# Recap 04 — Azure Cosmos DB for NoSQL

Dominio d'esame: **2. Soluzioni AI con i servizi di data management (25–30%)** → *Azure Cosmos DB for NoSQL*.
Completato il 2026-10-23 (F2). Componenti: account serverless, container `chunks` e `leases` (`infra/modules/cosmos-db.bicep`),
worker `src/worker`, funzione `on_chunks_changed` in `src/ingestion/changefeed.py`, script `scripts/tools/search_cosmos.py`.

| Skill | Come è stata coperta |
|---|---|
| Connessione tramite SDK ed esecuzione di query | `azure-cosmos` con `DefaultAzureCredential`; upsert, query parametrizzate, delete; RU lette dagli header |
| Indexing policy e consistency level | Session; esclusione di `/embedding/*` e `/text/?`; confronto dei costi in RU |
| Embedding e vector similarity search | policy vettoriale, vector index `quantizedFlat`, `VectorDistance` con filtro sul dominio |
| Change feed processor | trigger Cosmos DB di Functions con lease container, retry policy, evento custom su Event Grid |

---

## 1. Account

```powershell
az cosmosdb create --resource-group $RG --name $COSMOS --kind GlobalDocumentDB `
  --locations regionName=$LOCATION failoverPriority=0 isZoneRedundant=False `
  --capabilities EnableServerless EnableNoSQLVectorSearch --default-consistency-level Session --disable-local-auth true
```

- **RU** (Request Unit): costo normalizzato di ogni operazione (lettura per id di 1 KB ≈ 1 RU). Ogni risposta lo riporta nell'header `x-ms-request-charge`.
- **Modelli di throughput**: *serverless* (paghi le RU consumate, adatto a traffico sporadico), *provisioned* (RU/s riservate), *autoscale* (dal 10% al 100% di un massimo). Si sceglie alla creazione.
- `--disable-local-auth`: niente chiavi primarie/secondarie, solo Entra ID.

### Consistency level

| Livello | Garanzia |
|---|---|
| Strong | ogni lettura vede l'ultima scrittura confermata |
| Bounded Staleness | ritardo massimo limitato (K versioni o T secondi) |
| **Session** (default, scelto) | nella stessa sessione leggi le tue scritture |
| Consistent Prefix | mai fuori ordine, ma possibilmente in ritardo |
| Eventual | nessuna garanzia d'ordine, converge col tempo |

Più forte = più latenza e più costo, soprattutto con più regioni.

## 2. Container `chunks` (Bicep)

Database e container creati con Bicep (`az deployment group create`), perché la CLI non gestisce bene le partition key gerarchiche e perché con l'RBAC nativo **non si creano container dal data plane**. Bicep è **idempotente**: rilanciare il deploy porta le risorse allo stato descritto senza duplicarle (verificato aggiungendo `leases`).

### Partition key gerarchica `/domain` → `/document_id`

| Alternativa | Problema |
|---|---|
| `/domain` | bassa cardinalità → hot partition; un dominio oltre 20 GB |
| `/document_id` | query RAG per dominio in fan-out su tutte le partizioni |
| `/id` | tutto fan-out |
| **`/domain` → `/document_id`** (MultiHash) | query per dominio instradate al prefisso; chunk di un documento in una sola partizione logica; nessun limite di 20 GB per dominio |

- Una query con la partition key va su **una** partizione; senza va su **tutte** (fan-out, più RU).
- Partizione logica: max **20 GB**. Con la chiave gerarchica la partizione logica è la coppia completa.
- Con chiavi gerarchiche, ripetere i valori della chiave nel `WHERE` garantisce l'instradamento.

### Indexing policy

- Per default ogni campo è indicizzato, e ogni campo indicizzato **costa RU a ogni scrittura**.
- Esclusi `/embedding/*` (1536 numeri mai filtrati) e `/text/?`: è la scelta che riduce di più il costo delle scritture.
- **Vector index** separato su `/embedding`:

| Tipo | Ricerca | Quando |
|---|---|---|
| `flat` | esatta | max 505 dimensioni |
| **`quantizedFlat`** | esaustiva su vettori compressi (`quantizationByteSize` 96) | fino a ~50.000 vettori per query |
| `diskANN` | approssimata (ANN) | oltre ~50.000 vettori |

Sotto i 1.000 vettori `quantizedFlat` e `diskANN` fanno comunque una scansione completa.

