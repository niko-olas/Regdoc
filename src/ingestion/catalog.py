"""Subscription `catalog` del topic `documents` → riga nel catalogo dei documenti (PostgreSQL).

Secondo consumatore dello stesso topic dell'indexer (fan-out): ognuno riceve la sua copia di
ogni messaggio e la elabora con i suoi tempi, senza sapere dell'altro.
"""
import json
import logging

import azure.functions as func
from azure.identity import DefaultAzureCredential

from catalog_store import UPSERT_UPLOAD, connect, upload_record

bp = func.Blueprint()
_credential = DefaultAzureCredential()


# Settlement automatico (PeekLock): se la funzione termina senza errori il messaggio è completato;
# se solleva un'eccezione viene abbandonato e riconsegnato. Dopo maxDeliveryCount tentativi
# (3, impostato sulla subscription) Service Bus lo sposta nella dead-letter queue, dove resta
# da analizzare invece di bloccare i messaggi successivi.
@bp.service_bus_topic_trigger(
    arg_name="msg",
    topic_name="documents",
    subscription_name="catalog",
    # Connessione a identità: app setting ServiceBusConnection__fullyQualifiedNamespace, nessuna chiave.
    connection="ServiceBusConnection",
)
def on_document_uploaded(msg: func.ServiceBusMessage) -> None:
    # Un messaggio malformato fallisce a ogni tentativo e finisce in dead-letter: è il posto giusto.
    record = upload_record(json.loads(msg.get_body()), msg.enqueued_time_utc)
    with connect(_credential) as conn:
        conn.execute(UPSERT_UPLOAD, record)
    logging.info("Catalogo: %s registrato (MessageId=%s, consegna %s)",
                 record["blob_path"], msg.message_id, msg.delivery_count)
