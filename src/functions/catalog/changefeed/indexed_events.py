"""Dalle modifiche del change feed agli eventi "documento indicizzato".

Logica pura, senza SDK Azure: si testa con pytest senza risorse cloud.
"""

EVENT_TYPE = "RegDoc.Document.Indexed"
EVENT_SOURCE = "/regdoc/changefeed"
# Stesso valore di shared.models.KIND_MANIFEST: la Function App non include src/shared
# (deploy separati), un test verifica che restino uguali.
KIND_MANIFEST = "manifest"


def summarize_changes(docs: list[dict]) -> list[dict]:
    """I documenti completati in questo lotto del change feed: uno per manifest.

    Il change feed riporta ogni chunk scritto, e un manuale (~100 chunk) arriva spesso in più lotti:
    un chunk dice solo che il documento sta cambiando. Il manifest, che il worker scrive per ultimo
    nella stessa partizione logica, dice che è completo; i chunk si ignorano.
    Rielaborare un messaggio riscrive il manifest e produce un secondo evento: i consumatori devono
    essere idempotenti (invalidare una cache due volte è innocuo).
    """
    by_document: dict[tuple[str, str], dict] = {}
    for doc in docs:
        if doc.get("kind") != KIND_MANIFEST:
            continue
        by_document[(doc["domain"], doc["document_id"])] = {
            "domain": doc["domain"],
            "document_id": doc["document_id"],
            "manufacturer": doc.get("manufacturer"),
            "model": doc.get("model"),
            "doc_type": doc.get("doc_type"),
            "blob_path": doc.get("blob_path"),
            "chunk_count": doc.get("chunk_count"),
            "pages": doc.get("pages"),
            "traceparent": doc.get("traceparent"),
        }
    return list(by_document.values())


def event_data(summary: dict) -> dict:
    """Dati dell'evento RegDoc.Document.Indexed: il riepilogo senza il contesto della traccia, che
    viaggia come estensione del CloudEvent e non fa parte del contenuto."""
    return {k: v for k, v in summary.items() if k != "traceparent"}
