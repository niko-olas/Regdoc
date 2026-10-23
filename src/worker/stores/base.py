"""Interfaccia comune agli store vettoriali: Cosmos DB (F2) e PostgreSQL con pgvector (F3)."""
from abc import ABC, abstractmethod

from shared.models import Chunk


class VectorStore(ABC):
    name: str

    @abstractmethod
    def replace_document(self, domain: str, document_id: str, chunks: list[Chunk]) -> dict:
        """Porta lo store a contenere esattamente questi chunk per il documento.

        Deve essere idempotente: lo stesso messaggio può essere elaborato più volte
        (at-least-once di Service Bus) senza duplicare né perdere dati.
        Restituisce statistiche da registrare nei log.
        """
