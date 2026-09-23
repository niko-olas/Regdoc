# RegDoc

Assistente Q&A (RAG) su documenti normativi ESMA/CONSOB. È un **progetto di studio**: lo costruisco per prepararmi all'esame Microsoft AI-200, quindi conta quanto il *come* è costruito, non solo che funzioni.

Skill d'esame, fasi F1–F5 e avanzamento: [docs/ai200-skills.md](docs/ai200-skills.md). Non duplicare qui quel contenuto — leggilo quando serve capire a che fase appartiene un componente o quale skill copre.

## Architettura

**Ingestion (F1)**
Blob Storage → Event Grid → Azure Function → Service Bus (topic con subscription `indexer` e `audit`)

**Audit (F1)**
Subscription `audit` → consumer minimale che registra ogni messaggio nei log con OpenTelemetry. Nessuna logica di dominio: serve a rendere visibile il fan-out del topic.

**Indicizzazione (F2–F3)**
Subscription `indexer` → worker Python su Container Apps (scaling KEDA sulla coda) → embedding con Foundry → **scrittura su entrambi gli store**, Cosmos DB for NoSQL (F2) e PostgreSQL con pgvector (F3), dietro la stessa interfaccia.
Si scrive sempre su entrambi per due motivi: il change feed di Cosmos deve scattare a ogni indicizzazione, e i due store restano confrontabili sugli stessi dati.

**Reazione alle modifiche (F2–F3)**
Change feed di Cosmos → invalidazione della cache su Azure Managed Redis → evento custom pubblicato su Event Grid.

**Query (F4)**
API in container: la stessa immagine va su App Service e su AKS. Il **feature flag in App Configuration decide da quale store legge** l'API (Cosmos o pgvector), cambiabile a runtime senza reindicizzare. La scrittura non dipende dal flag.

**Trasversali (F5)**
Key Vault (secret), App Configuration (config e feature flag), OpenTelemetry → Application Insights.

## Sviluppo

- Python 3.12, un `requirements.txt` per componente.
- Test con pytest, dalla radice: `pytest tests/`.
- Le immagini si buildano con **contesto `src/`**, non con la cartella del componente, così il Dockerfile può copiare `shared/`. Il Dockerfile resta accanto al suo componente e si indica con `-f`:

```bash
az acr build --registry <acr> --image regdoc-worker:<tag> -f src/worker/Dockerfile src/
```

## Regole

### Codice
- Python, SDK Azure ufficiali (`azure-*`). Niente wrapper di terze parti se l'SDK ufficiale copre il caso.
- Autenticazione sempre con `DefaultAzureCredential` / managed identity. Mai connection string, chiavi o SAS nel codice.
- Nessun segreto nei file committati: i secret stanno in Key Vault, endpoint e nomi risorsa in App Configuration o in variabili d'ambiente. I file con valori locali (`.env`, `local.settings.json`) restano fuori dal repo — verifica che siano in `.gitignore` prima di crearli.

### Risorse Azure
- **Non eseguire comandi che creano o modificano risorse**: `az ... create/update/delete`, `az acr build`, `kubectl apply/delete`, `func ... publish`, `docker push`, deploy in generale. Proponili nella risposta o come script sotto `infra/`: li eseguo io, perché la configurazione fa parte dello studio.
- I comandi di sola lettura (`az ... show/list`, `kubectl get/describe/logs`, `docker build` locale) vanno bene.

### Commenti didattici
Quando il codice tocca un argomento d'esame, aggiungi un commento breve che spiega **la scelta**, non cosa fa la riga: consistency level, indexing policy, partition key, gestione della dead-letter, regole di scaling KEDA, TTL e chiavi della cache, tipo di indice pgvector. Un commento per decisione, non un tutorial.

### Decision log
Dopo ogni decisione architetturale, proponi in fondo alla risposta una voce per `docs/decision-log.md`: data, decisione, alternative scartate, motivo, fase e skill AI-200 toccata. Scrivila nel file solo se te lo chiedo.

### Troubleshooting log
Dopo ogni problema risolto, proponi allo stesso modo una voce per `docs/troubleshooting-log.md`: data, sintomo, diagnosi (comandi o query KQL usati), causa, soluzione, skill AI-200 collegata. Scrivila nel file solo se te lo chiedo.

## Struttura delle cartelle (proposta)

Le cartelle nascono fase per fase, non tutte insieme.

```
src/
  shared/            # F5 — libreria comune importata da tutti i componenti
    config.py        #      App Configuration, feature flag dello store di lettura
    credentials.py   #      DefaultAzureCredential condivisa
    telemetry.py     #      setup OpenTelemetry → Application Insights
    models.py        #      documento, chunk, record di embedding
  ingestion/         # F1 — Azure Function: Event Grid trigger → Service Bus
    function_app.py
    host.json
  audit/             # F1 — consumer della subscription audit, solo logging
    main.py
    Dockerfile
  worker/            # F2 — consumer della subscription indexer su Container Apps
    main.py          #      loop di ricezione, settlement, dead-letter
    chunking.py
    embeddings.py    #      client Foundry
    stores/          #      scrittura su entrambi, dietro la stessa interfaccia
      base.py        #      interfaccia VectorStore
      cosmos.py      # F2
      postgres.py    # F3 — pgvector
    Dockerfile
  changefeed/        # F2–F3 — change feed processor → Redis + Event Grid
    main.py
    Dockerfile
  api/               # F4 — API di query, una immagine per App Service e AKS
    main.py
    retrieval.py     #      store di lettura scelto dal feature flag
    cache.py         #      Azure Managed Redis
    Dockerfile
infra/
  scripts/           # comandi az proposti (li eseguo io)
  containerapps/     # F2 — config environment, scale rule KEDA
  k8s/               # F4 — manifest AKS
  appservice/        # F4
docs/
  ai200-skills.md
  decision-log.md
  troubleshooting-log.md
  kql/               # F5 — query KQL salvate
tests/
samples/             # documenti ESMA/CONSOB di prova
```

Ogni componente containerizzato ha il suo `Dockerfile` e il suo `requirements.txt` accanto al codice; `src/shared/` entra nell'immagine grazie al contesto di build.
