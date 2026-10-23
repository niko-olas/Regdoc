# RegDoc

Assistente Q&A (RAG) per tecnici manutentori: i tecnici caricano documentazione tecnica (manuali di installazione, uso e manutenzione, schede tecniche) e fanno domande tecniche sugli impianti. Le risposte combinano i **manuali** con l'**esperienza dal campo** (interventi già fatti su impianti simili).

Due obiettivi, con lo stesso peso:
- **Studio**: preparazione all'esame Microsoft AI-200, quindi conta quanto il *come* è costruito, non solo che funzioni.
- **Prodotto realistico**: l'app finale deve poter servire in un'azienda vera. Ogni componente ha un ruolo funzionale reale; niente parti che esistono solo per l'esercizio. Se una skill d'esame non trova un uso reale, si studia con un esperimento separato, non forzandola nell'architettura.

Skill d'esame, fasi F1–F5 e avanzamento: [docs/study/ai200-skills.md](docs/study/ai200-skills.md). Non duplicare qui quel contenuto — leggilo quando serve capire a che fase appartiene un componente o quale skill copre.

## Dominio generico

Il progetto non è legato a un tipo di impianto: il primo **dominio** è `stufe-pellet`, domani potrebbero arrivare `caldaie` o altro. Un nuovo dominio si aggiunge con la configurazione, non con il codice.

- **Campi fissi** (il codice lavora solo su questi): `domain`, `manufacturer`, `model`, `doc_type`, più `page` su ogni chunk perché le risposte citino documento e pagina.
- **Attributi liberi** per dominio: dizionario `attributes` (es. `potenza_kw` per le stufe), che il codice non interpreta.
- **Profilo di dominio** in App Configuration, una label per dominio: `doc_type` ammessi, attributi attesi, prompt di sistema.
- **Dati dal campo** (relazionali, su PostgreSQL): clienti, impianti installati (con `domain`, `manufacturer`, `model` come nei manuali) e interventi con note libere. Il collegamento tra un impianto e i suoi manuali passa per i campi fissi, non per chiavi tra database diversi.

## Architettura

**Ingestion (F1)**
Blob Storage → Event Grid → Azure Function → Service Bus (topic `documents` con subscription `indexer` e `catalog`)
I tecnici caricano i documenti **direttamente in Blob** (nessun endpoint di upload per ora). I campi fissi vengono dal percorso del blob, gli attributi liberi dai metadati del blob (`x-ms-meta-*`):
`documents/{domain}/{manufacturer}/{model}/{doc_type}/{file}.pdf` — es. `documents/stufe-pellet/edilkamin/blade-h/uso-manutenzione/manuale.pdf`.
Estrazione del testo dai PDF con `pypdf`; Document Intelligence eventualmente più avanti.

**Catalogo dei documenti (F1–F3)**
Subscription `catalog` → funzione `on_document_uploaded` (trigger Service Bus) → tabella `documents` su PostgreSQL. Il change feed segna il documento come indicizzato. L'API mostra al tecnico quali manuali esistono per il suo impianto e se sono già interrogabili; chi gestisce i documenti vede quelli rimasti bloccati.

**Indicizzazione dei manuali (F2)**
Subscription `indexer` → worker Python su Container Apps (scaling KEDA sulla coda) → chunk + embedding con Foundry → **Cosmos DB for NoSQL** (container `chunks`, partition key gerarchica `domain`/`document_id`, vector index). Il worker scrive dietro l'interfaccia `VectorStore`.

**Dati dal campo (F3)**
**PostgreSQL Flexible Server con pgvector**: schema relazionale clienti → impianti → interventi; embedding delle note d'intervento per trovare guasti simili già risolti, con filtri relazionali (stesso modello, stesso dominio). In un'azienda questi dati arriverebbero dal gestionale (CRM/ERP); nel progetto li carica uno script di import con dati di esempio anonimi.

**Reazione alle modifiche (F2–F3)**
Change feed di `chunks` → funzione `on_chunks_changed` (trigger Cosmos DB) → evento custom `RegDoc.Document.Indexed` su Event Grid, documento indicizzato nel catalogo, invalidazione delle risposte in cache su Azure Managed Redis.

**Query (F4)**
API in container su App Service, con interfaccia web per i tecnici. Per una domanda: impianto (PostgreSQL) → pagine del manuale del modello (Cosmos) + interventi simili (pgvector) → risposta con citazioni (documento, pagina, intervento). Risposte in cache su Redis (esatta e semantica). I **feature flag in App Configuration** attivano a runtime la cache semantica e l'uso degli interventi nelle risposte. AKS non ha un ruolo nel prodotto: si studia con un esperimento separato.

**Trasversali (F5)**
App Configuration (config e feature flag), OpenTelemetry → Application Insights. L'app non ha segreti (solo managed identity): Key Vault si studia con un esperimento separato.

**Infrastruttura**
Tutto in `infra/main.bicep`. `scripts/deploy/up.ps1` crea l'ambiente da zero (Bicep in due passate, immagini, Function, dati di esempio); `scripts/deploy/down.ps1` lo cancella a fine sessione, così i costi restano a zero tra una sessione e l'altra.

