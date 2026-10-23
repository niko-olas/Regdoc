// RegDoc: tutta l'infrastruttura in un file. Pensato per ricreare l'ambiente da zero dopo
// `az group delete` (costi a zero tra una sessione e l'altra). Lo usa scripts/deploy/up.ps1, in due passate:
//   1. deployWorkloads=false: tutto tranne ciò che richiede immagini o codice già pubblicati
//   2. deployWorkloads=true:  worker su Container Apps e sottoscrizioni Event Grid
// Nessun segreto e nessun ID personale nel file: utente e IP arrivano come parametri al deploy.

targetScope = 'resourceGroup'

@description('Suffisso dei nomi globali (storage, cosmos, ...).')
param suffix string

param location string = 'swedencentral'

@description('PostgreSQL in un\'altra regione: in swedencentral il tier Burstable non aveva capacità (RegionalAllocationFailed).')
param postgresLocation string = 'northeurope'

@description('Object ID del tuo utente Entra: ruoli di sviluppo e amministratore di PostgreSQL.')
param userObjectId string

@description('UPN del tuo utente Entra: è il nome del ruolo amministratore in PostgreSQL.')
param userPrincipalName string

@description('IP pubblico da cui lavori, per il firewall di PostgreSQL. Vuoto = nessuna regola.')
param clientIpAddress string = ''

param apiImageTag string = '2.2.0'
param workerImageTag string = '0.2.0'

@description('Seconda passata: richiede le immagini in ACR e la Function già pubblicata.')
param deployWorkloads bool = false

@description('Crea l\'amministratore Entra di PostgreSQL. Va a false se esiste già: con un UPN oltre i 63 caratteri (utenti ospite #EXT#) il nome del ruolo viene troncato e la risorsa non è ridistribuibile.')
param configurePostgresAdmin bool = true

// --- Nomi ---------------------------------------------------------------------------------------
var acrName = 'acrregdoc${suffix}'
var storageName = 'stregdoc${suffix}'
var funcStorageName = 'stregdocfn${suffix}'
var sbName = 'sb-regdoc-${suffix}'
var cosmosName = 'cosmos-regdoc-${suffix}'
var foundryName = 'ais-regdoc-${suffix}'
var pgName = 'psql-regdoc-${suffix}-ne'
var redisName = 'redis-regdoc-${suffix}'
var appConfigName = 'appcs-regdoc-${suffix}'
var webAppName = 'app-regdoc-api-${suffix}'
var funcAppName = 'func-regdoc-ingest-${suffix}'
var egCustomTopicName = 'evgt-regdoc-indexed-${suffix}'

// Ruoli built-in (ID uguali in ogni tenant).
var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  blobContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  blobOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  blobReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
  tableContributor: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
  queueContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
  queueSender: 'c6a89b2d-59bc-44d0-9896-0f6e12d7b80a'
  sbSender: '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
  sbReceiver: '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'
  sbOwner: '090c5cfd-751d-490a-894a-3ce6f1109419'
  openAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  egSender: 'd5a91429-5739-47e2-a06b-3470a27159e7'
  appConfigReader: '516239f1-63e1-4d78-a4de-a74fb236a071'
  appConfigOwner: '5ae67dd6-50cb-40e7-96ff-dc2bfa4b606b'
  metricsPublisher: '3913510d-42f4-4e42-8a64-420c390055eb'
}
// Ruoli di data plane di Cosmos DB (RBAC nativo, non Azure RBAC).
var cosmosReader = '00000000-0000-0000-0000-000000000001'
var cosmosContributor = '00000000-0000-0000-0000-000000000002'

func roleId(id string) string => subscriptionResourceId('Microsoft.Authorization/roleDefinitions', id)

// --- Monitoraggio -------------------------------------------------------------------------------
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-regdoc-dev'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// Un solo Application Insights per API, Function e worker: le distingue cloud_RoleName.
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-regdoc-dev'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
    // Solo Entra ID per l'invio della telemetria (ruolo Monitoring Metrics Publisher).
    DisableLocalAuth: true
  }
}

// --- Container registry -------------------------------------------------------------------------
resource acr 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
  }
}

