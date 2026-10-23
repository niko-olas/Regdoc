"""Import dei dati di esempio dal campo, con gli embedding degli interventi.

Ripetibile: usa le chiavi del "gestionale" (code, serial_number, external_ref) con
INSERT ... ON CONFLICT DO UPDATE, quindi rieseguirlo aggiorna senza duplicare.

Uso, dalla radice con il venv di sviluppo:
    $env:PGHOST = "<server>.postgres.database.azure.com"
    $env:PGUSER = "<il tuo UPN>"
    $env:FOUNDRY_ENDPOINT = "https://<risorsa>.cognitiveservices.azure.com/"
    .venv\\Scripts\\python.exe scripts\\db\\import_field_data.py
"""
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from azure.identity import DefaultAzureCredential  # noqa: E402

from fielddata.db import connect  # noqa: E402
from fielddata.interventions import embedding_text  # noqa: E402
from sample_data import generate  # noqa: E402
from shared.foundry import Embedder  # noqa: E402


def main() -> None:
    customers, installations, interventions = generate()
    credential = DefaultAzureCredential()

    print(f"Calcolo di {len(interventions)} embedding...")
    embedder = Embedder(os.environ["FOUNDRY_ENDPOINT"], credential)
    vectors = embedder.embed([embedding_text(i.symptom, i.resolution) for i in interventions])

    with connect(credential) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO customers (code, name, city) VALUES (%s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, city = EXCLUDED.city
                """,
                [(c.code, c.name, c.city) for c in customers],
            )
            customer_ids = dict(cur.execute("SELECT code, id FROM customers").fetchall())

            cur.executemany(
                """
                INSERT INTO installations (customer_id, domain, manufacturer, model, serial_number, installed_on, attributes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (serial_number) DO UPDATE SET
                    customer_id = EXCLUDED.customer_id, domain = EXCLUDED.domain, manufacturer = EXCLUDED.manufacturer,
                    model = EXCLUDED.model, installed_on = EXCLUDED.installed_on, attributes = EXCLUDED.attributes
                """,
                [(customer_ids[i.customer_code], i.domain, i.manufacturer, i.model, i.serial_number, i.installed_on,
                  json.dumps(i.attributes)) for i in installations],
            )
            installation_ids = dict(cur.execute("SELECT serial_number, id FROM installations").fetchall())

            cur.executemany(
                """
                INSERT INTO interventions (installation_id, external_ref, performed_on, kind, technician,
                                           symptom, resolution, duration_minutes, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (external_ref) DO UPDATE SET
                    installation_id = EXCLUDED.installation_id, performed_on = EXCLUDED.performed_on,
                    kind = EXCLUDED.kind, technician = EXCLUDED.technician, symptom = EXCLUDED.symptom,
                    resolution = EXCLUDED.resolution, duration_minutes = EXCLUDED.duration_minutes,
                    embedding = EXCLUDED.embedding
                """,
                [(installation_ids[i.serial_number], i.external_ref, i.performed_on, i.kind, i.technician,
                  i.symptom, i.resolution, i.duration_minutes, v) for i, v in zip(interventions, vectors, strict=True)],
            )

            counts = cur.execute(
                """
                SELECT (SELECT count(*) FROM customers), (SELECT count(*) FROM installations),
                       (SELECT count(*) FROM interventions), (SELECT count(*) FROM interventions WHERE embedding IS NOT NULL)
                """
            ).fetchone()
            by_kind = cur.execute("SELECT kind, count(*) FROM interventions GROUP BY kind ORDER BY kind").fetchall()
            size = cur.execute("SELECT pg_size_pretty(pg_total_relation_size('interventions'))").fetchone()[0]
    # Tutto in una transazione: il COMMIT avviene all'uscita dal blocco `with`. Se qualcosa
    # fallisce a metà, nel database non resta un import parziale.

    print(f"clienti {counts[0]}, impianti {counts[1]}, interventi {counts[2]} (con embedding: {counts[3]})")
    print("per tipo: " + ", ".join(f"{k} {n}" for k, n in by_kind))
    print(f"dimensione della tabella interventions: {size}")


if __name__ == "__main__":
    main()
