"""Retrieval: pagine dei manuali (Cosmos DB) e interventi simili (PostgreSQL + pgvector)."""
from dataclasses import dataclass

from azure.cosmos import ContainerProxy


@dataclass
class ManualPage:
    file_name: str
    doc_type: str
    page: int
    text: str
    score: float


def search_manuals(container: ContainerProxy, vector: list[float], *, domain: str, manufacturer: str | None,
                   model: str | None, k: int = 5) -> tuple[list[ManualPage], float]:
    """I chunk più vicini alla domanda, solo dei manuali dello stesso modello. Restituisce anche le RU."""
    filters = ["c.domain = @domain"]
    params = [{"name": "@q", "value": vector}, {"name": "@domain", "value": domain}]
    if manufacturer:
        filters.append("c.manufacturer = @manufacturer")
        params.append({"name": "@manufacturer", "value": manufacturer})
    if model:
        filters.append("c.model = @model")
        params.append({"name": "@model", "value": model})
    # Il filtro su domain (primo livello della partition key gerarchica) limita la query alle
    # partizioni del dominio; TOP k è obbligatorio con VectorDistance, altrimenti Cosmos calcola e
    # restituisce molti più risultati del necessario (più RU e latenza).
    query = (
        f"SELECT TOP {int(k)} c.file_name, c.doc_type, c.page, c.text, VectorDistance(c.embedding, @q) AS score "
        f"FROM c WHERE {' AND '.join(filters)} ORDER BY VectorDistance(c.embedding, @q)"
    )
    items = list(container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
    charge = float(container.client_connection.last_response_headers.get("x-ms-request-charge", 0))
    return [ManualPage(i["file_name"], i["doc_type"], i["page"], i["text"], i["score"]) for i in items], charge
