"""Connessione a PostgreSQL Flexible Server con un token Entra ID al posto della password."""
import os

import psycopg
from azure.core.credentials import TokenCredential
from azure.identity import DefaultAzureCredential
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

# Audience dei token per Azure Database for PostgreSQL (la stessa di MySQL).
TOKEN_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


def _conn_kwargs() -> dict:
    """PGHOST: <server>.postgres.database.azure.com
    PGUSER: per un utente, il suo UPN; per una managed identity, il nome con cui è stata
            registrata come ruolo nel server.
    """
    return {
        "host": os.environ["PGHOST"],
        "dbname": os.getenv("PGDATABASE", "regdoc"),
        "user": os.environ["PGUSER"],
        # Flexible Server accetta solo connessioni cifrate.
        "sslmode": "require",
    }


def connect(credential: TokenCredential | None = None, *, with_vector: bool = True) -> psycopg.Connection:
    """Apre una singola connessione autenticata con Entra ID (script, import, prove).

    Il token vale circa un'ora e serve solo all'apertura: una connessione già aperta resta valida.
    """
    credential = credential or DefaultAzureCredential()
    conn = psycopg.connect(**_conn_kwargs(), password=credential.get_token(TOKEN_SCOPE).token)
    if with_vector:
        # Fa arrivare le colonne vector come oggetti Vector invece che come stringhe.
        # Richiede che l'estensione esista già nel database.
        register_vector(conn)
    return conn


def create_pool(credential: TokenCredential | None = None, *, min_size: int = 1, max_size: int = 5,
                with_vector: bool = True) -> ConnectionPool:
    """Pool di connessioni per i servizi che restano accesi (l'API di F4).

    Aprire una connessione costa: TCP, TLS, token Entra e autenticazione, decine o centinaia di ms
    contro ~1 RTT di una query. Il pool le apre una volta e le presta a ogni richiesta.
    Lato applicazione e non PgBouncer: il PgBouncer integrato di Flexible Server non esiste sul tier
    Burstable. max_size va tenuto basso: B1ms ha max_connections=50, di cui 15 riservate, e il
    totale è condiviso da tutte le repliche dell'API (repliche x max_size <= connessioni libere).
    """
    credential = credential or DefaultAzureCredential()

    class EntraConnection(psycopg.Connection):
        # Il pool apre connessioni nuove anche ore dopo l'avvio (crescita, max_lifetime, riconnessioni):
        # il token va chiesto a ogni apertura, non una volta sola. DefaultAzureCredential lo tiene in
        # cache e lo rinnova prima della scadenza, quindi la chiamata è quasi sempre gratuita.
        @classmethod
        def connect(cls, conninfo: str = "", **kwargs):
            kwargs["password"] = credential.get_token(TOKEN_SCOPE).token
            return super().connect(conninfo, **kwargs)

    def configure(conn: psycopg.Connection) -> None:
        if with_vector:
            register_vector(conn)
            conn.commit()  # il pool accetta solo connessioni restituite fuori da una transazione

    return ConnectionPool(
        kwargs=_conn_kwargs(),
        connection_class=EntraConnection,
        configure=configure,
        min_size=min_size,
        max_size=max_size,
        name="regdoc",
        open=True,
    )
