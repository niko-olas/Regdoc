import json

import pytest

from audit.messages import InvalidMessage, parse_body, summarize

VALID = {
    "event_id": "evt-1",
    "domain": "stufe-pellet",
    "manufacturer": "edilkamin",
    "model": "blade-h",
    "doc_type": "uso-manutenzione",
    "blob_path": "stufe-pellet/edilkamin/blade-h/uso-manutenzione/manuale.pdf",
    "attributes": {"potenza_kw": "12"},
}


def test_parse_body_accetta_un_messaggio_valido():
    assert parse_body(json.dumps(VALID)) == VALID


@pytest.mark.parametrize(
    "raw",
    [
        "non sono json",
        json.dumps(["una", "lista"]),
        json.dumps({"domain": "stufe-pellet"}),  # mancano event_id e blob_path
    ],
)
def test_parse_body_rifiuta_messaggi_non_elaborabili(raw):
    with pytest.raises(InvalidMessage):
        parse_body(raw)


def test_summarize_non_include_gli_attributi_liberi():
    summary = summarize(VALID)
    assert summary["blob_path"] == VALID["blob_path"]
    assert "attributes" not in summary