// --- Storage dei documenti (F1) ------------------------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: storageName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    accessTier: 'Hot'
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: storage
  name: 'default'
}

resource documentsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: blobService
  name: 'documents'
}

resource deadletterContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: blobService
  name: 'eventgrid-deadletter'
}

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2025-01-01' = {
  parent: storage
  name: 'default'
}

resource indexedQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2025-01-01' = {
  parent: queueService
  name: 'indexed-events'
}

// --- Service Bus (F1) ---------------------------------------------------------------------------
resource sb 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
  name: sbName
  location: location
  sku: { name: 'Standard', tier: 'Standard' } // Standard: i topic non esistono nel tier Basic
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
  }
}

resource sbTopic 'Microsoft.ServiceBus/namespaces/topics@2024-01-01' = {
  parent: sb
  name: 'documents'
  properties: {
    // MessageId = id dell'evento Event Grid: un evento consegnato due volte diventa un solo messaggio.
    requiresDuplicateDetection: true
    duplicateDetectionHistoryTimeWindow: 'PT10M'
    supportOrdering: true
    maxSizeInMegabytes: 1024
  }
}

resource sbIndexer 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = {
  parent: sbTopic
  name: 'indexer'
  properties: {
    // Lock più lungo del catalogo: l'indicizzazione di un PDF dura decine di secondi (il worker lo rinnova).
    lockDuration: 'PT1M'
    maxDeliveryCount: 5
    deadLetteringOnMessageExpiration: true
    deadLetteringOnFilterEvaluationExceptions: true
  }
}

// Secondo consumatore dello stesso topic (fan-out): registra ogni documento nel catalogo su PostgreSQL.
resource sbCatalog 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = {
  parent: sbTopic
  name: 'catalog'
  properties: {
    lockDuration: 'PT30S'
    maxDeliveryCount: 3
    deadLetteringOnMessageExpiration: true
    deadLetteringOnFilterEvaluationExceptions: true
  }
}

// --- Cosmos DB (F2) -----------------------------------------------------------------------------
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2025-04-15' = {
  name: cosmosName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    // EnableNoSQLVectorSearch: senza, Cosmos rifiuta i container con vectorEmbeddingPolicy.
    // Le capability valgono solo alla CREAZIONE: su un account esistente un deploy le ignora e
    // serve `az cosmosdb update --capabilities` (lo fa up.ps1).
    capabilities: [ { name: 'EnableServerless' }, { name: 'EnableNoSQLVectorSearch' } ]
    // Session: ogni client legge le proprie scritture, al costo di RU più basso dopo Eventual.
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [ { locationName: location, failoverPriority: 0, isZoneRedundant: false } ]
    disableLocalAuth: true
    minimalTlsVersion: 'Tls12'
  }
}

module cosmosDb 'modules/cosmos-db.bicep' = {
  name: 'cosmos-regdoc-db'
  params: { accountName: cosmos.name }
}

// --- Foundry (F2-F4) ----------------------------------------------------------------------------
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: foundryName
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: foundryName // obbligatorio per l'autenticazione Entra ID
    disableLocalAuth: true
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: 'text-embedding-3-small'
  sku: { name: 'DataZoneStandard', capacity: 50 }
  properties: {
    model: { format: 'OpenAI', name: 'text-embedding-3-small', version: '1' }
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: 'gpt-4.1-mini'
  sku: { name: 'DataZoneStandard', capacity: 50 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4.1-mini', version: '2025-04-14' }
  }
  dependsOn: [ embeddingDeployment ] // i deployment dello stesso account vanno creati uno alla volta
}

// --- PostgreSQL (F3) ----------------------------------------------------------------------------
resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: pgName
  location: postgresLocation
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '17'
    storage: { storageSizeGB: 32, autoGrow: 'Enabled' }
    // Solo Entra ID: nessuna password da custodire.
    authConfig: { activeDirectoryAuth: 'Enabled', passwordAuth: 'Disabled', tenantId: tenant().tenantId }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
  }
}

resource pgAdmin 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-08-01' = if (configurePostgresAdmin) {
  parent: pg
  name: userObjectId
  properties: {
    principalType: 'User'
    principalName: userPrincipalName
    tenantId: tenant().tenantId
  }
}

