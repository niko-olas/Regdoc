"""Crea il ruolo PostgreSQL di una managed identity e le dà solo i permessi del suo profilo.

Profili (minimo privilegio):
    api      lettura di tutte le tabelle (impianti, interventi, catalogo): l'API non scrive mai
    catalog  lettura e scrittura del solo catalogo `documents`: la Function non tocca i dati dal campo

Va eseguito da un amministratore Entra del server (tu). Il nome del ruolo deve essere quello della
managed identity: per una system-assigned è il nome della risorsa (web app, function app). L'app poi
si collega con PGUSER=<quel nome> e un token della sua identità.

Uso, dalla radice con il venv di sviluppo e PGHOST/PGUSER (il tuo UPN) impostati:
    .venv\\Scripts\\python.exe scripts\\db\\grant_app_role.py <nome-identità> api|catalog
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from psycopg import sql  # noqa: E402

from fielddata.db import connect  # noqa: E402

PROFILES = {
    # Anche le tabelle create in futuro (ALTER DEFAULT PRIVILEGES): l'API le legge senza rieseguire lo script.
    "api": [
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO {role}",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {role}",
    ],
    # INSERT/UPDATE per gli upsert (ON CONFLICT DO UPDATE richiede entrambi), SELECT per il confronto.
    "catalog": [
        "GRANT SELECT, INSERT, UPDATE ON documents TO {role}",
    ],
}


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[2] not in PROFILES:
        sys.exit(__doc__)
    principal, profile = sys.argv[1], sys.argv[2]

    # I ruoli Entra si creano dal database `postgres` con la funzione di Azure pgaadauth_create_principal.
    os.environ["PGDATABASE"] = "postgres"
    with connect(with_vector=False) as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (principal,)).fetchone()
        if not exists:
            # (nome, is_admin=false, is_mfa=false): un ruolo normale, non amministratore.
            conn.execute("SELECT * FROM pgaadauth_create_principal(%s, false, false)", (principal,))
        print(f"ruolo {principal}: {'già esistente' if exists else 'creato'}")

    os.environ["PGDATABASE"] = "regdoc"
    role = sql.Identifier(principal)
    with connect(with_vector=False) as conn:
        conn.execute(sql.SQL("GRANT CONNECT ON DATABASE regdoc TO {}").format(role))
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        for statement in PROFILES[profile]:
            conn.execute(sql.SQL(statement).format(role=role))
        grants = conn.execute(
            """
            SELECT table_name, string_agg(privilege_type, ', ' ORDER BY privilege_type)
            FROM information_schema.role_table_grants WHERE grantee = %s
            GROUP BY table_name ORDER BY table_name
            """,
            (principal,),
        ).fetchall()
    print(f"profilo {profile}: " + "; ".join(f"{t} ({p})" for t, p in grants))


if __name__ == "__main__":
    main()
