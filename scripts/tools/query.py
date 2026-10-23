"""Esegue una query SQL su `regdoc` e stampa il risultato in tabella (al posto di psql).

Uso, dalla radice con il venv di sviluppo e PGHOST/PGUSER impostati:
    .venv\\Scripts\\python.exe scripts\\tools\\query.py "SELECT model, count(*) FROM installations GROUP BY model"
    .venv\\Scripts\\python.exe scripts\\tools\\query.py -f percorso\\query.sql

Le modifiche NON vengono salvate: la transazione viene annullata alla fine (strumento di sola lettura).
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fielddata.db import connect  # noqa: E402

MAX_WIDTH = 80


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "-f":
        sql = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
    elif len(sys.argv) == 2:
        sql = sys.argv[1]
    else:
        sys.exit(__doc__)

    with connect() as conn:
        cur = conn.execute(sql)
        if cur.description is None:
            print("(nessun risultato)")
            return
        headers = [d.name for d in cur.description]
        rows = [[str(v)[:MAX_WIDTH] for v in row] for row in cur.fetchall()]
        conn.rollback()

    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(v.ljust(w) for v, w in zip(r, widths)))
    print(f"({len(rows)} righe)")


if __name__ == "__main__":
    main()
