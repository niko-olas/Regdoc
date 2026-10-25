import json

import pytest
from pypdf import PdfWriter

from shared.models import KIND_CHUNK, KIND_MANIFEST, document_id_for, manifest_for
from worker.chunking import build_chunks, split_text
from worker.errors import InvalidDocument, InvalidMessage
from worker.messages import parse_body
from worker.pdf import extract_pages
from worker.stores.cosmos import CosmosVectorStore

BODY = {
    "event_id": "evt-1",
    "domain": "stufe-pellet",
    "manufacturer": "edilkamin",
    "model": "blade-h",
    "doc_type": "uso-manutenzione",
    "file_name": "manuale.pdf",
    "blob_path": "stufe-pellet/edilkamin/blade-h/uso-manutenzione/manuale.pdf",
    "blob_url": "https://example.blob.core.windows.net/documents/stufe-pellet/edilkamin/blade-h/uso-manutenzione/manuale.pdf",
    "attributes": {"potenza_kw": "12"},
    "etag": "0x8DC0001",
}


def test_parse_body_legge_il_messaggio_della_function():
    request = parse_body(json.dumps(BODY))
    assert request.domain == "stufe-pellet"
    assert request.attributes == {"potenza_kw": "12"}


@pytest.mark.parametrize("raw", ["non json", json.dumps({"domain": "stufe-pellet"})])
def test_parse_body_rifiuta_messaggi_non_validi(raw):
    with pytest.raises(InvalidMessage):
        parse_body(raw)


def test_document_id_stabile_e_senza_slash():
    a = document_id_for(BODY["blob_path"])
    assert a == document_id_for(BODY["blob_path"])
    assert "/" not in a
    assert a != document_id_for("altro/percorso.pdf")


def test_split_text_testo_corto_un_solo_chunk():
    assert split_text("Pulizia   del\nbraciere.") == ["Pulizia del braciere."]


def test_split_text_rispetta_dimensione_e_sovrapposizione():
    words = [f"parola{i}" for i in range(1000)]
    chunks = split_text(" ".join(words), max_chars=200, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    # Nessuna parola spezzata e nessuna parola persa.
    assert {w for c in chunks for w in c.split()} == set(words)
    # Sovrapposizione: l'inizio di ogni chunk compare alla fine del precedente.
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.split()[0] in prev.split()


def test_build_chunks_id_deterministici_e_pagina():
    request = parse_body(json.dumps(BODY))
    chunks = build_chunks(request, [(1, "testo pagina uno"), (3, "testo pagina tre")])
    doc_id = document_id_for(BODY["blob_path"])
    assert [c.id for c in chunks] == [f"{doc_id}-0000", f"{doc_id}-0001"]
    assert [c.page for c in chunks] == [1, 3]
    assert all(c.document_id == doc_id and c.domain == "stufe-pellet" and c.kind == KIND_CHUNK for c in chunks)


def test_manifest_nella_partizione_dei_chunk_con_conteggi_ed_etag():
    request = parse_body(json.dumps(BODY))
    chunks = build_chunks(request, [(1, "testo pagina uno"), (3, "testo pagina tre")])
    manifest = manifest_for(chunks, request.etag)
    doc_id = document_id_for(BODY["blob_path"])
    assert manifest["id"] == f"{doc_id}-manifest" and manifest["kind"] == KIND_MANIFEST
    # Stessa partition key [domain, document_id] dei chunk: è ciò che garantisce l'ordine nel change feed.
    assert (manifest["domain"], manifest["document_id"]) == ("stufe-pellet", doc_id)
    assert manifest["chunk_count"] == 2 and manifest["pages"] == 2 and manifest["source_etag"] == "0x8DC0001"


class FakeContainer:
    """Registra le operazioni nell'ordine in cui il worker le fa."""

    def __init__(self, existing_ids):
        self.existing_ids = existing_ids
        self.ops = []
        self.client_connection = type("Conn", (), {"last_response_headers": {"x-ms-request-charge": "1"}})()

    def upsert_item(self, item):
        self.ops.append(("upsert", item["id"]))

    def query_items(self, query, parameters, partition_key):
        return [{"id": i} for i in self.existing_ids]

    def delete_item(self, item, partition_key):
        self.ops.append(("delete", item))


def test_store_cancella_i_chunk_in_piu_e_scrive_il_manifest_per_ultimo():
    request = parse_body(json.dumps(BODY))
    chunks = build_chunks(request, [(1, "uno"), (2, "due")])
    manifest = manifest_for(chunks, request.etag)
    doc_id = chunks[0].document_id
    # Caricamento precedente più lungo: 3 chunk e il suo manifest.
    container = FakeContainer([f"{doc_id}-0000", f"{doc_id}-0001", f"{doc_id}-0002", f"{doc_id}-manifest"])
    store = CosmosVectorStore.__new__(CosmosVectorStore)
    store._container = container

    stats = store.replace_document("stufe-pellet", doc_id, chunks, manifest)

    assert container.ops == [("upsert", f"{doc_id}-0000"), ("upsert", f"{doc_id}-0001"),
                             ("delete", f"{doc_id}-0002"), ("upsert", f"{doc_id}-manifest")]
    assert stats["upserted"] == 2 and stats["deleted"] == 1


def test_extract_pages_rifiuta_file_non_pdf():
    with pytest.raises(InvalidDocument):
        extract_pages(b"PDF di prova")


def test_extract_pages_rifiuta_pdf_senza_testo(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    path = tmp_path / "vuoto.pdf"
    writer.write(path)
    with pytest.raises(InvalidDocument):
        extract_pages(path.read_bytes())
