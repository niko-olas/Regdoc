"""Change feed del container `chunks` → evento custom su Event Grid, catalogo dei documenti
e invalidazione della cache Redis.

Blueprint registrato in function_app.py, come le altre funzioni della Function App.
"""
import logging
import os
from datetime import datetime, timezone

import azure.functions as func
from azure.core.messaging import CloudEvent
from azure.eventgrid import EventGridPublisherClient
from azure.identity import DefaultAzureCredential
from opentelemetry import propagate, trace
from opentelemetry.trace import Link

from changefeed.cache_invalidation import bump_versions
from catalog_store import UPSERT_INDEXED, connect, indexed_record
from changefeed.indexed_events import EVENT_SOURCE, EVENT_TYPE, event_data, summarize_changes

bp = func.Blueprint()
tracer = trace.get_tracer("regdoc.catalog")
_credential = DefaultAzureCredential()
_publisher: EventGridPublisherClient | None = None


def _get_publisher() -> EventGridPublisherClient:
    global _publisher
    if _publisher is None:
        # Entra ID (EventGrid Data Sender): le chiavi del topic sono disattivate.
        _publisher = EventGridPublisherClient(os.environ["EVENTGRID_TOPIC_ENDPOINT"], _credential)
    return _publisher


# Con il trigger Cosmos DB, se la funzione fallisce il lotto NON viene riletto: il change feed
# processor avanza comunque il segnalibro nel lease container. La retry policy fa ritentare
# lo stesso lotto prima di andare avanti, con attese crescenti.
@bp.retry(strategy="exponential_backoff", max_retry_count="5", minimum_interval="00:00:05", maximum_interval="00:05:00")
@bp.cosmos_db_trigger(
    arg_name="docs",
    # Connessione a identità: app setting CosmosDB__accountEndpoint, nessuna chiave.
    connection="CosmosDB",
    database_name="regdoc",
    container_name="chunks",
    lease_container_name="leases",
    # Con l'RBAC nativo il trigger non può creare container: `leases` è nel template Bicep.
    create_lease_container_if_not_exists=False,
)
def on_chunks_changed(docs: func.DocumentList, context: func.Context) -> None:
    summaries = summarize_changes([doc.to_dict() for doc in docs])
    if not summaries:
        return

    invocation = propagate.extract({"traceparent": context.trace_context.trace_parent})
    invocation_link = Link(trace.get_current_span(invocation).get_span_context())
    now = datetime.now(timezone.utc)
    with connect(_credential) as conn:
        for s in summaries:
            # Il change feed non trasporta il contesto della traccia: lo porta il manifest, scritto dal
            # worker. Uno span per documento, figlio della traccia dell'upload; un lotto raccoglie più
            # documenti e l'invocazione non può avere un solo padre, quindi resta collegata con un link.
            parent = propagate.extract({"traceparent": s["traceparent"]}) if s.get("traceparent") else invocation
            with tracer.start_as_current_span("catalog.document_indexed", context=parent,
                                              links=[invocation_link]) as span:
                span.set_attribute("regdoc.blob_path", s.get("blob_path") or "")
                span.set_attribute("regdoc.document_id", s["document_id"])
                # Con la traccia attiva l'SDK aggiunge il traceparent come estensione del CloudEvent:
                # chi consuma l'evento può continuare la stessa traccia.
                _get_publisher().send([CloudEvent(source=EVENT_SOURCE, type=EVENT_TYPE,
                                                  subject=f"{s['domain']}/{s['document_id']}", data=event_data(s))])
                # Catalogo: il documento risulta indicizzato solo ora che è completo (manifest).
                # Upsert idempotente, ripeterlo è innocuo.
                conn.execute(UPSERT_INDEXED, indexed_record(s, now))
                # Le risposte in cache citano i manuali vecchi: si invalidano dopo l'evento. Se Event Grid,
                # PostgreSQL o Redis falliscono, l'eccezione fa ritentare il lotto (retry policy sopra):
                # rimandare l'evento, riscrivere il catalogo e incrementare la versione sono innocui.
                versions = bump_versions({s["domain"]})
            logging.info("Documento completo %s/%s: evento %s, catalogo aggiornato, cache %s",
                         s["domain"], s["document_id"], EVENT_TYPE, versions or "non configurata")
