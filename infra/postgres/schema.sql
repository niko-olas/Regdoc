-- Schema dei dati dal campo (F3): clienti → impianti → interventi.
-- Idempotente: si può rieseguire senza errori né duplicati.
-- In un'azienda questi dati arriverebbero dal gestionale (CRM/ERP); qui li carica lo script di import.

CREATE EXTENSION IF NOT EXISTS vector;

-- Clienti.
-- Due chiavi: `id` è la chiave interna (surrogata) usata dalle foreign key; `code` è il codice del
-- cliente nel gestionale (chiave naturale), UNIQUE perché l'import deve poter aggiornare senza duplicare.
CREATE TABLE IF NOT EXISTS customers (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code        text NOT NULL UNIQUE,
    name        text NOT NULL,
    city        text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Impianti installati presso i clienti.
-- domain/manufacturer/model sono gli stessi campi fissi dei manuali su Cosmos DB: è così che un
-- impianto trova i suoi manuali, senza chiavi tra due database diversi.
CREATE TABLE IF NOT EXISTS installations (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id    bigint NOT NULL REFERENCES customers (id) ON DELETE RESTRICT,
    domain         text NOT NULL,
    manufacturer   text NOT NULL,
    model          text NOT NULL,
    serial_number  text UNIQUE,
    installed_on   date,
    -- Attributi liberi del dominio (es. potenza_kw), come i metadati x-ms-meta-* dei manuali:
    -- jsonb e non colonne, perché cambiano da un dominio all'altro. jsonb (binario) e non json
    -- (testo): si può indicizzare e interrogare con gli operatori @>, ->, ->>.
    attributes     jsonb NOT NULL DEFAULT '{}'
);
-- PostgreSQL NON crea indici sulle foreign key: senza questo, "gli impianti del cliente X" e i JOIN
-- clienti → impianti leggerebbero l'intera tabella.
CREATE INDEX IF NOT EXISTS ix_installations_customer ON installations (customer_id);
-- Filtro tipico della ricerca: impianti dello stesso modello.
CREATE INDEX IF NOT EXISTS ix_installations_model ON installations (domain, manufacturer, model);

-- Interventi dei tecnici sugli impianti.
CREATE TABLE IF NOT EXISTS interventions (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    installation_id   bigint NOT NULL REFERENCES installations (id) ON DELETE RESTRICT,
    -- Chiave dell'intervento nel gestionale: rende l'import ripetibile senza duplicati.
    external_ref      text NOT NULL UNIQUE,
    performed_on      date NOT NULL,
    -- CHECK al posto di un tipo ENUM: aggiungere un valore è un semplice ALTER del vincolo.
    kind              text NOT NULL CHECK (kind IN ('installazione', 'manutenzione', 'guasto')),
    technician        text NOT NULL,          -- pseudonimo: mai dati personali reali
    symptom           text,                   -- cosa è stato segnalato o riscontrato
    resolution        text NOT NULL,          -- cosa è stato fatto
    duration_minutes  integer CHECK (duration_minutes > 0),
    -- Embedding di symptom + resolution con text-embedding-3-small, lo stesso modello dei manuali:
    -- 1536 dimensioni. NULL finché l'import non lo calcola.
    embedding         vector(1536)
);
-- "Ultimi interventi su questo impianto": la foreign key più l'ordinamento per data in un solo indice.
CREATE INDEX IF NOT EXISTS ix_interventions_installation ON interventions (installation_id, performed_on DESC);
-- Indice vettoriale HNSW e non IVFFlat: la tabella cresce ogni giorno e IVFFlat calcola i suoi gruppi
-- solo alla creazione (su 184 righe sarebbero già sbagliati domani); HNSW si aggiorna a ogni insert.
-- vector_cosine_ops = stessa metrica dell'operatore <=> usato nelle query: con un'altra metrica
-- l'indice verrebbe ignorato. m/ef_construction ai default; ef_search si regola a query time.
-- Con pochi candidati dopo i filtri relazionali il planner continua a preferire la ricerca esatta.
CREATE INDEX IF NOT EXISTS ix_interventions_embedding ON interventions USING hnsw (embedding vector_cosine_ops);

-- Catalogo dei documenti caricati: cosa esiste per ogni modello e se è già interrogabile.
-- Lo scrive la Function App (subscription `catalog` del topic e change feed di Cosmos), lo legge l'API.
-- I chunk restano su Cosmos: qui c'è una riga per documento, interrogabile con SQL e JOIN sugli impianti.
CREATE TABLE IF NOT EXISTS documents (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Percorso nel container `documents`: identifica il file. Ricaricarlo aggiorna la riga, non la duplica.
    blob_path     text NOT NULL UNIQUE,
    domain        text NOT NULL,
    manufacturer  text NOT NULL,
    model         text NOT NULL,
    doc_type      text NOT NULL,
    file_name     text NOT NULL,
    size_bytes    bigint,
    attributes    jsonb NOT NULL DEFAULT '{}',
    -- Due date scritte da due flussi indipendenti, al posto di una colonna `status`: l'ordine in cui
    -- arrivano gli eventi non conta e nessun messaggio in ritardo può far tornare indietro lo stato.
    uploaded_at   timestamptz,
    indexed_at    timestamptz
);
-- "Quali manuali ha questo modello?": la domanda che l'API fa per ogni impianto.
CREATE INDEX IF NOT EXISTS ix_documents_model ON documents (domain, manufacturer, model);

CREATE OR REPLACE VIEW documents_status AS
SELECT d.*,
       CASE
           WHEN d.indexed_at IS NOT NULL AND (d.uploaded_at IS NULL OR d.indexed_at >= d.uploaded_at) THEN 'indicizzato'
           ELSE 'in indicizzazione'
       END AS status
FROM documents d;