## Sviluppo

- Python 3.12, un `requirements.txt` per componente; `requirements-dev.txt` alla radice per l'ambiente di sviluppo unico (`.venv`).
- Test con pytest, dalla radice: `.venv\Scripts\python.exe -m pytest tests`.
- Le immagini si buildano con **contesto `src/`**, non con la cartella del componente, così il Dockerfile può copiare `shared/` e `fielddata/`. Il Dockerfile resta accanto al suo componente e si indica con `-f`:

```bash
az acr build --registry <acr> --image regdoc-worker:<tag> -f src/worker/Dockerfile src/
```

## Regole

### Codice
- Python, SDK Azure ufficiali (`azure-*`). Niente wrapper di terze parti se l'SDK ufficiale copre il caso.
- Autenticazione sempre con `DefaultAzureCredential` / managed identity. Mai connection string, chiavi o SAS nel codice.
- Nessun segreto nei file committati: i secret stanno in Key Vault, endpoint e nomi risorsa in App Configuration o in variabili d'ambiente. I file con valori locali (`.env`, `local.settings.json`) restano fuori dal repo — verifica che siano in `.gitignore` prima di crearli.

### Repo pubblico
Il repository è pubblico: tutto ciò che viene committato, cronologia compresa, va considerato pubblicato.
- Mai nel repo: subscription ID, tenant ID, client/object ID, nomi di sottoscrizioni o tenant, chiavi, connection string, SAS, token, indirizzi IP, email.
- Gli script leggono questi valori da variabili d'ambiente o da `scripts/env.ps1` (non tracciato); nel repo va solo `scripts/env.example.ps1` con segnaposto. I valori personali (utente, IP) arrivano al Bicep come parametri al deploy.
- Output di `az`, `kubectl` e KQL riportati nei docs (soprattutto `troubleshooting-log.md`) vanno ripuliti: resource ID come `/subscriptions/<subscription-id>/resourceGroups/...`, niente GUID o IP reali.
- Nomi di risorse inventati per il progetto (es. `rg-regdoc-dev`) vanno bene.

### Risorse Azure
- **Non eseguire comandi che creano o modificano risorse**: `az ... create/update/delete`, `az acr build`, `kubectl apply/delete`, `func ... publish`, `docker push`, deploy in generale. Proponili nella risposta, nel Bicep o negli script sotto `scripts/`: li eseguo io, perché la configurazione fa parte dello studio.
- I comandi di sola lettura (`az ... show/list`, `kubectl get/describe/logs`, `docker build` locale) vanno bene.

### Commenti didattici
Quando il codice tocca un argomento d'esame, aggiungi un commento breve che spiega **la scelta**, non cosa fa la riga: consistency level, indexing policy, partition key, gestione della dead-letter, regole di scaling KEDA, TTL e chiavi della cache, tipo di indice pgvector. Un commento per decisione, non un tutorial.

### Decision log
Dopo ogni decisione architetturale, proponi in fondo alla risposta una voce per `docs/decision-log.md`: data, decisione, alternative scartate, motivo, fase e skill AI-200 toccata. Scrivila nel file solo se te lo chiedo.

### Troubleshooting log
Dopo ogni problema risolto, proponi allo stesso modo una voce per `docs/troubleshooting-log.md`: data, sintomo, diagnosi (comandi o query KQL usati), causa, soluzione, skill AI-200 collegata. Scrivila nel file solo se te lo chiedo.

## Struttura delle cartelle

```
src/
  shared/              # libreria comune: modelli dei chunk, client degli embedding, config, telemetria
  ingestion/           # Function App
    function_app.py    #   on_blob_created: Event Grid → topic documents
    catalog.py         #   on_document_uploaded: subscription catalog → catalogo (PostgreSQL)
    changefeed.py      #   on_chunks_changed: change feed → evento custom, catalogo, invalidazione cache
  worker/              # consumer della subscription indexer su Container Apps: PDF → chunk → Cosmos
  fielddata/           # accesso a PostgreSQL: impianti, interventi, catalogo, ricerca di guasti simili
  api/                 # API di query e interfaccia web (static/), immagine per App Service
infra/
  main.bicep           # tutta l'infrastruttura
  modules/             # moduli Bicep (database e container Cosmos)
  postgres/schema.sql  # schema dei dati dal campo e del catalogo
scripts/
  env.example.ps1      # variabili dei comandi az (copia in env.ps1, non tracciato)
  deploy/              # up.ps1, down.ps1, smoke-test.ps1
  db/                  # schema, permessi delle identità, import dei dati di esempio, riallineamento catalogo
  tools/               # strumenti di diagnosi e misura: query, peek Service Bus, ricerche, benchmark
docs/
  decision-log.md
  troubleshooting-log.md
  study/               # materiale d'esame: skill AI-200, recap per modulo, note Python
tests/
samples/               # manuali tecnici di prova (PDF, non tracciati)
```

Ogni componente containerizzato ha il suo `Dockerfile` e il suo `requirements.txt` accanto al codice; `src/shared/` e `src/fielddata/` entrano nelle immagini grazie al contesto di build.
