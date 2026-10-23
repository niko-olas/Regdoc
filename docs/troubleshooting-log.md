# Troubleshooting log

Problemi incontrati e risolti su RegDoc, dal più recente al più vecchio.
Formato di una voce:

```
## AAAA-MM-GG — Titolo breve

**Sintomo**: che cosa si osservava (errore, comportamento, metrica).
**Diagnosi**: comandi az/kubectl o query KQL usati per restringere il campo.
**Causa**: la causa reale.
**Soluzione**: che cosa l'ha risolto, e che cosa evita che si ripresenti.
**Skill**: skill AI-200 collegata (vedi ai200-skills.md).
```

---

## 2026-10-23 — Fonti non pertinenti nella risposta

**Sintomo**: a una domanda sull'impostazione di data e ora l'elenco delle fonti mostrava quattro interventi di
guasto (display, depressione, sonda fumi), mentre il testo citava solo due pagine del manuale.
**Diagnosi**: distanze misurate su otto domande con `fielddata.search` e `api.retrieval`: guasti pertinenti sotto
0,40, domande estranee sopra 0,45.
**Causa**: la ricerca restituisce sempre i k candidati più vicini e l'API mostrava le fonti recuperate, non citate.
**Soluzione**: fonti filtrate sulle citazioni del testo; soglia di distanza sugli interventi in App Configuration;
versione del formato nella chiave della cache, così le risposte salvate prima non vengono più servite.
**Skill**: PostgreSQL (vector search, RAG); App Configuration.

## 2026-10-23 — Deploy Bicep ripetuto: amministratore PostgreSQL "already exists"

**Sintomo**: `AadAuthPrincipalCreationFailed: role "…" already exists` sulla risorsa `administrators`, dal secondo
deploy in poi.
**Diagnosi**: `az postgres flexible-server microsoft-entra-admin list` mostrava un nome lungo esattamente 63 caratteri.
**Causa**: l'UPN di un utente ospite (`…#EXT#@…onmicrosoft.com`) supera il limite di 63 caratteri dei nomi di
ruolo PostgreSQL e viene troncato; al deploy successivo Azure cerca il nome intero e prova a ricrearlo.
**Soluzione**: parametro `configurePostgresAdmin`, che `up.ps1` mette a false quando l'amministratore esiste già.
**Skill**: PostgreSQL (autenticazione Entra ID).

## 2026-10-23 — Deploy Bicep: container vettoriale rifiutato da Cosmos DB

**Sintomo**: `A Container Vector Policy has been provided, but the capability has not been enabled on your account`
alla creazione del container `chunks`; con la capability aggiunta al Bicep, l'errore restava.
**Diagnosi**: `az cosmosdb show --query capabilities[].name` → solo `EnableServerless`, anche dopo un deploy riuscito.
**Causa**: mancava `EnableNoSQLVectorSearch`; e le capability si applicano solo alla creazione dell'account: un
deploy su un account esistente le ignora senza errori.
**Soluzione**: capability nel Bicep per gli account nuovi; per quelli esistenti `up.ps1` esegue
`az cosmosdb update --capabilities EnableServerless EnableNoSQLVectorSearch` e ritenta mentre si attiva.
**Skill**: Cosmos DB for NoSQL (vector search).

## 2026-10-23 — Bench pgvector: recall di HNSW più bassa del previsto

**Sintomo**: recall@10 di HNSW tra 0,48 e 0,91 su 20.000 vettori, contro 1,00 di IVFFlat con `probes=4`.
**Diagnosi**: `SELECT count(DISTINCT embedding::text) FROM interventions` → 28 su 184: i dati di esempio ripetono le
stesse frasi, e il bench ne genera migliaia di copie quasi identiche.
**Causa**: dati sintetici a cluster stretti e isolati: la ground truth per id è ambigua e il grafo HNSW ha pochi
collegamenti tra i cluster.
**Soluzione**: aggiunta al bench la metrica `+dist` (quanto sono più lontani i risultati rispetto ai veri vicini);
scelta dell'indice motivata dal comportamento sui dati reali, da rimisurare quando ci saranno.
**Skill**: PostgreSQL (strategie di indicizzazione per pgvector).

## 2026-10-23 — PostgreSQL Flexible Server: RegionalAllocationFailed e nome "occupato" in un'altra regione

