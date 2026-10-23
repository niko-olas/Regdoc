"""Store vettoriale su Azure Cosmos DB for NoSQL."""
from azure.core.credentials import TokenCredential
from azure.cosmos import CosmosClient

from shared.models import Chunk
from worker.stores.base import VectorStore


class CosmosVectorStore(VectorStore):
    name = "cosmos"

    def __init__(self, endpoint: str, database: str, container: str, credential: TokenCredential):
        # Nessun livello di consistenza esplicito: vale quello dell'account (Session),
        # sufficiente perché il worker rilegga subito ciò che ha appena scritto.
        client = CosmosClient(endpoint, credential=credential)
        self._container = client.get_database_client(database).get_container_client(container)

    def _request_charge(self) -> float:
        # Ogni risposta di Cosmos riporta il costo dell'operazione in RU.
        return float(self._container.client_connection.last_response_headers.get("x-ms-request-charge", 0))

    def replace_document(self, domain: str, document_id: str, chunks: list[Chunk]) -> dict:
        # Partition key gerarchica completa: [domain, document_id]. Tutte le operazioni
        # di questo metodo restano dentro una sola partizione logica.
        pk = [domain, document_id]
        ru = 0.0

        # Upsert: crea o sostituisce. Con id deterministici, rielaborare lo stesso messaggio
        # riscrive gli stessi documenti invece di duplicarli.
        for chunk in chunks:
            self._container.upsert_item(chunk.to_item())
            ru += self._request_charge()

        # Se il documento è stato ricaricato più corto, restano chunk con indice più alto:
        # li troviamo con una query a partizione singola e li cancelliamo.
        # I valori della chiave sono ripetuti nel WHERE: con le partition key gerarchiche è
        # quello che garantisce l'instradamento alla partizione giusta.
        existing = self._container.query_items(
            query="SELECT c.id FROM c WHERE c.domain = @domain AND c.document_id = @document_id",
            parameters=[{"name": "@domain", "value": domain}, {"name": "@document_id", "value": document_id}],
            partition_key=pk,
        )
        keep = {chunk.id for chunk in chunks}
        stale = [item["id"] for item in existing if item["id"] not in keep]
        ru += self._request_charge()

        for item_id in stale:
            self._container.delete_item(item=item_id, partition_key=pk)
            ru += self._request_charge()

        return {"store": self.name, "upserted": len(chunks), "deleted": len(stale), "ru": round(ru, 2)}