// Le estensioni vanno autorizzate a livello di server prima di CREATE EXTENSION.
resource pgExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: pg
  name: 'azure.extensions'
  properties: { value: 'VECTOR', source: 'user-override' }
  dependsOn: [ pgAdmin ] // PostgreSQL accetta un'operazione alla volta sul server
}

resource pgDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: pg
  name: 'regdoc'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
  dependsOn: [ pgExtensions ]
}

// 0.0.0.0 = "consenti i servizi Azure": l'IP in uscita di App Service non è fisso.
resource pgAllowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: pg
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
  dependsOn: [ pgDatabase ]
}

resource pgAllowClient 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = if (!empty(clientIpAddress)) {
  parent: pg
  name: 'AllowClientIp'
  properties: { startIpAddress: clientIpAddress, endIpAddress: clientIpAddress }
  dependsOn: [ pgAllowAzure ]
}

// --- Azure Managed Redis (F3) -------------------------------------------------------------------
resource redis 'Microsoft.Cache/redisEnterprise@2025-07-01' = {
  name: redisName
  location: location
  sku: { name: 'Balanced_B0' }
  properties: {
    minimumTlsVersion: '1.2'
    highAvailability: 'Disabled' // sviluppo: dati non replicati, costo dimezzato
    publicNetworkAccess: 'Enabled'
  }
}

resource redisDb 'Microsoft.Cache/redisEnterprise/databases@2025-07-01' = {
  parent: redis
  name: 'default'
  properties: {
    clientProtocol: 'Encrypted'
    port: 10000
    // RediSearch (indice vettoriale della cache semantica) si aggiunge solo alla creazione e
    // richiede EnterpriseCluster + NoEviction.
    clusteringPolicy: 'EnterpriseCluster'
    evictionPolicy: 'NoEviction'
    modules: [ { name: 'RediSearch' } ]
    accessKeysAuthentication: 'Disabled'
  }
}

// --- App Configuration (F5) ---------------------------------------------------------------------
resource appConfig 'Microsoft.AppConfiguration/configurationStores@2024-05-01' = {
  name: appConfigName
  location: location
  sku: { name: 'free' }
  properties: {
    disableLocalAuth: true
  }
}

// --- Identità del worker (F2) -------------------------------------------------------------------
// User-assigned: esiste prima della Container App, quindi AcrPull è già valido al primo pull.
resource workerId 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: 'id-regdoc-worker'
  location: location
}

// Identità separata per KEDA: Data Owner serve solo a leggere la lunghezza della coda.
resource scalerId 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: 'id-regdoc-scaler'
  location: location
}

// --- Function App di ingestion (F1-F3) ----------------------------------------------------------
resource funcStorage 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: funcStorageName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    accessTier: 'Hot'
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource funcBlobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: funcStorage
  name: 'default'
}

resource funcPackages 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: funcBlobService
  name: 'app-package'
}

resource funcPlan 'Microsoft.Web/serverfarms@2024-11-01' = {
  name: 'plan-regdoc-func'
  location: location
  kind: 'functionapp'
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  properties: { reserved: true }
}

resource funcApp 'Microsoft.Web/sites@2024-11-01' = {
  name: funcAppName
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: funcPlan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${funcStorage.properties.primaryEndpoints.blob}app-package'
          authentication: { type: 'SystemAssignedIdentity' }
        }
      }
      scaleAndConcurrency: { maximumInstanceCount: 10, instanceMemoryMB: 2048 }
      runtime: { name: 'python', version: '3.12' }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      appSettings: [
        // Storage dell'host con identità: nessuna connection string.
        { name: 'AzureWebJobsStorage__accountName', value: funcStorage.name }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'APPLICATIONINSIGHTS_AUTHENTICATION_STRING', value: 'Authorization=AAD' }
        { name: 'SERVICEBUS_FQDN', value: '${sb.name}.servicebus.windows.net' }
        { name: 'SERVICEBUS_TOPIC', value: sbTopic.name }
        // Trigger Service Bus con identità: il suffisso __fullyQualifiedNamespace sostituisce la connection string.
        { name: 'ServiceBusConnection__fullyQualifiedNamespace', value: '${sb.name}.servicebus.windows.net' }
        { name: 'PGHOST', value: pg.properties.fullyQualifiedDomainName }
        // Ruolo PostgreSQL della managed identity: può scrivere solo il catalogo (grant_app_role.py catalog).
        { name: 'PGUSER', value: funcAppName }
        { name: 'CosmosDB__accountEndpoint', value: cosmos.properties.documentEndpoint }
        { name: 'EVENTGRID_TOPIC_ENDPOINT', value: egCustomTopic.properties.endpoint }
        { name: 'REDIS_HOST', value: redis.properties.hostName }
      ]
    }
  }
}

