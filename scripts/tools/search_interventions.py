"""Cerca interventi simili a un sintomo descritto a parole (prova della ricerca pgvector).

Uso, dalla radice con il venv di sviluppo e PGHOST/PGUSER/FOUNDRY_ENDPOINT impostati:
    .venv\\Scripts\\python.exe scripts\\tools\\search_interventions.py "la stufa si spegne con errore fumi"
    .venv\\Scripts\\python.exe scripts\\tools\\search_interventions.py "..." --model karolina
    .venv\\Scripts\\python.exe scripts\\tools\\search_interventions.py "..." --explain
"""
import argparse
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from azure.identity import DefaultAzureCredential  # noqa: E402

from fielddata.db import connect  # noqa: E402
from fielddata.search import build_query, similar_interventions  # noqa: E402
from shared.foundry import Embedder  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("text", help="sintomo descritto dal tecnico")
    parser.add_argument("--domain", default="stufe-pellet")
    parser.add_argument("--manufacturer")
    parser.add_argument("--model")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--explain", action="store_true", help="mostra il piano di esecuzione (EXPLAIN ANALYZE)")
    args = parser.parse_args()

    credential = DefaultAzureCredential()
    embedder = Embedder(os.environ["FOUNDRY_ENDPOINT"], credential)
    vector = embedder.embed([args.text])[0]
    filters = dict(domain=args.domain, manufacturer=args.manufacturer, model=args.model, k=args.k)

    with connect(credential) as conn:
        if args.explain:
            sql, params = build_query(vector, **filters)
            for (line,) in conn.execute("EXPLAIN (ANALYZE, BUFFERS) " + sql, params).fetchall():
                print(re.sub(r"'\[[^\]]*\]'::vector", "'[...]'::vector", line))  # il vettore intero non serve
            conn.rollback()
            return
        results = similar_interventions(conn, vector, **filters)

    for r in results:
        print(f"{r.distance:.3f}  {r.external_ref}  {r.performed_on}  {r.manufacturer} {r.model}")
        print(f"       sintomo: {r.symptom}")
        print(f"       soluzione: {r.resolution}")
    if not results:
        print("(nessun intervento trovato con questi filtri)")


if __name__ == "__main__":
    main()
