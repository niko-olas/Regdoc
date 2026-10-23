"""Catalogo dei documenti: quali manuali esistono per un modello e se sono già interrogabili."""
from dataclasses import dataclass
from datetime import datetime

import psycopg


@dataclass
class CatalogDocument:
    file_name: str
    doc_type: str
    status: str
    uploaded_at: datetime | None
    indexed_at: datetime | None


def documents_for_model(conn: psycopg.Connection, domain: str, manufacturer: str, model: str) -> list[CatalogDocument]:
    # Usa ix_documents_model (domain, manufacturer, model); lo stato viene dalla vista documents_status.
    rows = conn.execute(
        """
        SELECT file_name, doc_type, status, uploaded_at, indexed_at
        FROM documents_status
        WHERE domain = %s AND manufacturer = %s AND model = %s
        ORDER BY doc_type, file_name
        """,
        (domain, manufacturer, model),
    ).fetchall()
    return [CatalogDocument(*r) for r in rows]
