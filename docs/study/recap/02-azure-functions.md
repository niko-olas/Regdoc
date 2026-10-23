# Recap 02 — Azure Functions

Dominio d'esame: **3. Connessione e utilizzo dei servizi Azure (20–25%)** → *Azure Functions*.
Completato il 2026-10-21. Componente: `src/ingestion` — Function che riceve l'evento `BlobCreated` da Event Grid e pubblica un messaggio sul topic Service Bus `documents`.

| Skill | Come è stata coperta |
|---|---|
| API serverless con trigger e binding | Trigger Event Grid (modello v2 Python), SDK al posto dell'output binding, test in locale con evento simulato |
| Configurazione e deploy di function app | Flex Consumption, storage dell'host con managed identity, ruoli RBAC con scope minimo, app settings, `func azure functionapp publish` |

Prerequisiti già pronti da F1: storage `documents`, Service Bus con topic `documents` e subscription `indexer`/`catalog` (vedi il recap di messaging).

---

## 1. Cosa fa la Function

```
Event Grid ──POST──► host Functions ──► on_blob_created ──► Service Bus topic "documents"
                                          │
                                          ├─ parse_subject: percorso → domain/manufacturer/model/doc_type/file
                                          ├─ get_blob_properties: metadati x-ms-meta-* (non sono nell'evento)
                                          └─ ServiceBusMessage(body JSON, message_id=event.id, application_properties)
```

- **Errore permanente** (percorso fuori schema): warning nei log e `return` → l'invocazione è *Succeeded*, Event Grid non ritenta.
- **Errore transitorio** (Service Bus irraggiungibile): eccezione propagata → invocazione fallita → Event Grid ritenta.
- `MessageId = event.id` rende il messaggio **deterministico**: la duplicate detection del topic scarta le riconsegne di Event Grid (at-least-once).
- Client e credenziale creati **una volta per istanza** e riusati; il sender Service Bus non è thread-safe → `threading.Lock`.

## 2. Modello di programmazione

- **Python v2**: trigger e binding si dichiarano con decoratori (`@app.event_grid_trigger(arg_name="event")`), non con `function.json` (modello v1).
- **Trigger** = cosa fa partire la funzione (uno solo per funzione). **Binding** di input/output = dati letti o scritti in modo dichiarativo.
- **Output binding Service Bus vs SDK**: in Python il binding accetta solo il body; per `MessageId`, proprietà applicative, sessioni o batch serve l'SDK `azure-servicebus`.
- **Trigger Event Grid** = webhook HTTP esposto dall'host su `/runtime/webhooks/EventGrid?functionName=...`. Il corpo è sempre un **array** di eventi; l'header `aeg-event-type: Notification` distingue gli eventi dalla *validation handshake*.
- `azure-functions` 2.x richiede Python ≥ 3.13: con Python 3.12 si resta su 1.x.

## 3. Sviluppo locale

```powershell
cd src\ingestion
py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item local.settings.example.json local.settings.json   # e poi compilarlo
func start                                                    # Azurite deve essere avviato
.\scripts\tools\send-test-event.ps1                           # da un secondo terminale
```

- **Functions Core Tools** (`func`) esegue l'host in locale. **Azurite** emula lo storage dell'host (`UseDevelopmentStorage=true`).
- `local.settings.json` = app settings locali (sezione `Values`), mai committato né pubblicato. Letto **solo all'avvio**.
- In locale `DefaultAzureCredential` usa il login di `az`: i ruoli di data plane servono **all'utente** (es. *Azure Service Bus Data Sender*).

## 4. Host e storage dell'host

- L'**host** è il runtime che riceve gli eventi, chiama il codice, gestisce log, chiavi e scaling.
- **`AzureWebJobsStorage`** è obbligatorio per ogni Function App: chiavi (`azure-webjobs-secrets`), lock/lease tra istanze (`azure-webjobs-hosts`), pacchetto di deploy su Flex, eventi diagnostici (tabelle).
- Storage dell'host **separato** da quello dei dati: l'host vuole *Storage Blob Data Owner*, ai documenti basta *Reader*.

