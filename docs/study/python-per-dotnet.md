# Python per chi viene da .NET

Glossario che cresce con RegDoc: ogni volta che il codice introduce un costrutto Python nuovo, qui c'è l'equivalente C#/.NET e il file dove lo trovi. In fondo, esercizi da fare sul codice reale.

---

## Modulo 1 — L'API minimale (`src/api/`)

### Progetto e dipendenze

| Python | .NET | Dove |
|---|---|---|
| `requirements.txt` | `<PackageReference>` nel `.csproj` | [src/api/requirements.txt](../../src/api/requirements.txt) |
| `fastapi==0.115.14` | `Version="0.115.14"`: versione esatta | requirements.txt |
| `python -m pip install -r requirements.txt` | `dotnet restore` | Dockerfile |
| venv (`.venv/`) | Nessun equivalente diretto: è una copia isolata dell'interprete con i *suoi* pacchetti. In .NET i pacchetti sono già per-progetto, in Python senza venv finirebbero globali | radice del repo |
| `-r altro-file.txt` dentro un requirements | Un `ProjectReference` "povero": include le dipendenze di un altro file | [requirements-dev.txt](../../requirements-dev.txt) |

Regola pratica: **attiva sempre il venv** (`.\.venv\Scripts\Activate.ps1`) prima di `pip` o `pytest`, altrimenti installi nella 3.14 di sistema.

### Ambiente da zero

