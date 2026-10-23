"""Riallinea il catalogo dei documenti con lo stato reale di Blob Storage e Cosmos DB.

Il catalogo si aggiorna da solo con gli eventi (subscription `catalog` e change feed). Questo script
serve quando gli eventi non bastano: documenti caricati prima che il catalogo esistesse, un messaggio
finito in dead-letter, un database ripristinato. Idempotente: usa gli stessi upsert della Function.

Uso, dalla radice con il venv di sviluppo e PGHOST/PGUSER, STORAGE_ACCOUNT, COSMOS_ENDPOINT impostati:
    .venv\\Scripts\\python.exe scripts\\db\\sync_catalog.py
"""
import os
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "ingestion"))

from azure.cosmos import CosmosClient  # noqa: E402
from azure.identity import DefaultAzureCredential  # noqa: E402
from azure.storage.blob import ContainerClient  # noqa: E402

from catalog_store import UPSERT_INDEXED, UPSERT_UPLOAD, indexed_record, upload_record  # noqa: E402
from documents import CONTAINER, InvalidBlobPath, parse_subject  # noqa: E402
from fielddata.db import connect  # noqa: E402


def main() -> None:
    credential = DefaultAzureCredential()
    container = ContainerClient(f"https://{os.environ['STORAGE_ACCOUNT']}.blob.core.windows.net", CONTAINER, credential=credential)
    uploads = []
    for blob in container.list_blobs(include=["metadata"]):
        try:
            # Stessa regola di on_blob_created: i campi fissi vengono dal percorso.
            ref = parse_subject(f"/blobServices/default/containers/{CONTAINER}/blobs/{blob.name}")
        except InvalidBlobPath:
            continue
        body = {**ref.__dict__, "size": blob.size, "attributes": blob.metadata or {}}
        uploads.append(upload_record(body, blob.last_modified))

    chunks = (
        CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=credential)
        .get_database_client("regdoc")
        .get_container_client("chunks")
    )
    # Un documento con almeno un chunk su Cosmos è interrogabile dall'API.
    indexed = list(chunks.query_items(
        "SELECT DISTINCT c.blob_path, c.domain, c.manufacturer, c.model, c.doc_type FROM c",
        enable_cross_partition_query=True,
    ))
    now = datetime.now(timezone.utc)

    with connect(credential, with_vector=False) as conn:
        for record in uploads:
            conn.execute(UPSERT_UPLOAD, record)
        for summary in indexed:
            conn.execute(UPSERT_INDEXED, indexed_record(summary, now))
        rows = conn.execute("SELECT status, count(*) FROM documents_status GROUP BY status ORDER BY status").fetchall()
    print(f"blob: {len(uploads)}, documenti indicizzati su Cosmos: {len(indexed)}")
    print("catalogo: " + (", ".join(f"{s} {n}" for s, n in rows) or "vuoto"))


if __name__ == "__main__":
    main()
