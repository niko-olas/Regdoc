"""Client verso i servizi Azure: creati una volta per processo e riusati da tutte le richieste."""
import logging
import os
from functools import lru_cache

from azure.identity import DefaultAzureCredential

log = logging.getLogger("regdoc.api")

# Una credenziale per processo: in locale usa il login di az CLI, su App Service la managed identity.
credential = DefaultAzureCredential()

# Nomi dei feature flag in App Configuration e valore quando App Configuration non c'è (locale, test).
FLAG_INTERVENTIONS = "use-interventions"
FLAG_SEMANTIC_CACHE = "semantic-cache"
FLAG_DEFAULTS = {FLAG_INTERVENTIONS: True, FLAG_SEMANTIC_CACHE: False}


class Services:
    def __init__(self):
        from azure.cosmos import CosmosClient

        from api import cache
        from fielddata.db import create_pool
        from shared.config import RuntimeConfig
        from shared.foundry import Embedder, openai_client

        self.config = RuntimeConfig(credential, FLAG_DEFAULTS)
        self.embedder = Embedder(os.environ["FOUNDRY_ENDPOINT"], credential)
        # Meno tentativi degli embedding: c'è un tecnico che aspetta la risposta.
        self.chat = openai_client(os.environ["FOUNDRY_ENDPOINT"], credential, max_retries=3)
        self.chat_deployment = os.getenv("CHAT_DEPLOYMENT", "gpt-4.1-mini")
        self.chunks = (
            CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=credential)
            .get_database_client("regdoc")
            .get_container_client("chunks")
        )
        self.pool = create_pool(credential, min_size=1, max_size=int(os.getenv("PG_POOL_MAX", "5")))
        self.cache = None
        if os.getenv("REDIS_HOST"):
            try:
                self.cache = cache.AnswerCache(cache.connect(os.environ["REDIS_HOST"]))
            except Exception:  # noqa: BLE001 — la cache è un'ottimizzazione: senza, l'app risponde comunque
                log.warning("Redis non raggiungibile: cache disattivata", exc_info=True)


@lru_cache(maxsize=1)
def get_services() -> Services:
    return Services()
