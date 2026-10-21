# AI-200 — Skills misurate e mappa su RegDoc

Fonti ufficiali (da ricontrollare periodicamente, l'esame è nuovo e i contenuti si stanno ancora assestando):
- Pagina certificazione: https://learn.microsoft.com/en-us/credentials/certifications/azure-ai-cloud-developer-associate/
- Study guide: https://learn.microsoft.com/en-us/credentials/certifications/resources/study-guides/ai-200
- Skills misurate aggiornate al 15 aprile 2026 (study guide aggiornato il 5 maggio 2026). Sintesi rielaborata, non testo ufficiale.

## Info sull'esame

- Certificazione: Microsoft Certified: Azure AI Cloud Developer Associate, livello Intermediate, ruolo Developer.
- Esame AI-200, "Developing AI Cloud Solutions on Azure".
- Durata 120 minuti, proctored, possibili componenti interattive.
- Punteggio minimo 700/1000.
- Disponibile anche in italiano. Se si sostiene in una lingua non ancora aggiornata, si possono chiedere 30 minuti extra.
- Practice assessment ufficiale non ancora disponibile; c'è l'exam sandbox per provare l'interfaccia.
- Registrarsi con un account Microsoft personale (MSA), non aziendale.
- Rinnovo annuale gratuito tramite assessment online su Microsoft Learn.
- Domande quasi sempre su funzionalità GA; le preview possono uscire solo se molto usate.
- I link di formazione dello study guide rimandano ancora ai learning path di AZ-204.

## Profilo del candidato

Sviluppatore che partecipa a tutto il ciclo di vita di soluzioni AI su Azure (requisiti, design, sviluppo, deploy, sicurezza, monitoraggio), con focus sul back-end. Competenze attese:
- SDK Azure e SDK di terze parti usati su Azure
- servizi Azure di data management
- monitoring e troubleshooting su Azure
- messaging ed eventing
- database vettoriali
- Python
- applicazioni containerizzate su Azure

## Fasi di RegDoc (riferimento)

- **F1** — Ingestion: Blob Storage, Event Grid, Azure Function, Service Bus
- **F2** — Worker su Container Apps (KEDA), ACR, Cosmos DB con vettori e change feed
- **F3** — PostgreSQL con pgvector, Azure Managed Redis
- **F4** — API di query su App Service (container) e su AKS
- **F5** — Trasversale: Key Vault, App Configuration, OpenTelemetry, KQL

---

## 1. Soluzioni containerizzate su Azure (20–25%)

### Hosting di applicazioni container
| Skill | Fase | Fatto |
|---|---|---|
| Creare, archiviare, versionare e gestire immagini con Azure Container Registry | F2 | ☑ |
| Build ed esecuzione di immagini con ACR Tasks | F2 | ☑ |
| Deploy di container su App Service, con env vars e secret forniti dalla configurazione di App Service | F4 | ☑ |

### Soluzioni orchestrate
| Skill | Fase | Fatto |
|---|---|---|
| Deploy su Azure Container Apps: configurazione dell'environment e gestione delle revisioni | F2 | ☐ |
| Scaling event-driven con KEDA in Container Apps | F2 | ☐ |
| Deploy e gestione su AKS tramite file manifest | F4 | ☐ |
| Monitoraggio e troubleshooting su AKS e Container Apps: log, eventi, connettività end-to-end | F2, F4 | ☐ |

## 2. Soluzioni AI con i servizi di data management (25–30%)

### Azure Cosmos DB for NoSQL
| Skill | Fase | Fatto |
|---|---|---|
| Connessione tramite SDK ed esecuzione di query | F2 | ☐ |
| Ottimizzazione di performance e consumo di RU con indexing policy e consistency level | F2 | ☐ |
| Salvataggio e lettura di embedding, vector similarity search per retrieval semantico | F2 | ☐ |
| Change feed processor per reagire a item nuovi o modificati | F2 | ☐ |

### Azure Database for PostgreSQL
| Skill | Fase | Fatto |
|---|---|---|
| Connessione e query tramite SDK | F3 | ☐ |
| Modellazione dello schema: design delle tabelle e scelta dei tipi di dato | F3 | ☐ |
| Strategie di indicizzazione: ridurre la latenza delle query e il carico computazionale di pgvector | F3 | ☐ |
| Dimensionamento di compute, memoria e storage per workload vettoriali | F3 | ☐ |
| Vector search: embedding, retrieval semantico e pattern RAG con filtri sui metadati | F3 | ☐ |
| Ottimizzazione delle connessioni per throughput e latenza | F3 | ☐ |

### Azure Managed Redis
| Skill | Fase | Fatto |
|---|---|---|
| Operazioni sui dati: caching, expiration, invalidazione | F3 | ☐ |
| Indicizzazione vettoriale per similarity search | F3 | ☐ |

## 3. Connessione e utilizzo dei servizi Azure (20–25%)

### Soluzioni basate su eventi e messaggi
| Skill | Fase | Fatto |
|---|---|---|
| Service Bus per operazioni back-end in coda: messaggi, topic, subscription, dead-letter queue | F1 | ☑ |
| Workflow event-driven con Event Grid: filtri, eventi custom, retry | F1, F2 | ◐ filtri e retry fatti; mancano dead-letter ed eventi custom (F2) |

### Azure Functions
| Skill | Fase | Fatto |
|---|---|---|
| API serverless con trigger e binding | F1 | ☑ |
| Configurazione e deploy di function app | F1 | ☑ |

## 4. Sicurezza, monitoraggio e troubleshooting (20–25%)

### Sicurezza
| Skill | Fase | Fatto |
|---|---|---|
| Gestione dei secret con Key Vault, incluse rotazione e lettura | F5 | ☐ |
| Configurazione applicativa con Azure App Configuration | F5 | ☐ |

### Monitoraggio e troubleshooting
| Skill | Fase | Fatto |
|---|---|---|
| Tracing di sistemi distribuiti con gli SDK OpenTelemetry | F5 | ☐ |
| Query KQL per analizzare log e metriche | F5 | ☐ |

---

## Note personali

(Spazio per appunti, dubbi e concetti da ripassare, da aggiornare durante il progetto.)