## 5. Piani di hosting

| Piano | Scala a zero | Cold start | Note |
|---|---|---|---|
| **Flex Consumption** | sì | ridotto, istanze *always ready* opzionali | VNet, managed identity completa, piano consigliato |
| Consumption (legacy) | sì | sì | timeout max 10 min; Python 3.12 è l'ultima versione su Linux |
| Premium (Elastic) | no | no (istanze pre-riscaldate) | VNet, esecuzioni lunghe |
| Dedicated (App Service) | no | no (con *Always On*) | paghi la macchina |

- **Scala a zero**: nessuna istanza attiva quando non arrivano eventi → nessun costo.
- **Cold start**: ritardo del primo evento dopo inattività (alloca istanza, scarica pacchetto, avvia host e Python). Accettabile per l'ingestion, non per un'API interattiva.
- `--maximum-instance-count`: tetto allo scaling (costi, connessioni verso i servizi a valle).

## 6. Creazione e configurazione su Azure

```powershell
az functionapp create --resource-group $RG --name $FUNCAPP --storage-account $FUNC_STORAGE `
  --flexconsumption-location $LOCATION --runtime python --runtime-version 3.12 `
  --maximum-instance-count 10 --deployment-storage-auth-type SystemAssignedIdentity
```

- La CLI crea l'identità system-assigned e le dà *Storage Blob Data Contributor* sullo storage di deploy.
- **Sorpresa**: anche con le chiavi disattivate sullo storage, la CLI scrive `AzureWebJobsStorage` come connection string **con `AccountKey`**. Non funzionerebbe ed è un segreto in configurazione → va sostituita:

```powershell
az functionapp config appsettings delete --resource-group $RG --name $FUNCAPP --setting-names AzureWebJobsStorage
az functionapp config appsettings set --resource-group $RG --name $FUNCAPP --settings `
  "AzureWebJobsStorage__accountName=$FUNC_STORAGE" "SERVICEBUS_FQDN=<namespace>.servicebus.windows.net" "SERVICEBUS_TOPIC=documents"
```

- Il **doppio underscore** `__` = proprietà annidata (`AzureWebJobsStorage:accountName`). Solo il nome dell'account, nessuna chiave → l'host usa la managed identity.

### Ruoli dell'identità della Function

| Ruolo | Scope | Perché |
|---|---|---|
| Storage Blob Data Owner | storage dell'host | minimo richiesto per `AzureWebJobsStorage` |
| Storage Table Data Contributor | storage dell'host | eventi diagnostici dell'host |
| Storage Blob Data Contributor | storage dell'host | download del pacchetto (assegnato dalla CLI) |
| Storage Blob Data Reader | **solo il container** `documents` | lettura dei metadati |
| Azure Service Bus Data Sender | **solo il topic** `documents` | invio dei messaggi |

Scope come sotto-risorsa: `.../storageAccounts/<sa>/blobServices/default/containers/documents`, `.../namespaces/<ns>/topics/documents`. Il ruolo vale per lo scope e tutto ciò che sta sotto.

### Deploy

```powershell
cd src\ingestion
func azure functionapp publish $FUNCAPP
```

Zip della cartella (meno `.funcignore`), caricato nel container di deploy, **build remota** su Linux che installa `requirements.txt`.

## 7. Collegamento con Event Grid

```powershell
az eventgrid system-topic create --resource-group $RG --name $EG_TOPIC --location $LOCATION `
  --topic-type Microsoft.Storage.StorageAccounts --source $STORAGE_ID
az eventgrid system-topic event-subscription create --resource-group $RG --system-topic-name $EG_TOPIC `
  --name to-ingest-function --endpoint-type azurefunction --endpoint "$FUNC_ID/functions/on_blob_created" `
  --included-event-types Microsoft.Storage.BlobCreated `
  --subject-begins-with /blobServices/default/containers/documents/blobs/ --subject-ends-with .pdf `
  --max-delivery-attempts 10 --event-ttl 120
```

