"""Lettura del messaggio prodotto dalla Function di ingestion (src/ingestion/documents.py)."""
import json
from dataclasses import dataclass

from worker.errors import InvalidMessage

REQUIRED_FIELDS = ("domain", "manufacturer", "model", "doc_type", "file_name", "blob_path", "blob_url")


@dataclass(frozen=True)
class IndexRequest:
    domain: str
    manufacturer: str
    model: str
    doc_type: str
    file_name: str
    blob_path: str
    blob_url: str
    attributes: dict[str, str]


def parse_body(raw: str) -> IndexRequest:
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidMessage(f"corpo non JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise InvalidMessage("il corpo deve essere un oggetto JSON")

    missing = [f for f in REQUIRED_FIELDS if not body.get(f)]
    if missing:
        raise InvalidMessage(f"campi mancanti: {', '.join(missing)}")

    return IndexRequest(
        **{f: body[f] for f in REQUIRED_FIELDS},
        attributes=dict(body.get("attributes") or {}),
    )
