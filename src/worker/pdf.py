"""Estrazione del testo dai PDF, pagina per pagina, con pypdf."""
import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from worker.errors import InvalidDocument


def extract_pages(data: bytes) -> list[tuple[int, str]]:
    """Restituisce (numero di pagina da 1, testo) per ogni pagina con testo."""
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(n, (page.extract_text() or "").strip()) for n, page in enumerate(reader.pages, start=1)]
    except PdfReadError as exc:
        raise InvalidDocument(f"PDF non leggibile: {exc}") from exc

    pages = [(n, text) for n, text in pages if text]
    if not pages:
        # Tipico di un PDF scansionato (solo immagini): servirebbe OCR, es. Document Intelligence.
        raise InvalidDocument("nessun testo estraibile dal PDF")
    return pages
