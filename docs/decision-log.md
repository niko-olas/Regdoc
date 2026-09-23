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

## 2026-09-23 — Scrittura su entrambi gli store, feature flag solo in lettura

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
