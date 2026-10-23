from datetime import datetime, timedelta, timezone

import pytest

from ingestion.catalog_store import indexed_record, upload_record
from ingestion.documents import DocumentRef, build_message
from ingestion.indexed_events import summarize_changes

NOW = datetime(2026, 10, 23, 20, 0, tzinfo=timezone.utc)
REF = DocumentRef("stufe-pellet", "extraflame", "karolina", "manuale-utente", "karolina.pdf",
                  "stufe-pellet/extraflame/karolina/manuale-utente/karolina.pdf")


def test_il_messaggio_di_on_blob_created_diventa_una_riga_del_catalogo():
    body = build_message("evt-1", REF, "https://x/documents/...", {"potenza_kw": "8"}, "application/pdf", 1234, "etag")
    record = upload_record(body, NOW)
    assert record["blob_path"] == REF.blob_path and record["file_name"] == "karolina.pdf"
    assert record["size_bytes"] == 1234 and record["uploaded_at"] == NOW
    assert '"potenza_kw": "8"' in record["attributes"]


def test_un_messaggio_incompleto_e_rifiutato():
    # L'eccezione fa ritentare il messaggio e, dopo maxDeliveryCount, lo manda in dead-letter.
    with pytest.raises(ValueError, match="model"):
        upload_record({"blob_path": "a/b", "domain": "d", "manufacturer": "m", "doc_type": "t", "file_name": "f"}, NOW)


def test_il_change_feed_e_il_caricamento_scrivono_la_stessa_riga():
    chunks = [{"id": f"doc-{i:04d}", "domain": REF.domain, "document_id": "doc", "manufacturer": REF.manufacturer,
               "model": REF.model, "doc_type": REF.doc_type, "blob_path": REF.blob_path} for i in range(3)]
    [summary] = summarize_changes(chunks)
    record = indexed_record(summary, NOW + timedelta(minutes=2))
    uploaded = upload_record(build_message("e", REF, "u", {}, None, 1, "t"), NOW)
    # Stessa chiave e stessi campi fissi: chi arriva per primo crea la riga, l'altro la completa.
    assert {k: record[k] for k in ("blob_path", "domain", "manufacturer", "model", "doc_type", "file_name")} == \
           {k: uploaded[k] for k in ("blob_path", "domain", "manufacturer", "model", "doc_type", "file_name")}