// --- Event Grid ----------------------------------------------------------------------------------
resource egSystemTopic 'Microsoft.EventGrid/systemTopics@2025-02-15' = {
  name: 'evgt-regdoc-documents'
  location: location
  properties: {
    source: storage.id
    topicType: 'Microsoft.Storage.StorageAccounts'
  }
}

// Seconda passata: Event Grid verifica che la funzione esista già (codice pubblicato).
resource egToFunction 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2025-02-15' = if (deployWorkloads) {
  parent: egSystemTopic
  name: 'to-ingest-function'
  properties: {
    destination: {
      endpointType: 'AzureFunction'
      properties: {
        resourceId: '${funcApp.id}/functions/on_blob_created'
        maxEventsPerBatch: 1
        preferredBatchSizeInKilobytes: 64
      }
    }
    eventDeliverySchema: 'EventGridSchema'
    // Solo PDF caricati nel container documents: niente eventi per altri file o container.
    filter: {
      includedEventTypes: [ 'Microsoft.Storage.BlobCreated' ]
      subjectBeginsWith: '/blobServices/default/containers/documents/blobs/'
      subjectEndsWith: '.pdf'
    }
    retryPolicy: { maxDeliveryAttempts: 10, eventTimeToLiveInMinutes: 120 }
  }
}

resource egCustomTopic 'Microsoft.EventGrid/topics@2025-02-15' = {
  name: egCustomTopicName
  location: location
  identity: { type: 'SystemAssigned' } // consegna e dead-letter verso lo storage con la propria identità
  properties: {
    inputSchema: 'CloudEventSchemaV1_0'
    disableLocalAuth: true
    dataResidencyBoundary: 'WithinGeopair'
    publicNetworkAccess: 'Enabled'
  }
}

// Seconda passata: Event Grid valida i ruoli della sua identità alla creazione, e l'RBAC appena
// assegnato nella prima passata ha avuto il tempo di propagarsi.
resource egToQueue 'Microsoft.EventGrid/topics/eventSubscriptions@2025-02-15' = if (deployWorkloads) {
  parent: egCustomTopic
  name: 'to-indexed-queue'
  properties: {
    eventDeliverySchema: 'CloudEventSchemaV1_0'
    filter: { includedEventTypes: [ 'RegDoc.Document.Indexed' ] }
    retryPolicy: { maxDeliveryAttempts: 5, eventTimeToLiveInMinutes: 60 }
    deliveryWithResourceIdentity: {
      identity: { type: 'SystemAssigned' }
      destination: {
        endpointType: 'StorageQueue'
        properties: { resourceId: storage.id, queueName: indexedQueue.name }
      }
    }
    deadLetterWithResourceIdentity: {
      identity: { type: 'SystemAssigned' }
      deadLetterDestination: {
        endpointType: 'StorageBlob'
        properties: { resourceId: storage.id, blobContainerName: deadletterContainer.name }
      }
    }
  }
}