**Sintomo**: `az postgres flexible-server create --sku-name Standard_B1ms` in swedencentral fallisce con
`RegionalAllocationFailed: We do not have sufficient capacity for the requested compute size in this region`.
Riprovando lo stesso nome in northeurope: `InvalidResourceLocation: The resource already exists in location 'swedencentral'`.
**Diagnosi**: `az postgres flexible-server show` → `ResourceNotFound`: la risorsa non esiste, ma ARM tiene il nome
legato alla regione del tentativo fallito. Tentativi con `--zone 1`, `2`, `3` in swedencentral: tutti `RegionalAllocationFailed`.
**Causa**: capacità fisica esaurita per lo SKU Burstable B1ms in tutte le zone della regione (non un problema di quota).
**Soluzione**: server creato in northeurope con un nome diverso (`psql-regdoc-<suffisso>-ne`).
Capacity → cambiare zona, SKU o regione; quota (`QuotaExceeded`) → richiesta di aumento.
**Skill**: Azure Database for PostgreSQL — dimensionamento di compute, memoria e storage.

## 2026-10-23 — Event subscription con managed identity: "does not have authorization to deliver to the endpoint"

**Sintomo**: `az eventgrid event-subscription create --delivery-identity systemassigned` verso una coda Storage
fallisce con `Managed Identity Authorization Error`.
**Diagnosi**: `az role assignment list --assignee <principal-id-del-topic> --all` → ruoli presenti ma con scope sulla
singola coda e sul singolo container di dead-letter.
**Causa**: Event Grid valida i permessi alla creazione della subscription e si aspetta *Storage Queue Data Message Sender*
e *Storage Blob Data Contributor* (dead-letter) sullo **storage account**.
**Soluzione**: ruoli assegnati con scope sullo storage account; subscription creata al primo tentativo.
Per il minimo privilegio in produzione: storage account dedicato a code e dead-letter.
**Skill**: Event Grid — workflow event-driven (dead-letter, retry); sicurezza con managed identity.

## 2026-10-23 — Custom topic Event Grid senza identità dopo la disattivazione delle chiavi

**Sintomo**: `az eventgrid topic show --query identity.principalId` vuoto; `identity.type = None`, anche se il topic
era stato creato con `--mi-system-assigned`.
**Diagnosi**: `az monitor activity-log list --resource-id <topic-id>` → ultima modifica: la PATCH su `disableLocalAuth`.
**Causa**: probabile perdita dell'identità con la PATCH (o mancata applicazione alla creazione); non verificata subito.
**Soluzione**: `az rest --method patch` con corpo `{"identity": {"type": "SystemAssigned"}}`, poi verifica di
`identity.type`, `identity.principalId` e `disableLocalAuth` insieme. Dopo ogni modifica, verificare tutte le proprietà
che contano, non solo quella cambiata.
**Skill**: Event Grid; sicurezza con managed identity.

## 2026-10-23 — `az resource update` su un topic Event Grid: "Endpoint is a read-only property"

**Sintomo**: `az resource update --set properties.disableLocalAuth=true` su `Microsoft.EventGrid/topics` fallisce con
`InvalidRequest: Endpoint is a read-only property and should not be present`.
**Diagnosi**: `az resource update` esegue GET + PUT dell'intera risorsa, includendo le proprietà read-only restituite dalla GET.
**Causa**: il resource provider di Event Grid rifiuta le proprietà read-only nel corpo del PUT (Cosmos DB e Cognitive
Services invece le ignorano).
**Soluzione**: `az rest --method patch --url https://management.azure.com<resource-id>?api-version=2022-06-15`
con corpo `{"properties": {"disableLocalAuth": true}}`.
**Skill**: Event Grid; sicurezza (autenticazione solo Entra ID).

## 2026-10-23 — Trigger Cosmos DB senza invocazioni, lease container vuoto

**Sintomo**: dopo il deploy di `on_chunks_changed` e una reindicizzazione, la scheda *Invocations* è vuota.
**Diagnosi**: `az cosmosdb sql role assignment list` → nessun ruolo per l'identità della Function App; conteggio dei
documenti in `leases` = 0; query KQL sugli errori dell'host:
`traces | where timestamp > ago(1h) | where severityLevel >= 3 or message has "lease" | order by timestamp desc`.
**Causa**: senza ruoli data plane nativi il change feed processor non può leggere `chunks` né scrivere in `leases`:
il trigger non parte, quindi non ci sono invocazioni.
**Soluzione**: *Cosmos DB Built-in Data Reader* su `/dbs/regdoc/colls/chunks`, *Data Contributor* su
`/dbs/regdoc/colls/leases`, *EventGrid Data Sender* sul topic; restart della Function App; nuovo upload
(al primo avvio il trigger legge solo le modifiche successive).
**Skill**: Cosmos DB — change feed processor; Azure Functions.

