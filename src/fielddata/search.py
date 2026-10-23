"""Ricerca di interventi simili: vettori (pgvector) + filtri relazionali nella stessa query."""
from dataclasses import dataclass
from datetime import date

import psycopg
from pgvector import Vector


@dataclass
class SimilarIntervention:
    external_ref: str
    performed_on: date
    manufacturer: str
    model: str
    symptom: str | None
    resolution: str
    distance: float


def build_query(query_vector: list[float], *, domain: str, manufacturer: str | None = None,
                model: str | None = None, kinds: tuple[str, ...] = ("guasto",), k: int = 5) -> tuple[str, dict]:
    """SQL e parametri della ricerca. I filtri opzionali entrano nel WHERE solo se valorizzati."""
    filters = ["i.domain = %(domain)s", "iv.kind = ANY(%(kinds)s)"]
    if manufacturer:
        filters.append("i.manufacturer = %(manufacturer)s")
    if model:
        filters.append("i.model = %(model)s")
    # `<=>` è la distanza coseno (0 = identici, 2 = opposti), la stessa metrica scelta per Cosmos.
    # Senza indice vettoriale PostgreSQL calcola la distanza su tutte le righe filtrate e le ordina:
    # ricerca esatta (recall 100%), costo lineare nel numero di righe. Gli indici HNSW/IVFFlat la
    # rendono approssimata ma sublineare, e con i filtri possono restituire meno di k righe.
    sql = f"""
        SELECT iv.external_ref, iv.performed_on, i.manufacturer, i.model, iv.symptom, iv.resolution,
               iv.embedding <=> %(q)s AS distance
        FROM interventions iv
        JOIN installations i ON i.id = iv.installation_id
        WHERE {" AND ".join(filters)}
        ORDER BY iv.embedding <=> %(q)s
        LIMIT %(k)s
    """
    params = {"q": Vector(query_vector), "domain": domain, "manufacturer": manufacturer,
              "model": model, "kinds": list(kinds), "k": k}
    return sql, params


def similar_interventions(conn: psycopg.Connection, query_vector: list[float], **filters) -> list[SimilarIntervention]:
    sql, params = build_query(query_vector, **filters)
    return [SimilarIntervention(*row) for row in conn.execute(sql, params).fetchall()]