// --- Container Apps: worker di indicizzazione (F2) ------------------------------------------------
resource acaEnv 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: 'cae-regdoc-dev'
  location: location
  properties: {
    workloadProfiles: [ { name: 'Consumption', workloadProfileType: 'Consumption' } ]
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

resource worker 'Microsoft.App/containerApps@2025-01-01' = if (deployWorkloads) {
  name: 'ca-regdoc-worker'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${workerId.id}': {}, '${scalerId.id}': {} }
  }
  properties: {
    environmentId: acaEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [ { server: acr.properties.loginServer, identity: workerId.id } ]
    }
    template: {
      containers: [
        {
          name: 'ca-regdoc-worker'
          image: '${acr.properties.loginServer}/regdoc-worker:${workerImageTag}'
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            // Con più identità sull'app, DefaultAzureCredential deve sapere quale usare.
            { name: 'AZURE_CLIENT_ID', value: workerId.properties.clientId }
            { name: 'SERVICEBUS_FQDN', value: '${sb.name}.servicebus.windows.net' }
            { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
            { name: 'FOUNDRY_ENDPOINT', value: foundry.properties.endpoint }
          ]
        }
      ]
      scale: {
        // Scale to zero senza messaggi; una replica ogni 5 messaggi in attesa, massimo 5.
        minReplicas: 0
        maxReplicas: 5
        pollingInterval: 30
        cooldownPeriod: 300
        rules: [
          {
            name: 'indexer-backlog'
            custom: {
              type: 'azure-servicebus'
              identity: scalerId.id
              metadata: {
                namespace: sb.name
                topicName: sbTopic.name
                subscriptionName: sbIndexer.name
                messageCount: '5'
              }
            }
          }
        ]
      }
    }
  }
  dependsOn: [ workerAcrPull ]
}

// --- Web App dell'API (F4) ----------------------------------------------------------------------
resource webPlan 'Microsoft.Web/serverfarms@2024-11-01' = {
  name: 'plan-regdoc-dev'
  location: location
  kind: 'linux'
  sku: { name: 'B1', tier: 'Basic' }
  properties: { reserved: true }
}

resource webApp 'Microsoft.Web/sites@2024-11-01' = {
  name: webAppName
  location: location
  kind: 'app,linux,container'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: webPlan.id
    httpsOnly: true
    clientAffinityEnabled: false // API senza stato: nessun bisogno di "sticky session"
    siteConfig: {
      // Se l'immagine non c'è ancora, App Service ritenta il pull: non blocca il deploy.
      linuxFxVersion: 'DOCKER|${acr.properties.loginServer}/regdoc-api:${apiImageTag}'
      acrUseManagedIdentityCreds: true
      healthCheckPath: '/health'
      alwaysOn: true
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      appSettings: [
        { name: 'WEBSITES_PORT', value: '8000' }
        { name: 'WEBSITES_ENABLE_APP_SERVICE_STORAGE', value: 'false' }
        { name: 'APP_ENV', value: 'dev' }
        { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
        { name: 'FOUNDRY_ENDPOINT', value: foundry.properties.endpoint }
        { name: 'CHAT_DEPLOYMENT', value: chatDeployment.name }
        { name: 'PGHOST', value: pg.properties.fullyQualifiedDomainName }
        // Il ruolo PostgreSQL della managed identity porta il nome della web app (grant_app_role.py).
        { name: 'PGUSER', value: webAppName }
        { name: 'PG_POOL_MAX', value: '5' }
        { name: 'REDIS_HOST', value: redis.properties.hostName }
        { name: 'APPCONFIG_ENDPOINT', value: appConfig.properties.endpoint }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
      ]
    }
  }
}

// --- Ruoli (Azure RBAC) --------------------------------------------------------------------------
// Ogni identità ha solo ciò che le serve, sull'ambito più stretto possibile.

// Web App
resource webAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, webApp.id, roles.acrPull)
  scope: acr
  properties: { roleDefinitionId: roleId(roles.acrPull), principalId: webApp.identity.principalId, principalType: 'ServicePrincipal' }
}
resource webOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, webApp.id, roles.openAiUser)
  scope: foundry
  properties: { roleDefinitionId: roleId(roles.openAiUser), principalId: webApp.identity.principalId, principalType: 'ServicePrincipal' }
}
resource webAppConfig 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appConfig.id, webApp.id, roles.appConfigReader)
  scope: appConfig
  properties: { roleDefinitionId: roleId(roles.appConfigReader), principalId: webApp.identity.principalId, principalType: 'ServicePrincipal' }
}
resource webMetrics 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appInsights.id, webApp.id, roles.metricsPublisher)
  scope: appInsights
  properties: { roleDefinitionId: roleId(roles.metricsPublisher), principalId: webApp.identity.principalId, principalType: 'ServicePrincipal' }
}

