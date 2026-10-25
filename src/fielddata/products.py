"""Prodotti (dominio, marca, modello) su cui il tecnico può fare domande: il punto di partenza dell'interfaccia."""
from dataclasses import dataclass

import psycopg


@dataclass
class Product:
    domain: str
    manufacturer: str
    model: str
    indexed_documents: int


def list_products(conn: psycopg.Connection) -> list[Product]:
    # Un prodotto esiste se ha almeno un manuale nel catalogo o un impianto installato: anche senza
    # manuali le risposte possono usare gli interventi già fatti su quel modello. Nessun dato dei clienti.
    rows = conn.execute(
        """
        SELECT p.domain, p.manufacturer, p.model,
               count(d.file_name) FILTER (WHERE d.status = 'indicizzato') AS indexed_documents
        FROM (SELECT domain, manufacturer, model FROM documents_status
              UNION
              SELECT domain, manufacturer, model FROM installations) p
        LEFT JOIN documents_status d USING (domain, manufacturer, model)
        GROUP BY p.domain, p.manufacturer, p.model
        ORDER BY p.domain, p.manufacturer, p.model
        """
    ).fetchall()
    return [Product(*r) for r in rows]
