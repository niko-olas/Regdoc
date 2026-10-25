from functions.changefeed.indexed_events import KIND_MANIFEST, summarize_changes
from shared.models import KIND_MANIFEST as SHARED_KIND_MANIFEST


def chunk(document_id: str, index: int, domain: str = "stufe-pellet") -> dict:
    return {
        "id": f"{document_id}-{index:04d}",
        "kind": "chunk",
        "domain": domain,
        "document_id": document_id,
        "manufacturer": "extraflame",
        "model": "karolina",
        "doc_type": "manuale-utente",
        "blob_path": f"{domain}/extraflame/karolina/manuale-utente/{document_id}.pdf",
    }


def manifest(document_id: str, chunk_count: int, domain: str = "stufe-pellet") -> dict:
    return {**chunk(document_id, 0, domain), "id": f"{document_id}-manifest", "kind": "manifest",
            "chunk_count": chunk_count, "pages": 56}


def test_un_evento_per_documento_completo():
    docs = [chunk("a", i) for i in range(66)] + [manifest("a", 106)]
    [summary] = summarize_changes(docs)
    assert summary["document_id"] == "a" and summary["chunk_count"] == 106 and summary["pages"] == 56


def test_un_lotto_di_soli_chunk_non_produce_eventi():
    # Il primo lotto di un manuale diviso dal change feed: il documento non è ancora completo.
    assert summarize_changes([chunk("a", i) for i in range(40)]) == []


def test_stesso_document_id_in_domini_diversi_resta_distinto():
    summaries = summarize_changes([manifest("a", 1, "stufe-pellet"), manifest("a", 1, "caldaie")])
    assert len(summaries) == 2


def test_ignora_documenti_che_non_sono_del_worker():
    assert summarize_changes([{"id": "x"}, {"domain": "stufe-pellet"}]) == []


def test_tipo_del_manifest_uguale_a_quello_del_worker():
    # La Function App non importa src/shared: se i due valori divergono, nessun evento parte più.
    assert KIND_MANIFEST == SHARED_KIND_MANIFEST
