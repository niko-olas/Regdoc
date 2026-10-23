"""Quanto costa aprire una connessione? Confronto tra connessione nuova per ogni query e pool.

Sola lettura: esegue solo SELECT 1.

Uso, dalla radice con il venv di sviluppo e PGHOST/PGUSER impostati:
    .venv\\Scripts\\python.exe scripts\\tools\\connection_bench.py
"""
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from azure.identity import DefaultAzureCredential  # noqa: E402

from fielddata.db import connect, create_pool  # noqa: E402

N = 10


def timed(fn) -> float:
    started = time.perf_counter()
    fn()
    return (time.perf_counter() - started) * 1000


def main() -> None:
    credential = DefaultAzureCredential()
    credential.get_token("https://ossrdbms-aad.database.windows.net/.default")  # token in cache: misuriamo solo il database

    def new_connection_each_time() -> None:
        with connect(credential, with_vector=False) as conn:
            conn.execute("SELECT 1").fetchone()

    no_pool = [timed(new_connection_each_time) for _ in range(N)]

    with create_pool(credential, min_size=1, max_size=2, with_vector=False) as pool:
        pool.wait()  # la prima connessione si apre qui, fuori dalla misura

        def from_pool() -> None:
            with pool.connection() as conn:
                conn.execute("SELECT 1").fetchone()

        pooled = [timed(from_pool) for _ in range(N)]
        stats = pool.get_stats()

    print(f"{'modo':28} {'ms medi':>8} {'min':>7} {'max':>7}")
    for label, values in [("connessione nuova ogni volta", no_pool), ("connessione dal pool", pooled)]:
        print(f"{label:28} {statistics.mean(values):8.1f} {min(values):7.1f} {max(values):7.1f}")
    print(f"connessioni aperte dal pool: {stats.get('connections_num', 0)}, richieste servite: {stats.get('requests_num', 0)}")


if __name__ == "__main__":
    main()
