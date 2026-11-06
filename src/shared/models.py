"""Modelli condivisi tra i componenti: il worker li scrive, l'API (F4) li legge."""
import hashlib
from dataclasses import asdict, dataclass, field


def document_id_for(blob_path: str) -> str:
    """Id stabile di un documento, derivato dal percorso del blob.

    Ricaricare un file nello stesso percorso produce lo stesso id: la reindicizzazione
    sostituisce i chunk esistenti invece di duplicarli. L'hash evita i caratteri '/'
    del percorso, non ammessi negli id di Cosmos DB.
    """
    return hashlib.sha256(blob_path.encode("utf-8")).hexdigest()[:32]


# Tipi di item nel container `chunks`: i pezzi di testo dei manuali e, uno per documento, il manifest
# che il worker scrive per ultimo quando il documento è completo.
KIND_CHUNK = "chunk"
KIND_MANIFEST = "manifest"


@dataclass
class Chunk:
    id: str
    domain: str
    document_id: str
    manufacturer: str
    model: str
    doc_type: str
    file_name: str
    blob_path: str
    page: int
    chunk_index: int
    text: str
    attributes: dict[str, str] = field(default_factory=dict)
    embedding: list[float] | None = None
    kind: str = KIND_CHUNK

    def to_item(self) -> dict:
        return asdict(self)


def manifest_for(chunks: list[Chunk], source_etag: str | None = None, traceparent: str | None = None) -> dict:
    """Item "documento completo": stessa partizione logica dei suoi chunk, scritto dopo di loro."""
    first = chunks[0]
    return {
        "id": f"{first.document_id}-manifest",
        "kind": KIND_MANIFEST,
        "domain": first.domain,
        "document_id": first.document_id,
        "manufacturer": first.manufacturer,
        "model": first.model,
        "doc_type": first.doc_type,
        "file_name": first.file_name,
        "blob_path": first.blob_path,
        "chunk_count": len(chunks),
        "pages": len({c.page for c in chunks}),
        # Versione del blob indicizzata: dice quale caricamento ha prodotto questi chunk.
        "source_etag": source_etag,
        # Contesto W3C della traccia dell'indicizzazione: il change feed non trasporta header, quindi è il
        # manifest a portare la traccia fino a on_chunks_changed.
        "traceparent": traceparent,
    }
