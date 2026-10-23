"""Ricerca nei manuali su Cosmos DB, con la stessa funzione usata dall'API (diagnosi delle risposte).

Uso, dalla radice con il venv di sviluppo e COSMOS_ENDPOINT, FOUNDRY_ENDPOINT impostati:
    .venv\\Scripts\\python.exe scripts\\tools\\search_cosmos.py "come si pulisce il braciere?"
    .venv\\Scripts\\python.exe scripts\\tools\\search_cosmos.py "..." --manufacturer extraflame --model karolina --k 3

Richiede: Cosmos DB Built-in Data Reader/Contributor e Cognitive Services OpenAI User.
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from azure.cosmos import CosmosClient  # noqa: E402
from azure.identity import DefaultAzureCredential  # noqa: E402

from api.retrieval import search_manuals  # noqa: E402
from shared.foundry import Embedder  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--domain", default="stufe-pellet")
    parser.add_argument("--manufacturer")
    parser.add_argument("--model")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    credential = DefaultAzureCredential()
    vector = Embedder(os.environ["FOUNDRY_ENDPOINT"], credential).embed([args.question])[0]
    container = (
        CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=credential)
        .get_database_client("regdoc")
        .get_container_client("chunks")
    )
    pages, ru = search_manuals(container, vector, domain=args.domain, manufacturer=args.manufacturer,
                               model=args.model, k=args.k)

    print(f'Domanda: "{args.question}"  ({ru} RU)\n')
    for p in pages:
        print(f"[{p.score:.3f}] {p.file_name} — pagina {p.page}")
        print(f"    {p.text[:300]}...\n")


if __name__ == "__main__":
    main()