### Policy vettoriale

`float32`, `cosine`, **1536 dimensioni** = `text-embedding-3-small`. **Non modificabile** dopo la creazione: un modello con altre dimensioni richiede un container nuovo.

## 3. Sicurezza: RBAC nativo per i dati

| | Azure RBAC | RBAC nativo Cosmos |
|---|---|---|
| Protegge | control plane (account, database, container, chiavi) | data plane (documenti, query, change feed) |
| Comando | `az role assignment create` | `az cosmosdb sql role assignment create` |
| Ruoli | DocumentDB Account Contributor, Cosmos DB Operator… | **Built-in Data Reader** (`…0001`), **Built-in Data Contributor** (`…0002`) |
| Scope | subscription / RG / account | `/`, `/dbs/<db>`, `/dbs/<db>/colls/<c>` |

| Identità | Ruolo | Scope |
|---|---|---|
| utente (sviluppo) | Data Contributor | `/dbs/regdoc` |
| worker | Data Contributor | `/dbs/regdoc/colls/chunks` |
| Function (change feed) | Data **Reader** | `/dbs/regdoc/colls/chunks` |
| Function (change feed) | Data Contributor | `/dbs/regdoc/colls/leases` |

## 4. SDK Python (`azure-cosmos`)

```python
container = CosmosClient(endpoint, credential=DefaultAzureCredential()) \
    .get_database_client("regdoc").get_container_client("chunks")
container.upsert_item(item)                                   # crea o sostituisce
container.query_items(query="SELECT c.id FROM c WHERE c.domain = @d AND c.document_id = @doc",
                      parameters=[...], partition_key=[domain, document_id])  # partizione singola
container.delete_item(item=item_id, partition_key=[domain, document_id])
charge = container.client_connection.last_response_headers["x-ms-request-charge"]
```

- **Idempotenza**: id deterministici (`document_id` = hash del percorso del blob, chunk `document_id-0007`) + upsert → rielaborare un messaggio o ricaricare un manuale **sostituisce** i chunk (verificato: 106, non 212). Chunk in eccesso di una versione più corta → cancellati.
- Query **parametrizzate** (`@domain`), mai valori concatenati nella stringa.

### Costi osservati

| Operazione | RU |
|---|---|
| query per dominio con 1 risultato (Data Explorer) | 2,82 |
| indicizzazione di un manuale (106 upsert) | 2.914 |
| reindicizzazione dello stesso manuale (replace + query) | ~3.100–3.200 |
| ricerca vettoriale TOP 5 su 106 vettori | ~9,4 |

Sostituire costa più che creare: l'indice va aggiornato togliendo i valori vecchi.

## 5. Ricerca vettoriale

```sql
SELECT TOP 5 c.file_name, c.page, c.text, VectorDistance(c.embedding, @q) AS score
FROM c
WHERE c.domain = @domain
ORDER BY VectorDistance(c.embedding, @q)
```

- `@q` = embedding della domanda, calcolato con **lo stesso modello** dei chunk.
- `ORDER BY VectorDistance` + `TOP k` = k-nearest neighbors; con cosine, punteggio più alto = più simile.
- `WHERE` = filtro sui metadati combinato con la ricerca vettoriale (pattern RAG con filtri).
- Il Data Explorer non può eseguirla (non ha parametri né calcola embedding): testo → vettore (Foundry), vettore → chunk (Cosmos).
- `CONTAINS(c.text, 'braciere', true)` trova la parola esatta; la ricerca vettoriale trova il significato.

## 6. Change feed