1. **venv** — `py -3.12 -m venv .venv`. Per la [doc di venv](https://docs.python.org/3/library/venv.html): si chiama `.venv` per convenzione, non va in git, è *usa e getta* (non si sposta né si copia: si cancella e si ricrea) e dev'essere sempre ricreabile da un file di requirements.
2. **Un `requirements.txt` per componente, versioni esatte (`==`)** — è il formato che leggono i tool di Azure (remote build di Functions, build di App Service) e quello degli esempi Microsoft. I repo Python moderni usano spesso `pyproject.toml` + un lock (`uv.lock`, `poetry.lock`): qui non serve, perché la riproducibilità in produzione la garantisce il *digest* dell'immagine in ACR, non la ricostruzione.
3. **Runtime separato dagli strumenti di sviluppo** — l'immagine installa solo `src/api/requirements.txt`; pytest e httpx stanno in `requirements-dev.txt`, che include il primo con `-r`.
4. **`python -m pip`** invece di `pip` — usa sicuramente il pip del Python attivo.
5. **pytest** — [good practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html): test in `tests/` fuori dal codice, `--import-mode=importlib` per i progetti nuovi, `strict = true`. Il codice in `src/` si rende importabile con `pythonpath = src`.
6. **File generati da non committare** (già nel `.gitignore`): `.venv/`, `.pytest_cache/` (la crea pytest: ricorda i test falliti per `pytest --lf`), `__pycache__/` (bytecode compilato, simile a `obj/`), `.env` (variabili d'ambiente locali, letto dall'estensione Python di VS Code o da `python-dotenv`; in Azure il suo ruolo lo fanno le app settings).

**Aggiungere una dipendenza**: la scrivi con versione esatta nel `requirements.txt` del componente, poi `python -m pip install -r requirements-dev.txt`.

### Moduli, package e import

| Python | .NET |
|---|---|
| Un file `.py` = un **modulo** | Una classe statica / un file |
| Una cartella con `__init__.py` = un **package** | Un namespace |
| `from fastapi import FastAPI` | `using Microsoft.AspNetCore.Builder;` — ma importa un nome preciso, non tutto il namespace |
| `import os` poi `os.getenv(...)` | Usare il nome qualificato `System.Environment.GetEnvironmentVariable(...)` |
| `api.main:app` (in `uvicorn`) | "nel modulo `api/main.py`, l'oggetto chiamato `app`" |

[pytest.ini](../../pytest.ini) ha `pythonpath = src`: dice ai test di cercare i package dentro `src/`, così `from api.main import app` funziona. È il ruolo che in .NET ha il `ProjectReference` dal progetto di test al progetto web.

### La sintassi in [src/api/main.py](../../src/api/main.py)

| Python | C# | Nota |
|---|---|---|
| Indentazione | `{ }` | In Python l'indentazione **è** la sintassi: niente graffe, niente `;` |
| `def health() -> dict:` | `Dictionary<string, object> Health()` | `-> dict` è un *type hint*: Python **non lo verifica** a runtime. È documentazione + aiuto per l'editor (e per strumenti come `mypy`) |
| `{"status": "ok"}` | `new { status = "ok" }` | Un `dict` letterale; FastAPI lo serializza in JSON come fa ASP.NET con un oggetto anonimo |
| `os.getenv("APP_ENV", "local")` | `Environment.GetEnvironmentVariable("APP_ENV") ?? "local"` | Il secondo argomento è il default |
| `bool(os.getenv("APP_SECRET"))` | `!string.IsNullOrEmpty(...)` | *Truthiness*: `None`, `""`, `0`, `[]`, `{}` valgono `False` |
| `snake_case` per funzioni e variabili | `PascalCase` / `camelCase` | Convenzione PEP 8; le classi restano `PascalCase` (`FastAPI`, `TestClient`) |
| `# commento` | `// commento` | |

### Il framework web

| Python | ASP.NET Core |
|---|---|
| `app = FastAPI(title="RegDoc API")` | `var app = WebApplication.CreateBuilder(args).Build();` |
| `@app.get("/health")` sopra una funzione | `app.MapGet("/health", () => ...)` |
| `uvicorn` | Kestrel: il server HTTP che ospita l'app |
| `--host 0.0.0.0 --port 8000` | `ASPNETCORE_URLS=http://+:8000` |

Il **decorator** (`@qualcosa` sopra una `def`) è una funzione che riceve la tua funzione e la registra/avvolge. Qui `@app.get("/health")` significa "registra `health` come handler di GET /health". Somiglia agli attributi C# (`[HttpGet("/health")]`), ma è codice che *esegue* al momento della definizione, non solo metadati.

A differenza di Python "puro", **FastAPI legge davvero i type hint** a runtime: quando un endpoint avrà parametri (`def search(q: str, top: int = 5)`), FastAPI li userà per validare la query string e rispondere 422 se `top` non è un intero. Vale per FastAPI, non per Python in generale.

### I test in [tests/test_api.py](../../tests/test_api.py)

| pytest | xUnit |
|---|---|
| Funzione che inizia con `test_` | Metodo con `[Fact]` — pytest le scopre per nome, senza attributi |
| `assert a == b` | `Assert.Equal(b, a)` — pytest riscrive l'`assert` per mostrare entrambi i valori se fallisce |
| `TestClient(app)` | `WebApplicationFactory<Program>().CreateClient()` |
| Parametro `monkeypatch` | Una **fixture**: pytest la inietta guardando il *nome* del parametro (DI per nome, non per tipo). `monkeypatch.setenv` imposta una variabile d'ambiente e la ripristina a fine test |
| `pytest` dalla radice | `dotnet test` |

---

## Esercizi

Falli sul codice vero, con il venv attivo, e verifica con `pytest`. Se vuoi, poi li rivediamo insieme.

1. **Nuovo endpoint.** Aggiungi `GET /version` che restituisce solo `{"version": ...}` letto da `APP_VERSION`. Scrivi il test corrispondente.
2. **Truthiness.** Cosa restituisce `/info` in `secret_configured` se `APP_SECRET` è impostata a stringa vuota? Scrivi un test che lo dimostri (suggerimento: `monkeypatch.setenv("APP_SECRET", "")`).
3. **Parametri e type hint.** Aggiungi `GET /echo?text=...&times=2` con firma `def echo(text: str, times: int = 1)` che restituisce il testo ripetuto. Prova `times=abc` dal browser o da curl: che codice HTTP ottieni, e perché?
4. **Rimuovere una variabile.** Nel test di `/info`, usa `monkeypatch.delenv("APP_ENV", raising=False)` e verifica che `environment` valga `"local"`. Cosa fa `raising=False`?
