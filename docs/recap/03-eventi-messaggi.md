# Recap 03 — Soluzioni basate su eventi e messaggi

Dominio d'esame: **3. Connessione e utilizzo dei servizi Azure (20–25%)** → *Soluzioni basate su eventi e messaggi*.
Svolto il 2026-10-19/21 (F1). Componenti: storage `documents`, Event Grid, Service Bus, Function `src/ingestion`, consumer `src/audit`.

| Skill | Stato |
|---|---|
| Service Bus: messaggi, topic, subscription, dead-letter queue | ☑ completata |
| Event Grid: filtri, eventi custom, retry | ◐ filtri e retry fatti — **da completare**: dead-letter di Event Grid ed eventi custom (F2, change feed di Cosmos) |

Il flusso costruito:

```
upload PDF → Storage (system topic) → Event Grid (filtri) → Function → topic "documents"
                                                                        ├─ indexer → worker (F2)
                                                                        └─ audit   → consumer audit (log)
```

---

## 1. Evento o messaggio?

| | Evento (Event Grid) | Messaggio (Service Bus) |
|---|---|---|
| Che cos'è | notifica: "è successo X" | lavoro da fare, con il payload completo |
| Il mittente si aspetta qualcosa? | no | sì, che venga elaborato |
| Consegna | push agli iscritti | pull: il consumer lo preleva quando è pronto |
| Ricevente fermo | retry per un tempo limitato, poi scarta o dead-letter | il messaggio aspetta in coda |

| Scenario | Servizio |
|---|---|
| Reagire a un fatto accaduto (upload, creazione di risorse) | **Event Grid** |
| Lavoro affidabile, ordinato, con transazioni e dead-letter | **Service Bus** |
| Telemetria ad alto volume (IoT, log, milioni di eventi/s) | **Event Hubs** |

In RegDoc si usano entrambi: Event Grid **segnala** l'upload, Service Bus **conserva** il lavoro finché il worker non è pronto.

## 2. Event Grid

- **System topic**: eventi di una risorsa Azure (qui lo storage). Uno per risorsa. **Custom topic**: eventi pubblicati dal proprio codice. **Domain**: insieme di topic (multi-tenant).
- **Event subscription**: tipo di eventi + filtri + destinazione (handler) + retry policy.
- **Handler**: Function, webhook, coda o topic Service Bus, coda Storage, Event Hubs.
- **Filtri**: tipo di evento, `subject` (begins/ends with), filtri avanzati sui campi (`data.*`). Scartano gli eventi **prima** della consegna.
- **Retry**: backoff esponenziale; default 30 tentativi / 24 h, qui `--max-delivery-attempts 10 --event-ttl 120`. Poi l'evento è perso, a meno di una **dead-letter su container blob** (da fare).
- **At-least-once**: lo stesso evento può arrivare più volte → serve idempotenza a valle.
- **Schema**: Event Grid schema o CloudEvents 1.0. Il corpo è sempre un **array** di eventi.
- **BlobCreated** scatta anche alla sovrascrittura di un blob.
- **Metriche** per il troubleshooting: `PublishSuccessCount` → `MatchedEventCount` → `DeliverySuccessCount` / `DeliveryAttemptFailCount`.

```powershell
az eventgrid topic-type list-event-types --name Microsoft.Storage.StorageAccounts --query "[].name" -o tsv
az monitor metrics list --resource $EG_TOPIC_ID --metric PublishSuccessCount MatchedEventCount DeliverySuccessCount DeliveryAttemptFailCount `
  --aggregation Total --interval PT1H --offset 2h -o table
```

## 3. Service Bus: struttura

```
Namespace (Standard, disableLocalAuth)
└── Topic documents (duplicate detection 10 min)
    ├── Subscription indexer (lock 1 min, max delivery 5, DLQ alla scadenza)
    └── Subscription audit   (lock 30 s, max delivery 3, DLQ alla scadenza)
```

- **Tier**: Basic = solo code, niente topic né duplicate detection. Standard = topic, subscription, filtri. Premium = risorse dedicate, VNet, messaggi fino a 100 MB.
- **Coda**: ogni messaggio a un solo consumatore. **Topic + subscription**: ogni subscription riceve una **copia** (fan-out). Un consumatore nuovo = una subscription nuova, senza toccare il mittente.
- **Il topic non conserva messaggi**: si leggono dalle subscription.
- **`disableLocalAuth`**: niente SAS key / connection string → solo Entra ID + RBAC.
- **Ruoli di data plane**: *Azure Service Bus Data Sender*, *Data Receiver*, *Data Owner*. Owner/Contributor della risorsa non bastano per inviare o ricevere.
- **Filtri delle subscription**: regola `$Default` (TrueFilter); SQL filter sulle proprietà; correlation filter (uguaglianza, più efficiente).

```powershell
az servicebus namespace create --resource-group $RG --name $SB_NAMESPACE --location $LOCATION --sku Standard --disable-local-auth true
az servicebus topic create --resource-group $RG --namespace-name $SB_NAMESPACE --name documents `
  --enable-duplicate-detection true --duplicate-detection-history-time-window PT10M
az servicebus topic subscription create --resource-group $RG --namespace-name $SB_NAMESPACE --topic-name documents `
  --name audit --lock-duration PT30S --max-delivery-count 3 --enable-dead-lettering-on-message-expiration true
```

## 4. Service Bus: il messaggio

- **Corpo** JSON + **proprietà di sistema** (`MessageId`, `ContentType`, `EnqueuedTimeUtc`, `DeliveryCount`, `SequenceNumber`) + **proprietà applicative** (qui `domain`, `doc_type`, utili per i filtri).
- **Duplicate detection**: scarta i messaggi con un `MessageId` già visto nella finestra (20 s – 7 giorni). Funziona solo se il **mittente** usa un `MessageId` **deterministico**: qui `MessageId = id dell'evento Event Grid`. Senza, l'SDK genera un id casuale e la deduplicazione non serve a nulla.
- Verificato: stesso evento inviato due volte → contatori invariati, nessun errore.

