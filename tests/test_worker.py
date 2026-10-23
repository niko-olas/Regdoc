import json

import pytest
from pypdf import PdfWriter

from shared.models import document_id_for
from worker.chunking import build_chunks, split_text
from worker.errors import InvalidDocument, InvalidMessage
from worker.messages import parse_body
from worker.pdf import extract_pages

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
    assert all(c.document_id == doc_id and c.domain == "stufe-pellet" for c in chunks)


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
