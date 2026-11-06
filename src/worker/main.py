"""Worker di indicizzazione: subscription `indexer` → PDF → chunk → embedding → store vettoriali.

Avvio locale, dalla cartella src/:
    python -m worker.main
"""
import logging
import os
import signal
import time
from dataclasses import replace

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.servicebus import (
    AutoLockRenewer,
    ServiceBusClient,
    ServiceBusReceivedMessage,
    ServiceBusReceiver,
    ServiceBusReceiveMode,
)
from azure.storage.blob import BlobClient
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from worker.chunking import build_chunks
from shared import telemetry
from shared.foundry import Embedder
from shared.models import manifest_for
from worker.errors import InvalidDocument, PermanentError
from worker.messages import IndexRequest, parse_body
from worker.pdf import extract_pages
from worker.stores.base import VectorStore
from worker.stores.cosmos import CosmosVectorStore
from worker.tracing import context_from_message, current_traceparent

logger = logging.getLogger("regdoc.worker")
tracer = trace.get_tracer("regdoc.worker")
_running = True


def _stop(*_) -> None:
    global _running
    _running = False


def _download(blob_url: str, credential) -> bytes:
    try:
        return BlobClient.from_blob_url(blob_url, credential=credential).download_blob().readall()
    except ResourceNotFoundError as exc:
        # Il blob è stato cancellato dopo l'evento: non comparirà riprovando.
        raise InvalidDocument(f"blob non trovato: {blob_url}") from exc


def index_document(request: IndexRequest, credential, embedder: Embedder, stores: list[VectorStore]) -> list[dict]:
    pages = extract_pages(_download(request.blob_url, credential))
    chunks = build_chunks(request, pages)
    vectors = embedder.embed([c.text for c in chunks])
    chunks = [replace(c, embedding=v) for c, v in zip(chunks, vectors, strict=True)]
    manifest = manifest_for(chunks, request.etag, traceparent=current_traceparent())
    # Scrittura su tutti gli store configurati: oggi solo Cosmos. L'interfaccia permette di
    # aggiungerne o sostituirne uno senza toccare il resto della pipeline.
    return [store.replace_document(request.domain, chunks[0].document_id, chunks, manifest) for store in stores]


def _handle(receiver: ServiceBusReceiver, msg: ServiceBusReceivedMessage, credential, embedder, stores) -> None:
    retry_delay = None
    # Il messaggio porta il contesto della traccia di on_blob_created (traceparent): lo span di elaborazione
    # ne è figlio, così upload, indicizzazione e change feed formano una sola traccia in Application Insights.
    with tracer.start_as_current_span("worker.index_document", context=context_from_message(msg.application_properties),
                                      kind=SpanKind.CONSUMER) as span:
        span.set_attribute("messaging.message.id", msg.message_id or "")
        span.set_attribute("messaging.delivery_count", msg.delivery_count or 0)
        try:
            request = parse_body(str(msg))
            span.set_attribute("regdoc.blob_path", request.blob_path)
            started = time.monotonic()
            stats = index_document(request, credential, embedder, stores)
            logger.info(
                "Indicizzato %s in %.1fs: %s", request.blob_path, time.monotonic() - started, stats,
                extra={"blob_path": request.blob_path, "domain": request.domain, "message_id": msg.message_id},
            )
            receiver.complete_message(msg)

        except PermanentError as exc:
            span.set_status(Status(StatusCode.ERROR, exc.reason))
            logger.warning("Messaggio %s in dead-letter (%s): %s", msg.message_id, exc.reason, exc)
            receiver.dead_letter_message(msg, reason=exc.reason, error_description=str(exc)[:1024])

        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            retry_delay = min(2 ** msg.delivery_count, 30)
            logger.exception("Errore su %s (delivery_count=%d), abandon tra %ds",
                             msg.message_id, msg.delivery_count, retry_delay)

    if retry_delay is not None:
        # Errore transitorio (rete, 429 oltre i retry del client, Cosmos non disponibile).
        # abandon riconsegna subito: una breve attesa prima, crescente con i tentativi, evita
        # di bruciare i 5 tentativi di `indexer` in pochi secondi. Il lock resta valido
        # grazie all'AutoLockRenewer. L'attesa è fuori dallo span per non gonfiarne la durata.
        time.sleep(retry_delay)
        receiver.abandon_message(msg)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    # Una riga INFO per ogni richiesta HTTP del client openai (logger httpx o httpx2, a seconda della versione).
    for name in ("httpx", "httpx2"):
        logging.getLogger(name).setLevel(logging.WARNING)
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    credential = DefaultAzureCredential()
    # Tracce e log verso Application Insights (con Entra ID, come l'API); in locale senza connection string no.
    telemetry.setup("regdoc-worker", credential)
    embedder = Embedder(os.environ["FOUNDRY_ENDPOINT"], credential)
    stores: list[VectorStore] = [
        CosmosVectorStore(
            os.environ["COSMOS_ENDPOINT"],
            os.getenv("COSMOS_DATABASE", "regdoc"),
            os.getenv("COSMOS_CONTAINER", "chunks"),
            credential,
        ),
    ]

    topic = os.getenv("SERVICEBUS_TOPIC", "documents")
    subscription = os.getenv("SERVICEBUS_SUBSCRIPTION", "indexer")
    client = ServiceBusClient(os.environ["SERVICEBUS_FQDN"], credential=credential)
    # Il lock di `indexer` dura 1 minuto: un manuale lungo può richiedere di più tra
    # download, embedding e scritture. L'AutoLockRenewer rinnova il lock in background
    # fino a 10 minuti, così il messaggio non torna disponibile a un altro worker a metà lavoro.
    renewer = AutoLockRenewer(max_lock_renewal_duration=600)
    receiver = client.get_subscription_receiver(
        topic_name=topic,
        subscription_name=subscription,
        receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
        auto_lock_renewer=renewer,
    )

    with client, receiver, renewer:
        logger.info("In ascolto su %s/%s, store: %s", topic, subscription, [s.name for s in stores])
        while _running:
            # Un messaggio alla volta: l'elaborazione è lunga, e lasciare gli altri in coda
            # permette a più repliche (scaling KEDA) di dividersi il lavoro.
            for msg in receiver.receive_messages(max_message_count=1, max_wait_time=5):
                _handle(receiver, msg, credential, embedder, stores)
    logger.info("Arresto completato")


if __name__ == "__main__":
    main()
