"""Esperimento: ricerca vettoriale senza indice, con IVFFlat e con HNSW su ~20.000 vettori.

Con i 184 interventi reali un indice vettoriale non serve (vedi EXPLAIN del passo 4), quindi
il confronto si fa su una tabella separata, `bench_vectors`, da eliminare a fine esperimento.
I vettori sono copie "rumorose" degli embedding veri: stessa dimensione e distribuzione realistica,
generati direttamente nel database (nessuna chiamata a Foundry).

Uso, dalla radice con il venv di sviluppo e PGHOST/PGUSER impostati:
    .venv\\Scripts\\python.exe scripts\\tools\\vector_bench.py setup     # crea e popola bench_vectors
    .venv\\Scripts\\python.exe scripts\\tools\\vector_bench.py run       # misura i tre casi
    .venv\\Scripts\\python.exe scripts\\tools\\vector_bench.py cleanup   # elimina bench_vectors
"""
import math
import pathlib
import random
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from pgvector import Vector  # noqa: E402

from fielddata.db import connect  # noqa: E402

COPIES = 110          # 184 interventi x 110 = 20.240 vettori
QUERIES = 20
K = 10
SEARCH = "SELECT id, embedding <=> %(q)s FROM bench_vectors ORDER BY embedding <=> %(q)s LIMIT %(k)s"

SETUP = """
DROP TABLE IF EXISTS bench_vectors;
CREATE TABLE bench_vectors (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    embedding vector(1536) NOT NULL
);
-- Il riferimento a g.n e iv.id nella LATERAL obbliga a ricalcolare il rumore per ogni riga.
INSERT INTO bench_vectors (embedding)
SELECT l2_normalize(iv.embedding + noise.v)
FROM interventions iv
CROSS JOIN generate_series(1, %(copies)s) AS g(n)
CROSS JOIN LATERAL (
    SELECT array_agg((random() - 0.5) * 0.05)::vector AS v
    FROM generate_series(1, 1536) WHERE g.n > 0 AND iv.id > 0
) AS noise;
ANALYZE bench_vectors;
"""

# (nome, DDL dell'indice, parametro di ricerca, valori da provare)
INDEXES = [
    ("nessuno", None, None, [None]),
    # IVFFlat divide i vettori in `lists` gruppi attorno a centroidi calcolati SUI DATI PRESENTI
    # al momento della creazione: va creato dopo il caricamento, e se i dati cambiano molto va
    # ricostruito. Regola pgvector: lists = righe / 1000 fino a 1M righe. A query time `probes`
    # dice quanti gruppi visitare: più probes, più recall e più lentezza.
    ("ivfflat", "CREATE INDEX ix_bench_ivfflat ON bench_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 20)",
     "ivfflat.probes", [1, 4, 10]),
    # HNSW costruisce un grafo a più livelli: nessun training (si può creare anche su tabella vuota
    # e regge bene inserimenti continui), costruzione più lenta e indice più grande, ma un miglior
    # rapporto velocità/recall. `m` e `ef_construction` (qui i default) pesano sulla costruzione,
    # `hnsw.ef_search` (>= k) sulla ricerca.
    ("hnsw", "CREATE INDEX ix_bench_hnsw ON bench_vectors USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)",
     "hnsw.ef_search", [10, 40, 100]),
]


def setup(conn) -> None:
    started = time.perf_counter()
    conn.execute(SETUP.replace("%(copies)s", str(COPIES)))  # più istruzioni insieme: niente parametri
    rows, size = conn.execute(
        "SELECT count(*), pg_size_pretty(pg_total_relation_size('bench_vectors')) FROM bench_vectors").fetchone()
    print(f"bench_vectors: {rows} vettori, {size}, creati in {time.perf_counter() - started:.0f} s")


def query_vectors(conn) -> list[Vector]:
    """Domande di prova: embedding veri con un rumore diverso da quello delle righe in tabella."""
    rng = random.Random(7)
    vectors = []
    for (e,) in conn.execute("SELECT embedding FROM interventions ORDER BY id LIMIT %s", (QUERIES,)).fetchall():
        v = [x + rng.uniform(-0.025, 0.025) for x in e.to_list()]
        norm = math.sqrt(sum(x * x for x in v))
        vectors.append(Vector([x / norm for x in v]))
    return vectors


def search(conn, q) -> tuple[list[int], float, float, bool]:
    rows = conn.execute(SEARCH, {"q": q, "k": K}).fetchall()
    # Tempo misurato dal server (EXPLAIN ANALYZE), non dal client: esclude la latenza di rete.
    plan = conn.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + SEARCH, {"q": q, "k": K}).fetchone()[0][0]
    return [r[0] for r in rows], statistics.mean(r[1] for r in rows), plan["Execution Time"], "Index Scan" in str(plan)


def run(conn) -> None:
    queries = query_vectors(conn)
    conn.execute("SET maintenance_work_mem = '256MB'")  # il grafo HNSW deve stare in memoria durante la build
    truth: list[tuple[list[int], float]] = []
    print(f"{'indice':8} {'parametro':18} {'build s':>8} {'dim':>8} {'ms medi':>8} {'recall@10':>9} {'+dist':>7}  usa indice")
    for name, ddl, param, values in INDEXES:
        conn.execute("DROP INDEX IF EXISTS ix_bench_ivfflat, ix_bench_hnsw")
        build, size = "-", "-"
        if ddl:
            started = time.perf_counter()
            conn.execute(ddl)
            build = f"{time.perf_counter() - started:.1f}"
            size = conn.execute(f"SELECT pg_size_pretty(pg_relation_size('ix_bench_{name}'))").fetchone()[0]
        for value in values:
            if param:
                conn.execute(f"SET {param} = {int(value)}")
            results = [search(conn, q) for q in queries]
            if name == "nessuno":
                truth = [(ids, dist) for ids, dist, _, _ in results]  # senza indice la ricerca è esatta: è il riferimento
            recall = statistics.mean(len(set(r[0]) & set(t[0])) / K for r, t in zip(results, truth))
            # Recall conta gli id. Con molti vettori quasi equidistanti (i dati di esempio ripetono le
            # stesse frasi) l'indice può tornare vicini "altrettanto buoni" ma diversi: +dist misura di
            # quanto sono più lontani, in media, rispetto ai veri più vicini. Vicino a 0 = qualità uguale.
            extra = statistics.mean(r[1] - t[1] for r, t in zip(results, truth))
            ms = statistics.mean(r[2] for r in results)
            used = all(r[3] for r in results)
            label = f"{param}={value}" if param else ""
            print(f"{name:8} {label:18} {build:>8} {size:>8} {ms:8.2f} {recall:9.2f} {extra:7.4f}  {'sì' if used else 'no'}")
    conn.execute("DROP INDEX IF EXISTS ix_bench_ivfflat, ix_bench_hnsw")


def cleanup(conn) -> None:
    conn.execute("DROP TABLE IF EXISTS bench_vectors")
    print("bench_vectors eliminata")


def main() -> None:
    commands = {"setup": setup, "run": run, "cleanup": cleanup}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(__doc__)
    with connect() as conn:
        conn.autocommit = True  # ogni DDL è definitiva subito, come in psql
        commands[sys.argv[1]](conn)


if __name__ == "__main__":
    main()
