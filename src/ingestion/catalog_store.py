"""Catalogo dei documenti su PostgreSQL: cosa è stato caricato e se è già indicizzato.

Due scritture indipendenti sulla stessa riga, chiave `blob_path`:
- record_upload: dalla subscription `catalog` del topic (documento caricato)
- record_indexed: dal change feed di Cosmos (chunk scritti dal worker)
Lo stato non è una colonna: si ricava da uploaded_at e indexed_at (vedi la vista documents_status).
Così l'ordine di arrivo non conta: worker e catalogo lavorano in parallelo e un messaggio in
ritardo non può riportare un documento indicizzato a "in indicizzazione".
"""
import json
import os
from datetime import datetime

TOKEN_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"

UPSERT_UPLOAD = """
INSERT INTO documents (blob_path, domain, manufacturer, model, doc_type, file_name, size_bytes, attributes, uploaded_at)
VALUES (%(blob_path)s, %(domain)s, %(manufacturer)s, %(model)s, %(doc_type)s, %(file_name)s, %(size_bytes)s,
        %(attributes)s, %(uploaded_at)s)
ON CONFLICT (blob_path) DO UPDATE SET
    size_bytes = EXCLUDED.size_bytes,
    attributes = EXCLUDED.attributes,
    -- GREATEST: una riconsegna del messaggio di un caricamento precedente non sposta indietro la data.
    uploaded_at = GREATEST(documents.uploaded_at, EXCLUDED.uploaded_at)
"""

UPSERT_INDEXED = """
INSERT INTO documents (blob_path, domain, manufacturer, model, doc_type, file_name, indexed_at)
VALUES (%(blob_path)s, %(domain)s, %(manufacturer)s, %(model)s, %(doc_type)s, %(file_name)s, %(indexed_at)s)
ON CONFLICT (blob_path) DO UPDATE SET
    indexed_at = GREATEST(documents.indexed_at, EXCLUDED.indexed_at)
"""


def upload_record(body: dict, enqueued_at: datetime) -> dict:
    """Riga del catalogo dal messaggio pubblicato da on_blob_created."""
    missing = [k for k in ("blob_path", "domain", "manufacturer", "model", "doc_type", "file_name") if not body.get(k)]
    if missing:
        raise ValueError(f"messaggio senza {', '.join(missing)}")
    return {
        "blob_path": body["blob_path"],
        "domain": body["domain"],
        "manufacturer": body["manufacturer"],
        "model": body["model"],
        "doc_type": body["doc_type"],
        "file_name": body["file_name"],
        "size_bytes": body.get("size"),
        "attributes": json.dumps(body.get("attributes") or {}),
        # L'ora in cui il messaggio è entrato nel topic: subito dopo il caricamento del blob.
        "uploaded_at": enqueued_at,
    }


def indexed_record(summary: dict, indexed_at: datetime) -> dict:
    """Riga del catalogo da un riepilogo del change feed (vedi indexed_events.summarize_changes)."""
    blob_path = summary["blob_path"]
    return {
        "blob_path": blob_path,
        "domain": summary["domain"],
        "manufacturer": summary["manufacturer"],
        "model": summary["model"],
        "doc_type": summary["doc_type"],
        "file_name": blob_path.rsplit("/", 1)[-1],
        "indexed_at": indexed_at,
    }


def connect(credential):
    """Una connessione per invocazione: arriva un messaggio per documento caricato, il costo di
    apertura (~1 s) è trascurabile e non serve tenere un pool aperto in un'app che scala a zero."""
    import psycopg

    return psycopg.connect(
        host=os.environ["PGHOST"],
        dbname=os.getenv("PGDATABASE", "regdoc"),
        # Il ruolo PostgreSQL della managed identity porta il nome della Function App.
        user=os.environ["PGUSER"],
        password=credential.get_token(TOKEN_SCOPE).token,
        sslmode="require",
    )
