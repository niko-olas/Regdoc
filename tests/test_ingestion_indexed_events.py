from ingestion.indexed_events import summarize_changes


def chunk(document_id: str, index: int, domain: str = "stufe-pellet") -> dict:
    return {
        "id": f"{document_id}-{index:04d}",
        "domain": domain,
        "document_id": document_id,
        "manufacturer": "extraflame",
        "model": "karolina",
        "doc_type": "manuale-utente",
        "blob_path": f"{domain}/extraflame/karolina/manuale-utente/{document_id}.pdf",
    }


def test_un_evento_per_documento_non_per_chunk():
    docs = [chunk("a", i) for i in range(106)] + [chunk("b", i) for i in range(3)]
    summaries = summarize_changes(docs)
    assert {s["document_id"]: s["chunks_changed"] for s in summaries} == {"a": 106, "b": 3}


def test_stesso_document_id_in_domini_diversi_resta_distinto():
    summaries = summarize_changes([chunk("a", 0, "stufe-pellet"), chunk("a", 0, "caldaie")])
    assert len(summaries) == 2


def test_ignora_documenti_che_non_sono_chunk():
    assert summarize_changes([{"id": "x"}, {"domain": "stufe-pellet"}]) == []