- `--endpoint-type azurefunction` + ID della funzione: Event Grid gestisce da solo la chiave del webhook.
- I filtri scartano gli eventi **prima** della consegna: un `.txt` non invoca la Function (e non costa).

## 8. Monitoraggio

| Dove | Cosa mostra |
|---|---|
| Funzione → **Logs** | log stream in tempo reale, solo da quando ci si collega |
| Funzione → **Invocations** | storico delle esecuzioni con i loro log (ritardo 2–5 min) |
| Function App → **Monitoring → Logs** | KQL su Application Insights (`traces`, `requests`, `exceptions`) |
| Event Grid → metriche | `PublishSuccessCount`, `MatchedEventCount`, `DeliverySuccessCount`, `DeliveryAttemptFailCount` |

```kusto
traces
| where timestamp > ago(1h)
| where message has "ignorato" or message has "Pubblicato"
| project timestamp, severityLevel, message
| order by timestamp desc
```

---

## Errori incontrati

| Sintomo | Causa | Lezione |
|---|---|---|
| `ParserError: Token imprevisto 'eventType'` | hashtable PowerShell incollata su una riga sola | blocchi lunghi in uno script `.ps1` |
| `connection refused` su `localhost:7071` | host Functions non in esecuzione | è un sintomo: guardare il terminale di `func start` |
| *Blob Storage Secret Repository* … `127.0.0.1:10000` | Azurite spento | l'host ha sempre bisogno del suo storage |
| `ServiceBusConnectionError: getaddrinfo failed` | segnaposto nel FQDN / valore messo nel file `.example` | errore DNS ≠ porta chiusa ≠ permessi; settings lette solo all'avvio |
| `MissingSubscription` su `az role assignment create` | `$STORAGE_ID` vuota → scope senza `/subscriptions/...` | stampare le variabili calcolate prima di usarle |
| `--resource-group: expected one argument` | variabili non caricate nel terminale nuovo | `. .\scripts\env.ps1` a ogni terminale |

## Trappole d'esame

| Situazione | Risposta |
|---|---|
| Function App senza storage account | Impossibile: `AzureWebJobsStorage` è sempre richiesto dall'host |
| Storage dell'host con managed identity | `AzureWebJobsStorage__accountName` + *Storage Blob Data Owner* |
| Impostare `MessageId` o proprietà custom da Python | SDK, non output binding |
| Latenza critica, nessun cold start, VNet | Premium, oppure Flex con istanze always ready |
| Traffico sporadico, costo minimo | Flex Consumption |
| Errore permanente nell'elaborazione di un evento | Non sollevare eccezioni (log + return), altrimenti retry inutili |
| App setting modificata | L'app si riavvia; `local.settings.json` letto solo all'avvio |
| Log mancanti sotto carico | Sampling di Application Insights (`host.json`) |
| La funzione non viene invocata | Metriche Event Grid: `MatchedEventCount` (filtri) e `DeliverySuccessCount` / `DeliveryAttemptFailCount` |

## Domande di ripasso

1. Perché la Function non usa l'output binding Service Bus?
2. Che cosa salva l'host in `AzureWebJobsStorage`, e perché lo storage dell'host è separato da quello dei documenti?
3. Che cosa succede a `on_blob_created` se il percorso del blob è sbagliato? E se Service Bus non risponde? Perché i due casi sono gestiti in modo diverso?
4. Che differenza c'è tra Flex Consumption e Premium per scaling e cold start?
5. Che significa il doppio underscore in `AzureWebJobsStorage__accountName`?
6. Perché la connection string scritta da `az functionapp create` non avrebbe funzionato?
7. Su quale scope hai assegnato *Storage Blob Data Reader*, e perché non sull'intero storage account?
8. Un `.txt` caricato in `documents` invoca la Function? Dove lo verifichi?
9. Dove guardi i log di un'esecuzione di ieri? E quelli di un'esecuzione che stai per lanciare?
