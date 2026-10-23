"""Divisione del testo in chunk da indicizzare."""
import re

from shared.models import Chunk, document_id_for
from worker.messages import IndexRequest

# ~1500 caratteri ≈ 300-400 token: abbastanza contesto per rispondere, abbastanza piccolo
# perché l'embedding rappresenti un solo argomento. La sovrapposizione evita di spezzare
# a metà un'istruzione che sta a cavallo tra due chunk.
MAX_CHARS = 1500
OVERLAP_CHARS = 200


def split_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return [text] if text else []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # Taglia sull'ultimo spazio, per non spezzare le parole.
            cut = text.rfind(" ", start + max_chars // 2, end)
            end = cut if cut != -1 else end
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        # Il chunk successivo riparte un po' prima, dall'inizio di una parola.
        next_start = text.find(" ", max(end - overlap, start + 1), end)
        start = next_start + 1 if next_start != -1 else end
    return chunks


def build_chunks(request: IndexRequest, pages: list[tuple[int, str]]) -> list[Chunk]:
    document_id = document_id_for(request.blob_path)
    chunks = []
    for page, text in pages:
        for piece in split_text(text):
            index = len(chunks)
            chunks.append(Chunk(
                # Id deterministico: rielaborare lo stesso messaggio riscrive gli stessi documenti.
                id=f"{document_id}-{index:04d}",
                domain=request.domain,
                document_id=document_id,
                manufacturer=request.manufacturer,
                model=request.model,
                doc_type=request.doc_type,
                file_name=request.file_name,
                blob_path=request.blob_path,
                page=page,
                chunk_index=index,
                text=piece,
                attributes=request.attributes,
            ))
    return chunks