## 2026-10-21 — ServiceBusConnectionError: getaddrinfo failed

**Sintomo**: la Function in locale fallisce all'invio con `ServiceBusConnectionError ... [Errno 11001] getaddrinfo failed`.
**Diagnosi**: lettura di `SERVICEBUS_FQDN` da `local.settings.json` → valore ancora `sb-regdoc-<suffisso>...`.
**Causa**: segnaposto non sostituito; il valore corretto era stato scritto nel file `.example`, che l'host non legge.
Il nome host non si risolve via DNS.
**Soluzione**: valore corretto in `local.settings.json` e riavvio di `func start` (le impostazioni si leggono solo
all'avvio). Distinguere: DNS (`getaddrinfo`) ≠ porta chiusa (`connection refused`) ≠ permessi (`401/403`).
**Skill**: Service Bus — operazioni back-end con code e topic; Azure Functions.

## 2026-10-21 — func start: errore sul Blob Storage Secret Repository

**Sintomo**: `func start` si ferma con "There was an error performing a read operation on the Blob Storage Secret
Repository ... (127.0.0.1:10000) connection refused".
**Diagnosi**: la porta 10000 è quella del Blob service di Azurite; nessun processo in ascolto.
**Causa**: Azurite non avviato. L'host Functions legge le proprie chiavi (incluse quelle del webhook Event Grid) dallo
storage di `AzureWebJobsStorage`, anche se il codice non usa lo storage.
**Soluzione**: avviare Azurite (VS Code → "Azurite: Start") prima di `func start`.
**Skill**: Azure Functions — configurazione e deploy di function app.

## 2026-10-19 — App Service: ImagePullUnauthorizedFailure da ACR

**Sintomo**: la web app non parte; nei log `LastError: ImagePullUnauthorizedFailure ... Image pull failed with forbidden or unauthorized`.
**Diagnosi**: `az webapp log config --docker-container-logging filesystem` + `az webapp log tail`.
**Causa**: ACR ha l'admin user disabilitato e la web app non aveva né identità né permessi sul registry.
**Soluzione**: system-assigned identity sulla web app, ruolo `AcrPull` con scope sul registry,
`acrUseManagedIdentityCreds=true` nella config del sito, restart. Impostato anche `WEBSITES_PORT=8000`.
**Skill**: Soluzioni containerizzate — deploy di container su App Service, ACR.

## 2026-10-19 — `az acr create` fallisce con MissingSubscriptionRegistration

**Sintomo**: `az acr create` restituisce `MissingSubscriptionRegistration` per il namespace `Microsoft.ContainerRegistry`.
**Diagnosi**: `az provider show -n Microsoft.ContainerRegistry --query registrationState -o tsv` → `NotRegistered`.
**Causa**: su una subscription nuova i resource provider non sono registrati; il portale li registra in automatico, la CLI no.
**Soluzione**: `az provider register -n Microsoft.ContainerRegistry`, attesa fino a `Registered` (operazione asincrona),
poi nuovo `az acr create`. Per le fasi successive i provider vengono registrati in anticipo.
**Skill**: Soluzioni containerizzate — creare e gestire immagini con Azure Container Registry.

## 2026-10-19 — `az login` non trova subscription (MFA richiesta dal tenant)

**Sintomo**: `az login` termina con `AADSTS50076 ... you must use multi-factor authentication` sul tenant
`<tenant-id>` e poi `No subscriptions found`.
**Diagnosi**: l'errore arriva in fase di "Retrieving tenants and subscriptions": il token iniziale non ha il claim MFA,
quindi l'acquisizione silenziosa del token per il tenant fallisce e la CLI salta il tenant.
**Causa**: il tenant impone l'MFA; il login senza tenant esplicito non la richiede in modo interattivo.
**Soluzione**: `az login --tenant <tenant-id>` (in alternativa `--use-device-code`, oppure
`az config set core.enable_broker_on_windows=false` se il broker WAM non mostra il prompt). Verifica con `az account list -o table`.
**Skill**: autenticazione / identità (prerequisito per `DefaultAzureCredential` in locale).
