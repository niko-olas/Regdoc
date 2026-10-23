"""Invalidazione delle risposte in cache quando i manuali di un dominio cambiano.

La chiave è la stessa di src/api/cache.py (VERSION_KEY): la Function App non può importare il
codice dell'API (deploy separati), un test controlla che restino uguali.
"""
import os

VERSION_KEY = "regdoc:ver:{domain}"

_client = None


def _get_client():
    global _client
    if _client is None:
        import redis
        from redis_entraid.cred_provider import create_from_default_azure_credential

        _client = redis.Redis(
            host=os.environ["REDIS_HOST"],
            port=10000,
            ssl=True,
            credential_provider=create_from_default_azure_credential(("https://redis.azure.com/.default",)),
            socket_timeout=5,
            socket_connect_timeout=5,
        )
    return _client


def bump_versions(domains: set[str], client=None) -> dict[str, int]:
    """Incrementa la versione di ogni dominio: le risposte in cache con la versione vecchia non
    vengono più lette e scadono col loro TTL. INCR è atomico e ripeterlo è innocuo, quindi gli
    eventi duplicati del change feed (at-least-once) non fanno danni."""
    if client is None:
        if not os.getenv("REDIS_HOST"):
            return {}
        client = _get_client()
    return {domain: client.incr(VERSION_KEY.format(domain=domain)) for domain in sorted(domains)}