- Registro ordinato (**per partizione**) di creazioni e modifiche dei documenti.
- Modalità *latest version*: **non registra le cancellazioni** (servono *all versions and deletes* o un soft delete con TTL); modifiche ravvicinate possono comparire come una sola (l'ultima versione).
- Come leggerlo:

| Opzione | Note |
|---|---|
| Change feed processor (SDK) | lease, checkpoint, più istanze; solo .NET e Java |
| Pull model (SDK) | continuation token da gestire a mano |
| **Trigger Cosmos DB di Functions** (scelto) | costruito sul change feed processor; disponibile in Python |

```python
@bp.retry(strategy="exponential_backoff", max_retry_count="5", minimum_interval="00:00:05", maximum_interval="00:05:00")
@bp.cosmos_db_trigger(arg_name="docs", connection="CosmosDB", database_name="regdoc",
                      container_name="chunks", lease_container_name="leases",
                      create_lease_container_if_not_exists=False)
def on_chunks_changed(docs: func.DocumentList) -> None: ...
```

- **Lease container**: segnalibri del processor (partition key `/id`). Con Entra ID va creato prima (Bicep).
- Connessione a identità: app setting `CosmosDB__accountEndpoint`.
- Al primo avvio legge solo le modifiche **da quel momento** (`start_from_beginning` per rileggere tutto).
- Massimo 100 documenti per invocazione → 106 chunk = **2 lotti** → 2 eventi per lo stesso documento: i consumatori devono essere idempotenti.
- **Retry policy obbligatoria**: senza, se la funzione fallisce il segnalibro avanza comunque e le modifiche sono perse.
- Un trigger che non riesce ad avviarsi (es. 403 sul lease container) **non produce invocazioni**: l'errore è nei log dell'host (`traces`, `severityLevel >= 3`).

## 7. Evento custom su Event Grid

- Custom topic `--input-schema cloudeventschemav1_0`, chiavi disattivate, identità system-assigned.
- La Function pubblica con `EventGridPublisherClient` + `CloudEvent` (ruolo **EventGrid Data Sender**).
- Event subscription verso una coda Storage con consegna e **dead-letter con identità**; Event Grid valida i permessi alla creazione e li vuole **sullo storage account**.
- Nelle code Storage gli eventi arrivano **in Base64**.

---

## Errori incontrati

| Sintomo | Causa | Soluzione |
|---|---|---|
| query con `@q` nel Data Explorer non funziona | i parametri li riempie il codice; serve l'embedding | script `search_cosmos.py` |
| `on_chunks_changed` senza invocazioni, lease container vuoto | ruoli Cosmos nativi della Function mancanti → il trigger non parte | Reader su `chunks`, Contributor su `leases`, restart |
| `az resource update` sul topic: *Endpoint is a read-only property* | GET+PUT include proprietà read-only | `az rest --method patch` |
| topic senza identità dopo la PATCH | la PATCH (o la creazione) ha lasciato `identity: None` | PATCH con `{"identity": {"type": "SystemAssigned"}}` e verifica |
| `Managed Identity Authorization Error` creando la event subscription | ruoli con scope su coda/container, Event Grid li vuole sull'account | ruoli sullo storage account |

## Trappole d'esame

| Situazione | Risposta |
|---|---|
| App con *DocumentDB Account Contributor* riceve 403 leggendo documenti | manca un ruolo **data plane nativo** (Data Reader/Contributor) |
| Creare un container con Entra ID dal codice | non si può con l'RBAC nativo: ARM (CLI, Bicep, portale) |
| Scritture costose su documenti grandi | escludere dall'indice i campi non filtrati |
| Query lenta e costosa senza partition key | fan-out: includere la partition key (o il suo prefisso) |
| Partizione logica oltre 20 GB | partition key gerarchica o chiave a più alta cardinalità |
| Vettori da 1536 dimensioni e index `flat` | non supportato (max 505): `quantizedFlat` o `diskANN` |
| Cambiare le dimensioni dei vettori | nuovo container: la policy vettoriale non si modifica |
| Leggere le proprie scritture con il minimo costo | Session |
| Il change feed non vede le cancellazioni | latest version mode: soft delete o all versions and deletes |
| Modifiche perse quando la funzione del change feed fallisce | retry policy sul trigger |

## Domande di ripasso

1. Perché la partition key è gerarchica, e cosa succede a una query che filtra solo per `document_id`?
2. Che cosa cambia tra escludere `/embedding/*` dall'indice e definire un vector index su `/embedding`?
3. Quando sceglieresti `diskANN` invece di `quantizedFlat`?
4. Qual è la differenza tra *Cosmos DB Built-in Data Contributor* e *DocumentDB Account Contributor*?
5. Come garantisce il worker che ricaricare un manuale non duplichi i chunk?
6. Perché la stessa query vettoriale non funziona nel Data Explorer?
7. A cosa serve il lease container, e perché l'abbiamo creato con Bicep?
8. Perché un manuale da 106 chunk ha prodotto due eventi?
9. Che cosa succede senza retry policy se `on_chunks_changed` va in errore?
10. Il change feed vede un chunk cancellato dal worker? Come lo renderesti visibile?