// Function App
resource funcHostBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(funcStorage.id, funcApp.id, roles.blobOwner)
  scope: funcStorage
  properties: { roleDefinitionId: roleId(roles.blobOwner), principalId: funcApp.identity.principalId, principalType: 'ServicePrincipal' }
}
resource funcHostTable 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(funcStorage.id, funcApp.id, roles.tableContributor)
  scope: funcStorage
  properties: { roleDefinitionId: roleId(roles.tableContributor), principalId: funcApp.identity.principalId, principalType: 'ServicePrincipal' }
}
resource funcDocsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(documentsContainer.id, funcApp.id, roles.blobReader)
  scope: documentsContainer
  properties: { roleDefinitionId: roleId(roles.blobReader), principalId: funcApp.identity.principalId, principalType: 'ServicePrincipal' }
}
resource funcSbCatalog 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sbCatalog.id, funcApp.id, roles.sbReceiver)
  scope: sbCatalog
  properties: { roleDefinitionId: roleId(roles.sbReceiver), principalId: funcApp.identity.principalId, principalType: 'ServicePrincipal' }
}
resource funcSbSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sbTopic.id, funcApp.id, roles.sbSender)
  scope: sbTopic
  properties: { roleDefinitionId: roleId(roles.sbSender), principalId: funcApp.identity.principalId, principalType: 'ServicePrincipal' }
}
resource funcEgSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(egCustomTopic.id, funcApp.id, roles.egSender)
  scope: egCustomTopic
  properties: { roleDefinitionId: roleId(roles.egSender), principalId: funcApp.identity.principalId, principalType: 'ServicePrincipal' }
}
resource funcMetrics 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appInsights.id, funcApp.id, roles.metricsPublisher)
  scope: appInsights
  properties: { roleDefinitionId: roleId(roles.metricsPublisher), principalId: funcApp.identity.principalId, principalType: 'ServicePrincipal' }
}

// Worker e scaler KEDA
resource workerAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, workerId.id, roles.acrPull)
  scope: acr
  properties: { roleDefinitionId: roleId(roles.acrPull), principalId: workerId.properties.principalId, principalType: 'ServicePrincipal' }
}
resource workerDocsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(documentsContainer.id, workerId.id, roles.blobReader)
  scope: documentsContainer
  properties: { roleDefinitionId: roleId(roles.blobReader), principalId: workerId.properties.principalId, principalType: 'ServicePrincipal' }
}
resource workerSbReceiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sbIndexer.id, workerId.id, roles.sbReceiver)
  scope: sbIndexer
  properties: { roleDefinitionId: roleId(roles.sbReceiver), principalId: workerId.properties.principalId, principalType: 'ServicePrincipal' }
}
resource workerOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, workerId.id, roles.openAiUser)
  scope: foundry
  properties: { roleDefinitionId: roleId(roles.openAiUser), principalId: workerId.properties.principalId, principalType: 'ServicePrincipal' }
}
resource scalerSbOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sbTopic.id, scalerId.id, roles.sbOwner)
  scope: sbTopic
  properties: { roleDefinitionId: roleId(roles.sbOwner), principalId: scalerId.properties.principalId, principalType: 'ServicePrincipal' }
}

// Topic custom di Event Grid: Event Grid verifica i ruoli a livello di storage account.
resource egQueueSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, egCustomTopic.id, roles.queueSender)
  scope: storage
  properties: { roleDefinitionId: roleId(roles.queueSender), principalId: egCustomTopic.identity.principalId, principalType: 'ServicePrincipal' }
}
resource egDeadletter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, egCustomTopic.id, roles.blobContributor)
  scope: storage
  properties: { roleDefinitionId: roleId(roles.blobContributor), principalId: egCustomTopic.identity.principalId, principalType: 'ServicePrincipal' }
}

