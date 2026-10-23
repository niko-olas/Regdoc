"""Cache delle risposte su Azure Managed Redis: esatta e semantica, con invalidazione per versione.

Chiavi:
  regdoc:ver:{domain}                          versione dei manuali del dominio (INCR dal change feed)
  regdoc:answer:{domain}:v{ver}:{hash}         risposta per domanda identica (stringa JSON)
  regdoc:sem:{domain}:v{ver}:{hash}            hash con domanda, risposta ed embedding (cache semantica)

Invalidazione per VERSIONE e non per cancellazione: quando un manuale del dominio cambia, la
funzione on_chunks_changed incrementa regdoc:ver:{domain}. Le risposte vecchie hanno la versione
vecchia nella chiave, quindi nessuno le trova più; spariscono da sole alla scadenza del TTL.
Niente SCAN + DEL su migliaia di chiavi, ed è idempotente rispetto a eventi duplicati.
"""
import hashlib
import json
import logging
import struct

import redis
from redis.commands.search.field import TagField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

log = logging.getLogger("regdoc.cache")

# Stessa chiave usata da src/ingestion/changefeed.py: le due app non condividono codice
# (deploy separati), un test verifica che restino uguali.
VERSION_KEY = "regdoc:ver:{domain}"
SEM_PREFIX = "regdoc:sem:"
SEM_INDEX = "regdoc-sem-idx"
# 24 ore: una risposta vecchia di un giorno è accettabile per un manuale (che cambia raramente e
# comunque invalida la versione); il TTL serve soprattutto a liberare memoria dalle chiavi orfane.
TTL_SECONDS = 24 * 3600
# Distanza coseno massima per considerare "la stessa domanda" due frasi diverse (0 = identiche).
# Molto stretta: meglio un miss in più che rispondere alla domanda sbagliata.
SEMANTIC_MAX_DISTANCE = 0.06
DIMENSIONS = 1536
# Versione del formato della risposta: cambiarla rende irraggiungibili le risposte salvate con il
# formato precedente, come fa la versione dei manuali per i contenuti.
RESPONSE_FORMAT = 2


def scope_of(domain: str, manufacturer: str | None, model: str | None, use_interventions: bool,
             serial_number: str | None = None) -> str:
    """La stessa domanda ha risposte diverse per modelli diversi, con/senza interventi e per impianti
    diversi (la risposta usa lo storico dell'impianto): tutto ciò che cambia la risposta entra nella chiave."""
    return (f"f{RESPONSE_FORMAT}|{domain}|{manufacturer or '*'}|{model or '*'}|{serial_number or '*'}|"
            f"{'int' if use_interventions else 'man'}")


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]


def normalize(question: str) -> str:
    return " ".join(question.lower().split())


class AnswerCache:
    def __init__(self, client: redis.Redis):
        self._r = client
        self._ensure_index()

    def _ensure_index(self) -> None:
        try:
            self._r.ft(SEM_INDEX).info()
        except redis.ResponseError:
            # Indice vettoriale di Redis (RediSearch) sugli hash con prefisso regdoc:sem:.
            # FLAT e non HNSW: poche migliaia di domande in cache, la ricerca esatta costa poco.
            # scope e ver sono TAG: filtri esatti, come il WHERE prima del KNN.
            self._r.ft(SEM_INDEX).create_index(
                [
                    TagField("scope"),
                    TagField("ver"),
                    VectorField("embedding", "FLAT", {"TYPE": "FLOAT32", "DIM": DIMENSIONS, "DISTANCE_METRIC": "COSINE"}),
                ],
                definition=IndexDefinition(prefix=[SEM_PREFIX], index_type=IndexType.HASH),
            )

    def version(self, domain: str) -> int:
        return int(self._r.get(VERSION_KEY.format(domain=domain)) or 0)

    def get_exact(self, domain: str, ver: int, scope: str, question: str) -> dict | None:
        raw = self._r.get(f"regdoc:answer:{domain}:v{ver}:{_hash(scope, normalize(question))}")
        return json.loads(raw) if raw else None

    def get_semantic(self, ver: int, scope: str, vector: list[float]) -> tuple[dict, float] | None:
        q = (
            Query(f"(@scope:{{{_hash(scope)}}} @ver:{{{ver}}})=>[KNN 1 @embedding $vec AS distance]")
            .return_fields("response", "distance")
            .dialect(2)
        )
        result = self._r.ft(SEM_INDEX).search(q, query_params={"vec": _to_bytes(vector)})
        if not result.docs:
            return None
        doc = result.docs[0]
        distance = float(doc.distance)
        if distance > SEMANTIC_MAX_DISTANCE:
            return None
        return json.loads(doc.response), distance

    def store(self, domain: str, ver: int, scope: str, question: str, vector: list[float], response: dict) -> None:
        payload = json.dumps(response, ensure_ascii=False, default=str)
        key_hash = _hash(scope, normalize(question))
        pipe = self._r.pipeline(transaction=False)
        pipe.set(f"regdoc:answer:{domain}:v{ver}:{key_hash}", payload, ex=TTL_SECONDS)
        sem_key = f"{SEM_PREFIX}{domain}:v{ver}:{key_hash}"
        pipe.hset(sem_key, mapping={
            # scope come hash esadecimale: i TAG di RediSearch richiederebbero l'escape di '-' e '|'.
            "scope": _hash(scope),
            "ver": str(ver),
            "question": question,
            "response": payload,
            "embedding": _to_bytes(vector),
        })
        pipe.expire(sem_key, TTL_SECONDS)
        pipe.execute()


def _to_bytes(vector: list[float]) -> bytes:
    # RediSearch vuole il vettore come blob binario float32 little-endian.
    return struct.pack(f"<{len(vector)}f", *vector)


def connect(host: str, port: int = 10000) -> redis.Redis:
    from redis_entraid.cred_provider import create_from_default_azure_credential

    return redis.Redis(
        host=host,
        port=port,
        ssl=True,
        # Token Entra ID al posto della access key (disattivata): il provider lo rinnova da solo
        # prima della scadenza e ri-autentica la connessione.
        credential_provider=create_from_default_azure_credential(("https://redis.azure.com/.default",)),
        socket_timeout=5,
        socket_connect_timeout=5,
    )
