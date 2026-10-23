# Recap 05 — Azure Database for PostgreSQL

Dominio d'esame: **2. Soluzioni AI con i servizi di data management (25–30%)** → *Azure Database for PostgreSQL*.
Svolto il 2026-10-23 (F3). Componenti: Flexible Server B1ms con pgvector, schema in `infra/postgres/schema.sql`,
accesso in `src/fielddata/`, script in `scripts/db/` e `scripts/tools/`.

| Skill | Stato |
|---|---|
| Connessione e query tramite SDK | ☑ |
| Modellazione dello schema: tabelle e tipi di dato | ☑ |
| Strategie di indicizzazione per pgvector | ☑ |
| Dimensionamento di compute, memoria e storage per workload vettoriali | ☑ |
| Vector search, retrieval semantico, RAG con filtri sui metadati | ☑ |
| Ottimizzazione delle connessioni | ☑ |

Il ruolo nel prodotto: i **dati dal campo** (clienti → impianti → interventi) e il **catalogo dei documenti**.
Gli interventi hanno un embedding per trovare "guasti simili già risolti" sullo stesso modello.

---

## 1. Il server

- **Flexible Server** (il Single Server è ritirato). Tier: **Burstable** (B, CPU a crediti, sviluppo), **General
  Purpose** (D), **Memory Optimized** (E).
- **Solo Entra ID** (`passwordAuth: Disabled`): nessuna password da custodire. Amministratore Entra a livello di server.
- **Estensioni**: vanno prima **autorizzate** sul server (parametro `azure.extensions = VECTOR`), poi create nel
  database con `CREATE EXTENSION vector`. Senza il primo passo il secondo fallisce.
- **Arresto**: `az postgres flexible-server stop` ferma il compute (lo storage si paga comunque); **dopo 7 giorni
  Azure lo riavvia da solo**.
- **Capacità**: in swedencentral il Burstable non aveva capacità (`RegionalAllocationFailed`, diverso da un errore di
  quota): server creato in northeurope.

## 2. Connessione con Entra ID

```python
token = DefaultAzureCredential().get_token("https://ossrdbms-aad.database.windows.net/.default").token
psycopg.connect(host=..., dbname="regdoc", user=<UPN o nome dell'identità>, password=token, sslmode="require")
```

- Il **token è la password**; vale circa un'ora e serve **solo all'apertura**: una connessione aperta resta valida.
- **Managed identity**: un amministratore crea il ruolo dal database `postgres` con
  `pgaadauth_create_principal('<nome>', false, false)`; per una system-assigned il nome è quello della risorsa.
  Poi `GRANT` come per qualunque ruolo (`scripts/db/grant_app_role.py`: profilo `api` sola lettura, `catalog` solo
  la tabella `documents`).
- I nomi dei ruoli hanno un limite di **63 caratteri**: l'UPN di un utente ospite (`#EXT#`) viene troncato.

## 3. Lo schema

| Scelta | Perché |
|---|---|
| `bigint GENERATED ALWAYS AS IDENTITY` | chiave surrogata standard SQL (al posto di `serial`) |
| Chiave naturale `UNIQUE` (codice cliente, matricola, `external_ref`) | upsert ripetibili con `INSERT ... ON CONFLICT DO UPDATE` |
| `jsonb` per gli attributi liberi | indicizzabile, operatori `->>`, `@>`; `json` è solo testo |
| `CHECK (kind IN (...))` al posto di `ENUM` | aggiungere un valore è un `ALTER` del vincolo |
| `vector(1536)` | dimensione fissata dal modello di embedding |
| Indici sulle foreign key creati a mano | **PostgreSQL non li crea da solo** (a differenza della PK) |
| Vista `documents_status` | lo stato si ricava da due date, nessun aggiornamento fuori ordine |

L'import scrive tutto in **una transazione**: se fallisce a metà non resta niente di parziale.

## 4. Ricerca vettoriale e RAG

| Operatore | Distanza | Operator class dell'indice |
|---|---|---|
| `<->` | euclidea (L2) | `vector_l2_ops` |
| `<=>` | coseno | `vector_cosine_ops` |
| `<#>` | prodotto interno (negativo) | `vector_ip_ops` |

```sql
SELECT ..., iv.embedding <=> %(q)s AS distance
FROM interventions iv JOIN installations i ON i.id = iv.installation_id
WHERE i.domain = %(domain)s AND i.model = %(model)s AND iv.kind = 'guasto'
ORDER BY iv.embedding <=> %(q)s
LIMIT 4
```

- Filtri relazionali (JOIN, WHERE) e somiglianza **nella stessa query**: è il vantaggio rispetto a un vector store puro.
- La ricerca restituisce **sempre** k righe, anche lontane: serve una **soglia** di distanza (in RegDoc 0,42,
  tarata sui dati e regolabile da App Configuration).
- Il testo dell'embedding si sceglie una volta (`Sintomo: … Intervento: …`) e va usato identico in import e ricerca.

## 5. Indici