// Tu: caricare documenti, leggere code, provare script e configurare i feature flag.
var userRoles = [
  { scope: 'storage', role: roles.blobContributor }
  { scope: 'storage', role: roles.queueContributor }
  { scope: 'sb', role: roles.sbSender }
  { scope: 'sb', role: roles.sbReceiver }
  { scope: 'foundry', role: roles.openAiUser }
  { scope: 'appConfig', role: roles.appConfigOwner }
]
resource userStorageRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for r in filter(userRoles, x => x.scope == 'storage'): {
  name: guid(storage.id, userObjectId, r.role)
  scope: storage
  properties: { roleDefinitionId: roleId(r.role), principalId: userObjectId, principalType: 'User' }
}]
resource userSbRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for r in filter(userRoles, x => x.scope == 'sb'): {
  name: guid(sb.id, userObjectId, r.role)
  scope: sb
  properties: { roleDefinitionId: roleId(r.role), principalId: userObjectId, principalType: 'User' }
}]
resource userOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, userObjectId, roles.openAiUser)
  scope: foundry
  properties: { roleDefinitionId: roleId(roles.openAiUser), principalId: userObjectId, principalType: 'User' }
}
resource userAppConfig 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appConfig.id, userObjectId, roles.appConfigOwner)
  scope: appConfig
  properties: { roleDefinitionId: roleId(roles.appConfigOwner), principalId: userObjectId, principalType: 'User' }
}

// --- Ruoli di data plane: Cosmos DB e Redis ------------------------------------------------------
// Cosmos: Built-in Data Reader (…0001) e Data Contributor (…0002) sul percorso più stretto possibile.
resource cosmosFuncLeases 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2025-04-15' = {
  parent: cosmos
  name: guid(cosmos.id, 'func', 'leases')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosContributor}' // segnalibri del change feed
    principalId: funcApp.identity.principalId
    scope: '${cosmos.id}/dbs/regdoc/colls/leases'
  }
  dependsOn: [ cosmosDb ]
}
resource cosmosFuncChunks 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2025-04-15' = {
  parent: cosmos
  name: guid(cosmos.id, 'func', 'chunks')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosReader}' // lettura del change feed
    principalId: funcApp.identity.principalId
    scope: '${cosmos.id}/dbs/regdoc/colls/chunks'
  }
  dependsOn: [ cosmosFuncLeases ] // Cosmos accetta una modifica RBAC alla volta
}
resource cosmosWorker 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2025-04-15' = {
  parent: cosmos
  name: guid(cosmos.id, 'worker', 'chunks')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosContributor}'
    principalId: workerId.properties.principalId
    scope: '${cosmos.id}/dbs/regdoc/colls/chunks'
  }
  dependsOn: [ cosmosFuncChunks ]
}
resource cosmosWeb 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2025-04-15' = {
  parent: cosmos
  name: guid(cosmos.id, 'webapp', 'chunks')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosReader}'
    principalId: webApp.identity.principalId
    scope: '${cosmos.id}/dbs/regdoc/colls/chunks'
  }
  dependsOn: [ cosmosWorker ]
}
resource cosmosUser 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2025-04-15' = {
  parent: cosmos
  name: guid(cosmos.id, 'user', 'regdoc')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosContributor}'
    principalId: userObjectId
    scope: '${cosmos.id}/dbs/regdoc'
  }
  dependsOn: [ cosmosWeb ]
}

// Redis: l'utente Redis è l'object ID dell'identità, con la policy "default" (tutti i comandi).
// Una modifica alla volta sullo stesso database, da qui la catena di dependsOn.
resource redisWeb 'Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2025-07-01' = {
  parent: redisDb
  name: 'webapp'
  properties: { accessPolicyName: 'default', user: { objectId: webApp.identity.principalId } }
}
resource redisFunc 'Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2025-07-01' = {
  parent: redisDb
  name: 'funcapp'
  properties: { accessPolicyName: 'default', user: { objectId: funcApp.identity.principalId } }
  dependsOn: [ redisWeb ]
}
resource redisUser 'Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2025-07-01' = {
  parent: redisDb
  name: 'me'
  properties: { accessPolicyName: 'default', user: { objectId: userObjectId } }
  dependsOn: [ redisFunc ]
}

// --- Output per gli script ------------------------------------------------------------------------
output acrName string = acr.name
output webAppName string = webApp.name
output webAppUrl string = 'https://${webApp.properties.defaultHostName}'
output funcAppName string = funcApp.name
output appConfigEndpoint string = appConfig.properties.endpoint
output pgHost string = pg.properties.fullyQualifiedDomainName
output storageName string = storage.name
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output foundryEndpoint string = foundry.properties.endpoint
