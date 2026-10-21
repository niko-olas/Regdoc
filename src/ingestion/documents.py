"""Dal subject di un evento BlobCreated al messaggio per il topic `documents`.

Logica pura, senza SDK Azure: si testa con pytest senza risorse cloud.
"""
from dataclasses import asdict, dataclass

CONTAINER = "documents"
_SUBJECT_PREFIX = f"/blobServices/default/containers/{CONTAINER}/blobs/"


class InvalidBlobPath(ValueError):
    """Il blob non rispetta documents/{domain}/{manufacturer}/{model}/{doc_type}/{file}."""


@dataclass(frozen=True)
class DocumentRef:
    domain: str
    manufacturer: str
    model: str
    doc_type: str
    file_name: str
    blob_path: str  # percorso dentro il container, es. stufe-pellet/edilkamin/...


def parse_subject(subject: str) -> DocumentRef:
    """Estrae i campi fissi dal subject Event Grid di un blob.

    Esempio di subject:
    /blobServices/default/containers/documents/blobs/stufe-pellet/edilkamin/blade-h/uso-manutenzione/manuale.pdf
    """
    if not subject.startswith(_SUBJECT_PREFIX):
        raise InvalidBlobPath(f"blob fuori dal container '{CONTAINER}': {subject}")

    blob_path = subject[len(_SUBJECT_PREFIX):]
    parts = blob_path.split("/")
    if len(parts) != 5 or not all(parts):
        raise InvalidBlobPath(
            "atteso {domain}/{manufacturer}/{model}/{doc_type}/{file}, "
            f"trovato: {blob_path}"
        )

    domain, manufacturer, model, doc_type, file_name = parts
    return DocumentRef(domain, manufacturer, model, doc_type, file_name, blob_path)


def build_message(
    event_id: str,
    ref: DocumentRef,
    blob_url: str,
    metadata: dict[str, str],
    content_type: str | None,
    size: int,
    etag: str,
) -> dict:
    """Corpo JSON del messaggio: campi fissi + attributi liberi dai metadati del blob."""
    return {
        "event_id": event_id,
        **asdict(ref),
        "blob_url": blob_url,
        "content_type": content_type,
        "size": size,
        "etag": etag,
        # x-ms-meta-* del blob: il codice non li interpreta, li passa e basta.
        "attributes": dict(metadata),
    }