## 5. Ricezione e settlement

| Operazione | Effetto |
|---|---|
| **Peek** | legge senza lock e senza modificare nulla (diagnosi) |
| **Receive, PeekLock** (default) | blocca il messaggio per la *lock duration* |
| `complete` | cancella il messaggio |
| `abandon` | rilascia il lock subito, `DeliveryCount + 1`, riconsegna **immediata** |
| `dead_letter` | sposta in DLQ con `reason` e `error_description` |
| `defer` | mette da parte, si recupera con il sequence number |
| Lock scaduto | come abandon, ma dopo la lock duration |
| **ReceiveAndDelete** | cancella alla consegna: più veloce, ma un crash perde il messaggio |

- `delivery_count` nell'SDK **Python** conta i tentativi **falliti precedenti** (0 alla prima consegna); l'SDK .NET parte da 1.
- Le subscription sono **indipendenti**: completare in `audit` non tocca la copia in `indexer` (verificato: audit 0, indexer 2).

## 6. Dead-letter queue

- Sotto-coda di ogni coda e subscription: `<entità>/$DeadLetterQueue`. I messaggi **non scadono** e **non vengono riprovati**: vanno letti, analizzati, scartati o ri-sottomessi.
- Come ci si arriva:
  1. dead-letter **esplicito** dal codice;
  2. `MaxDeliveryCountExceeded` (troppi tentativi);
  3. `TTLExpiredException` (scadenza, se attivo dead-lettering on expiration);
  4. errori nella valutazione dei filtri (se attivato).

Verificato nella DLQ di `audit`:

| | Corpo non JSON | Valido + guasto simulato |
|---|---|---|
| Chi lo sposta | il codice (`dead_letter_message`) | Service Bus |
| Reason | `InvalidMessage` | `MaxDeliveryCountExceeded` |
| DeliveryCount | 0 | 3 |

**Regola**: errore **permanente** (il messaggio è sbagliato) → dead-letter esplicito subito. Errore **transitorio** (il problema è fuori dal messaggio) → abandon, e il max delivery count ferma il loop. Un backoff tra i tentativi va implementato nel consumer.

## 7. Strumenti usati

```powershell
# contatori, compresa la DLQ
az servicebus topic subscription list --resource-group $RG --namespace-name $SB_NAMESPACE --topic-name documents `
  --query "[].{name:name, attivi:countDetails.activeMessageCount, deadLetter:countDetails.deadLetterMessageCount}" -o table

# peek, anche della DLQ (richiede Data Receiver)
src\audit\.venv\Scripts\python.exe infra\scripts\peek_subscription.py $SB_NAMESPACE audit --dlq

# messaggi di prova: valid | invalid (richiede Data Sender)
src\audit\.venv\Scripts\python.exe infra\scripts\send_test_message.py $SB_NAMESPACE invalid

# consumer audit, da src/ (AUDIT_SIMULATE_FAILURE=1 per provare l'abandon)
$env:SERVICEBUS_FQDN = "$SB_NAMESPACE.servicebus.windows.net"
audit\.venv\Scripts\python.exe -m audit.main
```

Dal portale: subscription → **Service Bus Explorer** → *Peek Mode* (non Receive Mode), *Active* o *Dead-lettered*.

---

## Da completare (F2)

- **Dead-letter di Event Grid** su container blob, con managed identity del system topic.
- **Eventi custom**: il change feed di Cosmos pubblicherà un evento su un custom topic Event Grid.
- I 4 messaggi di test accumulati in `indexer` (tra cui uno non JSON) saranno il primo banco di prova del worker.

## Trappole d'esame

| Situazione | Risposta |
|---|---|
| Servono topic o duplicate detection | almeno **Standard** |
| Più consumatori devono ricevere ogni messaggio | topic + una subscription per consumatore |
| Consumatore che riceve solo un sottoinsieme | filtro sulla subscription (SQL o correlation) |
| Messaggi duplicati nonostante la duplicate detection | `MessageId` non deterministico, oppure fuori finestra |
| Messaggio che fallisce sempre e blocca risorse | max delivery count → DLQ; meglio dead-letter esplicito se l'errore è riconoscibile |
| Messaggi in DLQ "spariti"? | non scadono: restano finché non vengono letti |
| Inviare con Entra ID su namespace con local auth disabilitata | ruolo *Azure Service Bus Data Sender* |
| Evento consegnato più volte | at-least-once di Event Grid → idempotenza a valle |
| Eventi irrilevanti che arrivano alla Function | filtri sulla event subscription |
| Event Grid non riesce a consegnare per ore | retry fino a TTL / max tentativi, poi dead-letter su blob (se configurata) |

## Domande di ripasso

1. Evento o messaggio: come classifichi "un manuale è stato caricato" e "indicizza questo manuale"?
2. Perché RegDoc usa un topic con due subscription invece di una coda o di due code?
3. Perché il tier Basic non basta?
4. Che cosa serve perché la duplicate detection funzioni davvero? Che cosa c'entra Event Grid?
5. Differenza tra peek, receive + complete e ReceiveAndDelete?
6. Che cosa succede a un messaggio se il consumer va in crash dopo la ricezione ma prima del complete?
7. Quali sono i quattro modi in cui un messaggio finisce in DLQ? Quali due hai visto?
8. Perché un errore di parsing va in dead-letter subito, mentre un errore di rete viene riprovato?
9. Quali metriche di Event Grid guardi se la Function non viene invocata?
