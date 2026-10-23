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

    def to_item(self) -> dict:
        return asdict(self)
