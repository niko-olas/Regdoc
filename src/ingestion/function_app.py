import json
import logging
import os
import threading

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage, ServiceBusSender
from azure.storage.blob import BlobClient

from changefeed import bp as changefeed_bp
from documents import InvalidBlobPath, build_message, parse_subject

app = func.FunctionApp()
app.register_functions(changefeed_bp)

# Gli SDK Azure registrano ogni richiesta HTTP (URL e header) a livello INFO:
# in Application Insights diventerebbero più righe dei log applicativi.
logging.getLogger("azure").setLevel(logging.WARNING)

# Credenziale e client creati una volta per istanza e riusati tra le invocazioni:
# aprire una connessione AMQP a ogni evento aggiunge latenza e, sotto carico,
# esaurisce le connessioni. In locale DefaultAzureCredential usa il login di
# az CLI, su Azure la managed identity della Function App.
_credential = DefaultAzureCredential()
_sender: ServiceBusSender | None = None
# Il sender dell'SDK non è thread-safe e il worker Python può eseguire più
# invocazioni in parallelo su thread diversi.
_sender_lock = threading.Lock()


def _get_sender() -> ServiceBusSender:
    global _sender
    if _sender is None:
        client = ServiceBusClient(os.environ["SERVICEBUS_FQDN"], credential=_credential)
        _sender = client.get_topic_sender(topic_name=os.environ.get("SERVICEBUS_TOPIC", "documents"))
    return _sender


@app.event_grid_trigger(arg_name="event")
def on_blob_created(event: func.EventGridEvent) -> None:
    try:
        ref = parse_subject(event.subject)
    except InvalidBlobPath as exc:
        # Errore permanente: sollevare un'eccezione farebbe ritentare Event Grid
        # per ore senza speranza di successo. Lo registriamo e chiudiamo l'evento.
        logging.warning("Evento %s ignorato: %s", event.id, exc)
        return

    blob_url = event.get_json()["url"]
    # L'evento non contiene i metadati x-ms-meta-*: vanno letti dal blob.
    props = BlobClient.from_blob_url(blob_url, credential=_credential).get_blob_properties()

    body = build_message(
        event_id=event.id,
        ref=ref,
        blob_url=blob_url,
        metadata=props.metadata,
        content_type=props.content_settings.content_type,
        size=props.size,
        etag=props.etag,
    )
    message = ServiceBusMessage(
        json.dumps(body),
        content_type="application/json",
        # MessageId = id dell'evento: Event Grid consegna at-least-once, e se
        # riconsegna lo stesso evento la duplicate detection del topic scarta la copia.
        message_id=event.id,
        # Proprietà applicative: abilitano filtri SQL sulle subscription
        # (es. solo domain = 'caldaie') senza dover leggere il body.
        application_properties={"domain": ref.domain, "doc_type": ref.doc_type},
    )

    # Un'eccezione qui (Service Bus irraggiungibile, permessi mancanti) è
    # transitoria: la lasciamo propagare così Event Grid ritenta la consegna.
    with _sender_lock:
        _get_sender().send_messages(message)

    logging.info("Pubblicato %s (%s) sul topic, MessageId=%s", ref.blob_path, ref.domain, event.id)
