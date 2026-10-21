"""Lettura e validazione del corpo dei messaggi del topic `documents`.

Logica pura, senza SDK Azure: si testa con pytest senza risorse cloud.
"""
import json

# Campi senza i quali il messaggio non è registrabile in modo utile.
REQUIRED_FIELDS = ("event_id", "domain", "blob_path")


class InvalidMessage(ValueError):
    """Messaggio non elaborabile, qualunque sia il numero di tentativi."""


def parse_body(raw: str) -> dict:
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidMessage(f"corpo non JSON: {exc}") from exc

    if not isinstance(body, dict):
        raise InvalidMessage("il corpo deve essere un oggetto JSON")

    missing = [f for f in REQUIRED_FIELDS if f not in body]
    if missing:
        raise InvalidMessage(f"campi mancanti: {', '.join(missing)}")
    return body


def summarize(body: dict) -> dict:
    """Campi da registrare: niente attributi liberi, solo ciò che identifica il documento."""
    return {
        "event_id": body["event_id"],
        "domain": body["domain"],
        "manufacturer": body.get("manufacturer"),
        "model": body.get("model"),
        "doc_type": body.get("doc_type"),
        "blob_path": body["blob_path"],
    }
