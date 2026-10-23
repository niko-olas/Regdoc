"""Ricerca vettoriale su Cosmos DB: la domanda diventa un embedding, Cosmos trova i chunk più vicini.

Uso, dalla radice con il venv di sviluppo e le variabili COSMOS_ENDPOINT e FOUNDRY_ENDPOINT impostate:
    .venv\\Scripts\\python.exe infra\\scripts\\search_cosmos.py "come si pulisce il braciere?" [--domain stufe-pellet] [--k 5]

Richiede: Cosmos DB Built-in Data Reader/Contributor e Cognitive Services OpenAI User.
"""
import argparse
import os

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--domain", default="stufe-pellet")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    credential = DefaultAzureCredential()
    openai = AzureOpenAI(
        azure_endpoint=os.environ["FOUNDRY_ENDPOINT"],
        api_version="2024-10-21",
        azure_ad_token_provider=get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default"),
    )
    # La domanda va trasformata con lo STESSO modello usato per i chunk: vettori di modelli
    # diversi non sono confrontabili, anche se hanno le stesse dimensioni.
    query_vector = openai.embeddings.create(model="text-embedding-3-small", input=args.question).data[0].embedding

    container = (
        CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=credential)
        .get_database_client("regdoc")
        .get_container_client("chunks")
    )
    # VectorDistance con distanza cosine: 1 = identico, valori più alti = più simile.
    # ORDER BY VectorDistance usa il vector index; il WHERE sul primo livello della partition key
    # limita la ricerca alle partizioni del dominio invece di interrogarle tutte.
    query = (
        f"SELECT TOP {int(args.k)} c.file_name, c.page, c.text, VectorDistance(c.embedding, @q) AS score "
        "FROM c WHERE c.domain = @domain "
        "ORDER BY VectorDistance(c.embedding, @q)"
    )
    results = list(container.query_items(
        query=query,
        parameters=[{"name": "@q", "value": query_vector}, {"name": "@domain", "value": args.domain}],
        enable_cross_partition_query=True,
    ))
    charge = container.client_connection.last_response_headers.get("x-ms-request-charge")

    print(f'Domanda: "{args.question}"  (dominio {args.domain}, {charge} RU)\n')
    for r in results:
        print(f"[{r['score']:.3f}] {r['file_name']} — pagina {r['page']}")
        print(f"    {r['text'][:300]}...\n")


if __name__ == "__main__":
    main()
