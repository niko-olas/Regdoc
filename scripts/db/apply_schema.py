"""Applica infra/postgres/schema.sql al database `regdoc` e mostra il risultato.

Uso, dalla radice del progetto con il venv di sviluppo:
    $env:PGHOST = "<server>.postgres.database.azure.com"
    $env:PGUSER = "<il tuo UPN, l'amministratore Entra del server>"
    .venv\\Scripts\\python.exe scripts\\db\\apply_schema.py
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fielddata.db import connect  # noqa: E402


def main() -> None:
    sql = (ROOT / "infra" / "postgres" / "schema.sql").read_text(encoding="utf-8")

    # with_vector=False: alla prima esecuzione l'estensione vector non esiste ancora,
    # la crea proprio lo schema.
    with connect(with_vector=False) as conn:
        conn.execute(sql)
        version = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
        tables = conn.execute(
            """
            SELECT c.relname, pg_size_pretty(pg_total_relation_size(c.oid))
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY c.relname
            """
        ).fetchall()
        indexes = conn.execute(
            "SELECT tablename, indexname FROM pg_indexes WHERE schemaname = 'public' ORDER BY tablename, indexname"
        ).fetchall()
    # L'uscita dal blocco `with` esegue il COMMIT: fino a quel momento lo schema era in una transazione.

    print(f"pgvector: {version[0] if version else 'NON installata'}")
    print("\nTabelle:")
    for name, size in tables:
        print(f"  {name:<15} {size}")
    print("\nIndici:")
    for table, index in indexes:
        print(f"  {table:<15} {index}")


if __name__ == "__main__":
    main()
