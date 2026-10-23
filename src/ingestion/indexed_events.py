"""Dalle modifiche del change feed agli eventi "documento indicizzato".

Logica pura, senza SDK Azure: si testa con pytest senza risorse cloud.
"""

EVENT_TYPE = "RegDoc.Document.Indexed"
EVENT_SOURCE = "/regdoc/changefeed"


def summarize_changes(docs: list[dict]) -> list[dict]:
    """Raggruppa i chunk modificati per documento.

    Il change feed riporta ogni chunk scritto (un manuale = ~100 modifiche): a valle
    interessa sapere quali documenti sono cambiati, quindi un evento per documento.
    Uno stesso documento può comparire in due lotti consecutivi del feed e generare due
    eventi: i consumatori devono essere idempotenti (invalidare una cache due volte è innocuo).
    """
    by_document: dict[tuple[str, str], dict] = {}
    for doc in docs:
        domain, document_id = doc.get("domain"), doc.get("document_id")
        if not domain or not document_id:
            continue  # documento non prodotto dal worker: non è un chunk
        summary = by_document.setdefault((domain, document_id), {
            "domain": domain,
            "document_id": document_id,
            "manufacturer": doc.get("manufacturer"),
            "model": doc.get("model"),
            "doc_type": doc.get("doc_type"),
            "blob_path": doc.get("blob_path"),
            "chunks_changed": 0,
        })
        summary["chunks_changed"] += 1
    return list(by_document.values())
