import pytest

from ingestion.documents import InvalidBlobPath, build_message, parse_subject

PREFIX = "/blobServices/default/containers/documents/blobs/"


def test_parse_subject_estrae_i_campi_fissi():
    ref = parse_subject(PREFIX + "stufe-pellet/edilkamin/blade-h/uso-manutenzione/manuale.pdf")
    assert ref.domain == "stufe-pellet"
    assert ref.manufacturer == "edilkamin"
    assert ref.model == "blade-h"
    assert ref.doc_type == "uso-manutenzione"
    assert ref.file_name == "manuale.pdf"
    assert ref.blob_path == "stufe-pellet/edilkamin/blade-h/uso-manutenzione/manuale.pdf"


@pytest.mark.parametrize(
    "subject",
    [
        "/blobServices/default/containers/altro/blobs/a/b/c/d/e.pdf",  # container sbagliato
        PREFIX + "stufe-pellet/edilkamin/manuale.pdf",  # livelli mancanti
        PREFIX + "stufe-pellet/edilkamin/blade-h/uso/extra/manuale.pdf",  # livelli in più
        PREFIX + "stufe-pellet//blade-h/uso-manutenzione/manuale.pdf",  # segmento vuoto
    ],
)
def test_parse_subject_rifiuta_percorsi_non_conformi(subject):
    with pytest.raises(InvalidBlobPath):
        parse_subject(subject)


def test_build_message_unisce_campi_fissi_e_attributi_liberi():
    ref = parse_subject(PREFIX + "stufe-pellet/edilkamin/blade-h/uso-manutenzione/manuale.pdf")
    body = build_message(
        event_id="evt-1",
        ref=ref,
        blob_url="https://example.blob.core.windows.net/documents/stufe-pellet/x.pdf",
        metadata={"potenza_kw": "12"},
        content_type="application/pdf",
        size=1024,
        etag="0x1",
    )
    assert body["event_id"] == "evt-1"
    assert body["domain"] == "stufe-pellet"
    assert body["attributes"] == {"potenza_kw": "12"}
    assert body["content_type"] == "application/pdf"