- Senza indice: ricerca **esatta**, costo lineare. Con filtri selettivi è già veloce (0,4 ms sulle 10 Karolina).
- **L'indice lo sceglie il planner**, in base ai costi: con poche righe lo ignora. Lo usa solo con
  `ORDER BY <operatore> LIMIT k` e lo **stesso operatore** dell'operator class.

Misure su 20.000 vettori sintetici (`scripts/tools/vector_bench.py`), riferimento esatto 185 ms:

| Indice | Build | Ricerca | Note |
|---|---|---|---|
| IVFFlat `lists=20`, `probes=1` | 8 s | 17 ms | recall 0,70; i gruppi si calcolano **sui dati presenti alla creazione** |
| IVFFlat `probes=4` | | 38 ms | recall 1,00 |
| IVFFlat `probes=10` | | — | il planner torna alla scansione completa |
| HNSW `m=16`, `ef_construction=64`, `ef_search=40` | 44 s | 2 ms | grafo: nessun training, regge gli inserimenti continui |

Scelta: **HNSW** (la tabella cresce ogni giorno). La recall bassa del bench dipendeva dai dati sintetici a cluster
(vedi il troubleshooting log): **gli indici approssimati si valutano sui propri dati**.

## 6. Connessioni

- Ogni connessione è un **processo** del server: aprirla costa TCP + TLS + token + autenticazione.
  Misurato: **~1050 ms** per una connessione nuova, **~110 ms** dal pool.
- **Pool nell'applicazione** (`psycopg_pool`): token chiesto a ogni nuova connessione (il pool ne apre anche ore dopo).
- **PgBouncer integrato** (porta 6432, pool mode transaction): **non disponibile sul tier Burstable**.
- `max_connections` dipende dallo SKU (B1ms: 50, di cui 15 riservate): **repliche × max_size del pool ≤ connessioni libere**.

## 7. Dimensionamento per i vettori

| Grandezza | Valore | Conseguenza |
|---|---|---|
| Un vettore `vector(1536)` | 1536 × 4 byte ≈ **6 KB** | una pagina da 8 KB ne contiene **uno solo** |
| 20.000 vettori | **158 MB** di tabella, **158 MB** per indice | ogni indice vettoriale raddoppia lo spazio |
| 1 milione di vettori | ~8 GB tabella + ~8 GB indice | oltre la RAM di un B1ms (2 GB) |
| `halfvec(1536)` | 2 byte per dimensione | metà spazio, recall quasi invariata |

- **Memoria**: la ricerca HNSW è veloce se l'indice sta in RAM (`shared_buffers` + cache del sistema operativo).
  Quando non ci sta, ogni ricerca legge dal disco: si passa a **Memory Optimized**.
- **Costruzione dell'indice**: usa `maintenance_work_mem` (B1ms: ~97 MB); se il grafo non ci sta la build rallenta
  molto. Si alza per la sessione (`SET maintenance_work_mem = '256MB'`) senza superare la RAM.
- **CPU**: il calcolo delle distanze è CPU-bound; il Burstable consuma crediti e sotto carico continuo rallenta:
  **General Purpose** per un carico costante.
- **Storage**: auto-grow attivo; IOPS legati alla dimensione del disco (32 GB → P4, 120 IOPS).

## Trappole d'esame

| Situazione | Risposta |
|---|---|
| `CREATE EXTENSION vector` fallisce | estensione non autorizzata in `azure.extensions` |
| L'indice vettoriale non viene usato | operatore diverso dall'operator class, manca `ORDER BY ... LIMIT`, tabella troppo piccola |
| IVFFlat creato su tabella vuota | gruppi calcolati sul nulla: crearlo dopo il caricamento (o usare HNSW) |
| Recall bassa con IVFFlat / HNSW | alzare `ivfflat.probes` / `hnsw.ef_search` (più lento) |
| Molte connessioni brevi su Burstable | pool nell'applicazione (PgBouncer integrato non c'è) |
| Token Entra scaduto in un'app con pool | chiedere un token nuovo a ogni nuova connessione |
| JOIN lente su impianti di un cliente | foreign key senza indice |
| Server fermo "riacceso da solo" | lo stop dura al massimo 7 giorni |

## Domande di ripasso

1. Perché i dati dal campo stanno su PostgreSQL e i chunk dei manuali su Cosmos DB?
2. Che cosa serve, lato server e lato database, per usare pgvector?
3. Come si autentica una managed identity su PostgreSQL? Che cosa fa `pgaadauth_create_principal`?
4. Differenze tra HNSW e IVFFlat: costruzione, inserimenti, parametri di ricerca.
5. Perché con 184 interventi il planner non usa l'indice HNSW? Che cosa cambia con 1 milione?
6. Perché un pool di connessioni e non PgBouncer in RegDoc? Quando cambieresti scelta?
7. Quanto spazio occupano 100.000 embedding da 1536 dimensioni, con un indice HNSW? Con `halfvec`?
8. Perché la ricerca degli interventi ha bisogno di una soglia di distanza?
