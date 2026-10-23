# Decision log

Decisioni architetturali di RegDoc, dalla più recente alla più vecchia.
Formato di una voce:

```
## AAAA-MM-GG — Titolo breve

**Decisione**: cosa è stato deciso.
**Alternative scartate**: le opzioni valutate e perché non sono state scelte.
**Motivo**: la ragione principale della scelta.
**Fase / skill**: fase RegDoc e skill AI-200 toccate (vedi ai200-skills.md).
```

---

## 2026-10-23 — Infrastruttura in Bicep, ambiente effimero

**Decisione**: tutta l'infrastruttura in `infra/main.bicep`; `scripts/deploy/up.ps1` crea l'ambiente da zero
(Bicep in due passate, immagini, Function, dati di esempio) e `scripts/deploy/down.ps1` lo cancella a fine sessione.
La seconda passata crea ciò che dipende da immagini e codice già pubblicati (worker, sottoscrizioni Event Grid).

**Alternative scartate**: risorse create a mano con `az` e lasciate accese (costi fissi anche da ferme, configurazione
non riproducibile e documentata solo nella cronologia dei comandi); un solo deploy Bicep (Container Apps rifiuta
un'immagine che non esiste ancora in ACR, Event Grid una funzione non ancora pubblicata).

**Motivo**: costi a zero tra una sessione e l'altra e un ambiente sempre ricostruibile identico, ruoli compresi.

**Fase / skill**: trasversale — tutte le risorse; nessuna skill AI-200 specifica (Bicep non è nel perimetro d'esame).

## 2026-10-23 — Fonti mostrate = fonti citate; soglia sugli interventi in App Configuration

**Decisione**: l'API restituisce solo le fonti citate nel testo della risposta. Gli interventi oltre una distanza
coseno di 0,42 non entrano nel prompt; la soglia è la chiave `RegDoc:Interventions:MaxDistance` in App Configuration.

**Alternative scartate**: mostrare tutte le fonti recuperate (il retrieval porta sempre i k più vicini, anche
estranei: guasti alla sonda fumi per una domanda sull'orologio); solo la soglia (nessun valore separa tutti i casi:
"vetro che diventa nero" è pertinente a 0,50, "imposta data e ora" non lo è a 0,45); soglia nel codice.

**Motivo**: il tecnico deve poter verificare la risposta sulle fonti che l'hanno prodotta. La soglia dipende dai
dati e va ritarata su quelli reali senza un nuovo deploy.

**Fase / skill**: F4, F5 — PostgreSQL (vector search, RAG); App Configuration.

## 2026-10-23 — Catalogo dei documenti su PostgreSQL con stato derivato

**Decisione**: tabella `documents` su PostgreSQL scritta da due flussi indipendenti: la funzione `on_document_uploaded`
(trigger Service Bus sulla subscription `catalog` del topic) registra `uploaded_at`, il change feed di Cosmos
registra `indexed_at`. Lo stato (indicizzato / in indicizzazione) si ricava nella vista `documents_status`.
Lo script `sync_catalog.py` riallinea il catalogo con storage e Cosmos.

**Alternative scartate**: colonna `status` aggiornata dai due flussi (worker e catalogo lavorano in parallelo: un
messaggio in ritardo riporterebbe indietro lo stato); catalogo su Cosmos (servono JOIN con gli impianti); catalogo
scritto dal worker (un'altra dipendenza nel componente più critico, e il fan-out del topic esiste per questo).

**Motivo**: il tecnico vede quali manuali esistono per il suo impianto e se sono interrogabili; chi gestisce i
documenti vede i caricamenti bloccati. Il trigger delle Functions non richiede container né costi fissi.

**Fase / skill**: F1–F3 — Service Bus (fan-out, dead-letter), Azure Functions (trigger e binding), PostgreSQL (schema).

## 2026-10-23 — Cache delle risposte su Managed Redis con invalidazione per versione

**Decisione**: cache esatta (chiave: hash di domanda normalizzata e ambito) e semantica (indice vettoriale
RediSearch, KNN 1, distanza massima 0,06) con TTL di 24 ore. L'ambito comprende modello, impianto, uso degli
interventi e versione del formato. Il change feed incrementa `regdoc:ver:{dominio}`: le risposte con la versione
vecchia non vengono più lette e scadono da sole.

**Alternative scartate**: cancellare le chiavi con SCAN + DEL (costoso, non atomico); solo TTL (risposte obsolete
per ore dopo l'aggiornamento di un manuale); cache in memoria del processo (non condivisa tra repliche).

**Motivo**: la generazione è la parte lenta e costosa di una risposta (circa 3 s su 4); l'invalidazione per versione
è un INCR atomico e idempotente rispetto agli eventi duplicati del change feed.

**Fase / skill**: F3 — Azure Managed Redis (caching, expiration, invalidazione; indicizzazione vettoriale).

## 2026-10-23 — Feature flag e configurazione dinamica in App Configuration

**Decisione**: flag `use-interventions` e `semantic-cache` e chiavi `RegDoc:*` lette con il provider Python e
`FeatureManager`; refresh ogni 30 s tramite la chiave sentinella `RegDoc:Sentinel`. Senza App Configuration valgono
i default del codice.

**Alternative scartate**: variabili d'ambiente (ogni modifica riavvia l'app); controllare tutte le chiavi a ogni
refresh (una richiesta per chiave invece di una sola).

**Motivo**: attivare funzionalità e tarare parametri in esercizio senza deploy, con autenticazione solo Entra ID.

**Fase / skill**: F5 — App Configuration.

## 2026-10-23 — Connection pooling lato applicazione per PostgreSQL

**Decisione**: `psycopg_pool.ConnectionPool` nell'API, token Entra chiesto a ogni nuova connessione, `max_size=5`
per replica.

**Alternative scartate**: PgBouncer integrato (non disponibile sul tier Burstable); PgBouncer come sidecar (un
componente in più da gestire); una connessione per richiesta (circa 1 s ciascuna contro 0,1 s dal pool).

**Motivo**: B1ms ha 50 connessioni, di cui 15 riservate; il pool riduce la latenza di 10 volte e tiene sotto
controllo il totale (repliche × max_size ≤ connessioni libere).

**Fase / skill**: F3 — PostgreSQL (ottimizzazione delle connessioni).

## 2026-10-23 — Indice HNSW sugli embedding degli interventi

**Decisione**: indice `hnsw (embedding vector_cosine_ops)` sulla tabella `interventions`, parametri di default.

**Alternative scartate**: IVFFlat (nel bench su 20.000 vettori sintetici era più preciso a parità di tempo, ma
calcola i suoi gruppi solo alla creazione e la tabella cresce ogni giorno); nessun indice (oggi basta, non scala).

**Motivo**: HNSW si aggiorna a ogni inserimento ed è il più veloce su dati reali e diversificati. Con filtri
selettivi (stesso modello) il planner continua a scegliere la ricerca esatta tramite gli indici B-tree.

**Fase / skill**: F3 — PostgreSQL (strategie di indicizzazione per pgvector).

## 2026-10-23 — PostgreSQL per i dati dal campo; abbandonato il doppio store dei chunk

**Decisione**: Cosmos DB resta l'unico archivio dei chunk dei manuali. PostgreSQL Flexible Server con pgvector
gestisce i dati relazionali dal campo (clienti, impianti installati, interventi) e la ricerca semantica sulle note
d'intervento ("guasti simili già risolti"), con filtri relazionali. I feature flag di App Configuration attivano
funzionalità (cache semantica, uso degli interventi nelle risposte), non scelgono lo store di lettura.
Sostituisce la decisione del 2026-09-23.

**Alternative scartate**: doppia scrittura dei chunk su Cosmos e pgvector con flag sullo store di lettura
(architettura da laboratorio: costi e sincronizzazione doppi senza beneficio funzionale); PostgreSQL come unico
archivio dei manuali con Cosmos per la cronologia delle conversazioni (avrebbe richiesto di rifare F2).

**Motivo**: l'app deve essere realistica, con un ruolo reale per ogni componente. I dati dal campo sono relazionali
per natura (cliente → impianto → interventi) e danno alle risposte un valore che i soli manuali non hanno.

**Fase / skill**: F3, F4 — Azure Database for PostgreSQL (tutte le skill); Cosmos DB; App Configuration.

## 2026-10-23 — Change feed letto con il trigger Cosmos DB di Azure Functions

**Decisione**: la reazione alle modifiche del container `chunks` è una seconda funzione (`on_chunks_changed`) nella
Function App esistente, con trigger Cosmos DB, lease container `leases` creato via Bicep, connessione a identità e
retry policy esponenziale. Pubblica un CloudEvent `RegDoc.Document.Indexed` per documento su un custom topic.

**Alternative scartate**: componente `changefeed/` in container con il change feed processor dell'SDK (non esiste
nell'SDK Python, solo .NET e Java); pull model dell'SDK (checkpoint e coordinamento tra istanze da scrivere a mano).

**Motivo**: il trigger di Functions è costruito sul change feed processor (lease, checkpoint, scaling) ed è
disponibile in Python; nessuna infrastruttura in più.

**Fase / skill**: F2 — Cosmos DB change feed processor; Event Grid eventi custom; Azure Functions trigger.

## 2026-10-23 — Identità separata per lo scaler KEDA del worker

**Decisione**: la container app del worker ha due identità user-assigned: `id-regdoc-worker` per il codice
(`AZURE_CLIENT_ID`) con permessi di sola ricezione, e `id-regdoc-scaler` usata solo dalla regola KEDA
`azure-servicebus`, con Azure Service Bus Data Owner sul topic `documents`.

**Alternative scartate**: Data Owner all'identità del worker (il codice avrebbe anche permessi di invio e gestione);
connection string con SAS nella regola di scaling (chiavi disattivate sul namespace).

**Motivo**: KEDA legge le statistiche della subscription, operazione che richiede Data Owner; separare le identità
mantiene il codice al minimo privilegio.

**Fase / skill**: F2 — Scaling event-driven con KEDA in Container Apps; Service Bus.

## 2026-10-23 — Cosmos DB: partition key gerarchica, indexing policy, quantizedFlat, serverless

**Decisione**: container `chunks` con hierarchical partition key `/domain` → `/document_id` (MultiHash); indexing
policy che esclude `/embedding/*` e `/text/?`; vector index `quantizedFlat`, float32, cosine, 1536 dimensioni;
account serverless, consistenza Session, chiavi disattivate. Database e container descritti in Bicep.

**Alternative scartate**: `/domain` (bassa cardinalità, limite 20 GB per dominio); `/document_id` (query RAG per
dominio in fan-out); `/id` (tutto fan-out); index `flat` (max 505 dimensioni); `diskANN` (conviene oltre ~50k
vettori); provisioned/autoscale (costo fisso non giustificato).

**Motivo**: le query filtrano per dominio e vengono instradate al prefisso della chiave; i chunk di un documento
restano in una partizione logica; meno RU in scrittura escludendo dall'indice i campi mai filtrati.

**Fase / skill**: F2 — Cosmos DB: indexing policy e consistency level; embedding e vector search.

## 2026-10-19 — Service Bus Standard, topic con duplicate detection, solo Entra ID

**Decisione**: namespace Standard con `disableLocalAuth`; topic `documents` con duplicate detection (finestra 10 min)
e `MessageId` = id dell'evento Event Grid; subscription `indexer` (lock 1 min, max delivery 5) e `catalog` (lock 30 s,
max delivery 3), entrambe con dead-letter alla scadenza.

**Alternative scartate**: Basic (non supporta i topic); Premium (costo non giustificato in dev); due code separate
al posto del topic (il mittente dovrebbe conoscere ogni consumatore).

**Motivo**: fan-out verso consumatori indipendenti; Event Grid consegna at-least-once e la duplicate detection
assorbe le riconsegne; nessuna SAS key, coerente con il resto del progetto.

**Fase / skill**: F1 — Service Bus (topic, subscription, dead-letter queue).

## 2026-10-19 — Versione dell'API inclusa nell'immagine, non nelle app settings

**Decisione**: `APP_VERSION` viene impostata a build time (`ARG`/`ENV` nel Dockerfile, `--build-arg` in
`az acr build`) con lo stesso valore del tag dell'immagine; nessuna app setting `APP_VERSION`.

**Alternative scartate**: app setting impostata a mano su App Service (si disallinea dall'immagine in esecuzione
e la sovrascrive, perché le app settings vincono sulle `ENV` dell'immagine).

**Motivo**: `/version` deve dire quale immagine sta girando, non cosa qualcuno ha scritto in configurazione.

**Fase / skill**: F4 — ACR (versioning delle immagini), deploy di container su App Service.

## 2026-10-19 — Pull da ACR con managed identity, admin user disabilitato

**Decisione**: App Service e Container Apps scaricano le immagini da ACR con una managed identity e il ruolo
AcrPull; l'admin user di ACR resta disabilitato.

**Alternative scartate**: admin user di ACR (credenziali condivise, contro la regola "mai chiavi"); service
principal con secret (secret da ruotare).

**Motivo**: nessuna credenziale da gestire, coerente con `DefaultAzureCredential` in tutto il progetto.

**Fase / skill**: F2/F4 — ACR, deploy di container su App Service e Container Apps.

## 2026-09-23 — Scrittura su entrambi gli store, feature flag solo in lettura

> **Superata** dalla decisione del 2026-10-23 "PostgreSQL per i dati dal campo; abbandonato il doppio store dei chunk".

**Decisione**: il worker di indicizzazione scrive ogni chunk sia su Cosmos DB for NoSQL sia su
PostgreSQL con pgvector. Il feature flag in App Configuration decide soltanto da quale dei due
store legge l'API di query.

**Alternative scartate**: un flag che sceglie anche lo store in scrittura, cioè un solo store
attivo per volta. Scartata perché con Cosmos disattivato il change feed non scatterebbe e la
cache Redis non verrebbe invalidata, e perché ogni cambio di flag richiederebbe una
reindicizzazione completa prima di poter confrontare i risultati.

**Motivo**: tenere i due store allineati sugli stessi dati rende il confronto immediato —
si sposta il flag e si interroga — e lascia il change feed di Cosmos sempre attivo come
sorgente dell'invalidazione della cache.

**Fase / skill**: F2, F3, F5 — Cosmos DB (vector search, change feed), PostgreSQL con pgvector,
App Configuration, Azure Managed Redis.
