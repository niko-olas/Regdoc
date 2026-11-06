"""Ispezione della cache delle risposte su Azure Managed Redis, in sola lettura.

  versions  versione dei manuali per dominio (regdoc:ver:*): sale di 1 a ogni manuale indicizzato
  keys      risposte in cache con il TTL residuo, e lo stato dell'indice vettoriale (FT.INFO)
  pairs     distanza coseno tra coppie di domande contro la soglia della cache semantica: le parafrasi
            devono restare sotto, le domande diverse sopra (non serve Redis, solo gli embedding)

Uso, dalla radice con il venv di sviluppo:
    $env:REDIS_HOST = "<output redisHost di main.bicep>"        # versions, keys
    $env:FOUNDRY_ENDPOINT = "<output foundryEndpoint>"           # pairs
    .venv\\Scripts\\python.exe scripts\\tools\\redis_peek.py versions|keys|pairs

Richiede l'access policy di Redis per il proprio utente (redisUser nel Bicep) e Cognitive Services OpenAI User.
"""
import math
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from api.cache import SEM_INDEX, SEM_PREFIX, SEMANTIC_MAX_DISTANCE, TTL_SECONDS, connect  # noqa: E402

# (domanda, variante, la cache semantica deve trattarle come la stessa domanda?)
PAIRS = [
    ("Come si pulisce il braciere?", "Come pulisco il braciere?", True),
    ("La stufa va in allarme sonda fumi, cosa controllo?", "Allarme sonda fumi sulla stufa: cosa devo verificare?", True),
    ("Ogni quanto va fatta la manutenzione?", "Con che frequenza si fa la manutenzione?", True),
    ("Come si imposta l'ora?", "Come regolo l'orologio della stufa?", True),
    ("Come si pulisce il braciere?", "Come si pulisce il vetro?", False),
    ("Allarme sonda fumi, cosa controllo?", "Allarme depressione, cosa controllo?", False),
    ("Come si accende la stufa?", "Come si spegne la stufa?", False),
    ("Quanto pellet consuma al giorno?", "Che tipo di pellet devo usare?", False),
]


def cosine_distance(a: list[float], b: list[float]) -> float:
    """1 - similarità coseno: la stessa metrica (COSINE) dell'indice RediSearch."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return 1 - dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def _scan(r, pattern: str) -> list[str]:
    return sorted(k.decode() if isinstance(k, bytes) else k for k in r.scan_iter(match=pattern, count=500))


def versions() -> None:
    r = connect(os.environ["REDIS_HOST"])
    keys = _scan(r, "regdoc:ver:*")
    for key in keys:
        print(f"{key} = {int(r.get(key))}")
    if not keys:
        print("nessuna versione: nessun manuale indicizzato dall'ultima creazione di Redis")


def keys() -> None:
    r = connect(os.environ["REDIS_HOST"])
    for label, pattern in (("risposte esatte", "regdoc:answer:*"), ("risposte semantiche", f"{SEM_PREFIX}*")):
        found = _scan(r, pattern)
        print(f"{label}: {len(found)}")
        for key in found[:10]:
            ttl = r.ttl(key)
            print(f"  {key}  TTL {ttl} s ({ttl / 3600:.1f} h su {TTL_SECONDS / 3600:.0f} h)")
    info = r.ft(SEM_INDEX).info()
    print(f"\nindice {SEM_INDEX}: documenti {info.get('num_docs')}, errori di indicizzazione "
          f"{info.get('hash_indexing_failures')}")


def pairs() -> None:
    from azure.identity import DefaultAzureCredential

    from shared.foundry import Embedder

    texts = [t for a, b, _ in PAIRS for t in (a, b)]
    vectors = Embedder(os.environ["FOUNDRY_ENDPOINT"], DefaultAzureCredential()).embed(texts)
    print(f"soglia della cache semantica: {SEMANTIC_MAX_DISTANCE}\n")
    wrong = 0
    for i, (a, b, same) in enumerate(PAIRS):
        distance = cosine_distance(vectors[2 * i], vectors[2 * i + 1])
        hit = distance <= SEMANTIC_MAX_DISTANCE
        ok = hit == same
        wrong += not ok
        print(f"{'ok ' if ok else 'NO '} {distance:.4f}  {'hit ' if hit else 'miss'}  atteso {'hit ' if same else 'miss'}"
              f"  {a!r} / {b!r}")
    print(f"\n{len(PAIRS) - wrong}/{len(PAIRS)} coppie trattate come atteso")


if __name__ == "__main__":
    commands = {"versions": versions, "keys": keys, "pairs": pairs}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"uso: redis_peek.py {'|'.join(commands)}")
    commands[sys.argv[1]]()
