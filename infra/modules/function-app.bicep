// Function App Python su Flex Consumption, con il suo piano e il suo storage "di servizio".
// Modulo di infra/main.bicep, usato due volte: ingest (on_blob_created) e catalog (catalogo e change feed).
//
// Un piano e uno storage per app. Flex Consumption ammette una sola app per piano; uno storage condiviso
// darebbe a ogni identità Blob Owner sulle chiavi dell'host e sui pacchetti di deploy dell'altra app,
// e con nomi uguali nei primi 32 caratteri le due app entrerebbero in conflitto sull'host ID.

@description('Nome della Function App.')
param name string

@description('Storage dell\'host (chiavi, lease dei trigger, pacchetti di deploy): 3-24 caratteri, minuscole e numeri.')
param storageName string

param planName string
param location string

@description('Application Insights: identifica la risorsa, non è un segreto; l\'invio si autentica con Entra ID.')
param appInsightsConnectionString string

@description('App settings dell\'app, oltre a storage dell\'host e Application Insights.')
param appSettings array

@description('Istanze massime dell\'app (1-1000).')
@minValue(1)
@maxValue(1000)
param maximumInstanceCount int

var roles = {
  blobOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  tableContributor: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
}

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

resource packages 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: blobService
  name: 'app-package'
}

resource plan 'Microsoft.Web/serverfarms@2024-11-01' = {
  name: planName
  location: location
  kind: 'functionapp'
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  properties: { reserved: true }
}

resource site 'Microsoft.Web/sites@2024-11-01' = {
  name: name
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}${packages.name}'
          authentication: { type: 'SystemAssignedIdentity' }
        }
      }
      scaleAndConcurrency: { maximumInstanceCount: maximumInstanceCount, instanceMemoryMB: 2048 }
      runtime: { name: 'python', version: '3.12' }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      appSettings: concat([
        // Storage dell'host con identità: nessuna connection string.
        { name: 'AzureWebJobsStorage__accountName', value: storage.name }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
        { name: 'APPLICATIONINSIGHTS_AUTHENTICATION_STRING', value: 'Authorization=AAD' }
      ], appSettings)
    }
  }
}

// L'host usa il proprio storage per chiavi, lease e pacchetti: ruoli solo su questo account.
resource hostBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, site.id, roles.blobOwner)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobOwner)
    principalId: site.identity.principalId
    principalType: 'ServicePrincipal'
  }
}
resource hostTable 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, site.id, roles.tableContributor)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.tableContributor)
    principalId: site.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output id string = site.id
output name string = site.name
output principalId string = site.identity.principalId
