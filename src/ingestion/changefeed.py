"""Change feed del container `chunks` → evento custom su Event Grid, catalogo dei documenti
e invalidazione della cache Redis.

Blueprint registrato in function_app.py: la funzione vive nella stessa Function App
dell'ingestion ma resta in un modulo separato.
"""
import logging
import os
from datetime import datetime, timezone

import azure.functions as func
from azure.core.messaging import CloudEvent
from azure.eventgrid import EventGridPublisherClient
from azure.identity import DefaultAzureCredential

from cache_invalidation import bump_versions
from catalog_store import UPSERT_INDEXED, connect, indexed_record
from indexed_events import EVENT_SOURCE, EVENT_TYPE, summarize_changes

bp = func.Blueprint()
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
def on_chunks_changed(docs: func.DocumentList) -> None:
    summaries = summarize_changes([doc.to_dict() for doc in docs])
    if not summaries:
        return

    events = [
        CloudEvent(
            source=EVENT_SOURCE,
            type=EVENT_TYPE,
            subject=f"{s['domain']}/{s['document_id']}",
            data=s,
        )
        for s in summaries
    ]
    _get_publisher().send(events)
    logging.info(
        "Change feed: %d modifiche, %d eventi %s pubblicati (%s)",
        len(docs), len(events), EVENT_TYPE, ", ".join(e.subject for e in events),
    )
    # Catalogo: il documento risulta indicizzato. Upsert idempotente, ripeterlo è innocuo.
    now = datetime.now(timezone.utc)
    with connect(_credential) as conn:
        for s in summaries:
            conn.execute(UPSERT_INDEXED, indexed_record(s, now))

    # Le risposte in cache citano i manuali vecchi: si invalidano dopo l'evento. Se Redis o
    # PostgreSQL falliscono, l'eccezione fa ritentare il lotto (retry policy sopra): rimandare
    # l'evento e riscrivere il catalogo è innocuo.
    versions = bump_versions({s["domain"] for s in summaries})
    if versions:
        logging.info("Cache invalidata: %s", versions)
