# Changelog

Modifiche e funzionalità di RegDoc, dalla più recente alla più vecchia. Formato ispirato a
[Keep a Changelog](https://keepachangelog.com/it/1.1.0/): una voce per data e fase (F1–F5, vedi
[docs/study/ai200-skills.md](docs/study/ai200-skills.md)), con i tag delle immagini in ACR quando ci sono.

Qui c'è **cosa** è cambiato; il **perché** è nel [decision log](docs/decision-log.md), i problemi incontrati nel
[troubleshooting log](docs/troubleshooting-log.md).

---

## [Non rilasciato] — 2026-10-24/25 · F2–F4

Immagini: non ancora ricostruite con un nuovo tag (in `up.ps1` restano `regdoc-api:2.2.0` e `regdoc-worker:0.2.0`).

### Aggiunto
- **Manifest per documento**: il worker lo scrive per ultimo, nella stessa partizione logica dei chunk, con numero
  di chunk, pagine ed etag del blob. Il documento risulta indicizzato solo quando è completo.
- **Scelta per prodotto**: `GET /products` (dominio, marca, modello, manuali indicizzati) e
  `GET /products/{domain}/{manufacturer}/{model}/documents`; nell'interfaccia il tecnico sceglie marca e modello.
- `CHANGELOG.md`.

### Modificato
- `on_chunks_changed` reagisce solo ai manifest: un evento `RegDoc.Document.Indexed` per documento completo, con
  `chunk_count` e `pages` al posto di `chunks_changed`.
- La ricerca dei manuali filtra `kind = 'chunk'`; `sync_catalog.py` legge i manifest invece di tutti i chunk.
- Il prompt non contiene nome e città del cliente; la risposta di `/ask` non contiene i dati dell'impianto
  (solo la matricola in `scope`); `RESPONSE_FORMAT` della cache portato a 3.
- `src/ingestion` diventa `src/functions`, con **due Function App** e una cartella per funzione registrata come
  blueprint: `ingest/` (`blob_created/`) e `catalog/` (`document_uploaded/`, `changefeed/`, `catalog_store.py`).
- Infrastruttura: le due app hanno identità, piano Flex Consumption e storage dell'host separati (modulo
  `infra/modules/function-app.bicep`). `ingest` ha solo lettura dei blob e invio sul topic; PostgreSQL, Cosmos,
  Event Grid e Redis passano all'identità di `catalog`, limitata a 2 istanze e 4 messaggi contemporanei per istanza
  per non saturare le connessioni di PostgreSQL. `up.ps1` pubblica le due app; in `env.example.ps1`
  `FUNCAPP_INGEST` e `FUNCAPP_CATALOG` sostituiscono `FUNCAPP`.

### Corretto
- Catalogo ed evento segnavano un documento come indicizzato al primo lotto del change feed, quando mancavano
  ancora dei chunk (un manuale da 106 chunk arrivava in 2 lotti e produceva 2 eventi).
- Un hit esatto della cache restituiva i dati del cliente salvati in Redis, anche se nel frattempo erano cambiati.
- `requirements-dev.txt` puntava ancora a `src/ingestion/requirements.txt` dopo la rinomina della cartella.

### Rimosso
- `GET /installations` e `GET /installations/{serial}/documents`: l'elenco dei clienti non è più esposto.
- `docs/study/python-per-dotnet.md`.

## 2026-10-23 · F3–F5 — Dati dal campo, catalogo, API RAG, cache, infrastruttura

Immagini: `regdoc-api:2.2.0`, `regdoc-worker:0.2.0`.

### Aggiunto
- **Dati dal campo** su PostgreSQL + pgvector: clienti → impianti → interventi con embedding e indice HNSW; import
  dei dati di esempio; ricerca di guasti simili con filtri relazionali; connection pooling con token Entra ID.
- **Catalogo dei documenti**: subscription `catalog` → `on_document_uploaded`; stato derivato da `uploaded_at` e
  `indexed_at`; riallineamento con storage e Cosmos (`scripts/db/sync_catalog.py`).
- **API RAG** `/ask`: manuali (Cosmos) e interventi simili → risposta con citazioni, solo le fonti citate; soglia
  sugli interventi in App Configuration; interfaccia web.
- **Cache** su Azure Managed Redis, esatta e semantica, invalidata per versione dal change feed.
- **Feature flag** e configurazione dinamica in App Configuration; telemetria OpenTelemetry verso Application Insights.
- **Infrastruttura**: `infra/main.bicep` con tutte le risorse e i ruoli; `up.ps1`, `down.ps1`, `smoke-test.ps1`.
- README, decision log, troubleshooting log, recap PostgreSQL.

### Modificato
- Script divisi in `scripts/deploy`, `scripts/db`, `scripts/tools`; materiale d'esame in `docs/study`; database e
  container Cosmos in `infra/modules/cosmos-db.bicep`.

### Rimosso
- Consumer `audit`: il secondo consumatore del topic è ora la subscription `catalog`, che ha un ruolo reale nel prodotto.

## 2026-10-23 · F2 — Indicizzazione dei manuali e change feed

### Aggiunto
- **Worker** su Container Apps (scaling KEDA): subscription `indexer` → PDF (pypdf) → chunk con sovrapposizione →
  embedding con Foundry → upsert idempotente su Cosmos DB; dead-letter per gli errori permanenti, abandon con attesa
  crescente per i transitori, `AutoLockRenewer` per le elaborazioni lunghe.
- **Cosmos DB**: container `chunks` con partition key gerarchica `domain`/`document_id`, indexing policy che esclude
  embedding e testo, vector index `quantizedFlat` (float32, cosine, 1536).
- **Change feed**: `on_chunks_changed` (trigger Cosmos DB, lease container, connessione a identità, retry policy)
  pubblica l'evento custom `RegDoc.Document.Indexed` su Event Grid.
- Ricerca vettoriale da riga di comando con `VectorDistance` (`search_cosmos.py`); recap Cosmos DB.

## 2026-10-21 · F1 — Ingestion

### Aggiunto
- **`on_blob_created`**: Function Python v2 con trigger Event Grid; campi fissi dal percorso del blob, attributi dai
  metadati; messaggio sul topic `documents` con MessageId = id dell'evento (duplicate detection) e proprietà
  applicative per i filtri.
- Consumer `audit` della subscription omonima: PeekLock, dead-letter dei messaggi non validi, abandon per gli errori
  imprevisti.
- Script di prova: evento simulato, peek di una subscription, invio di messaggi di test.
- Recap Azure Functions ed Eventi e messaggi.

## 2026-10-19 · F4 (anticipata) — API scheletro e hosting container

Immagini: `regdoc-api:1.0.0`, `regdoc-api:1.1.0`.

### Aggiunto
- API FastAPI con `/health`, `/info`, `/version`; `APP_VERSION` impostata a build time con lo stesso valore del tag.
- Immagine in Azure Container Registry (admin user disabilitato), deploy su App Service con pull tramite managed
  identity.
- Ambiente di sviluppo unico (Python 3.12, pytest); recap Hosting container.
