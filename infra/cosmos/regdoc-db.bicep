// Database e container dei chunk su un account Cosmos DB for NoSQL già esistente.
// Deploy (lo esegue l'utente):
//   az deployment group create --resource-group <rg> --template-file infra/cosmos/regdoc-db.bicep --parameters accountName=<account>
//
// Perché Bicep e non `az cosmosdb sql container create`: la CLI non espone in modo affidabile
// le partition key gerarchiche (MultiHash); il template descrive il container in un colpo solo.

@description('Nome dell\'account Cosmos DB for NoSQL esistente (serverless).')
param accountName string

param databaseName string = 'regdoc'
param containerName string = 'chunks'

@description('Dimensioni del vettore: devono coincidere con il modello di embedding (text-embedding-3-small = 1536).')
param embeddingDimensions int = 1536

resource account 'Microsoft.DocumentDB/databaseAccounts@2025-04-15' existing = {
  name: accountName
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2025-04-15' = {
  parent: account
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
    // Nessun throughput: l'account è serverless, si paga per RU consumata.
  }
}

resource chunks 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2025-04-15' = {
  parent: database
  name: containerName
  properties: {
    resource: {
      id: containerName

      // Partition key gerarchica domain → document_id.
      // - Le query RAG filtrano per dominio: con domain come primo livello vengono instradate
      //   solo alle partizioni di quel dominio, non a tutte (niente fan-out completo).
      // - Tutti i chunk di un documento stanno nella stessa partizione logica (domain + document_id):
      //   reindicizzare un documento significa leggere e riscrivere una sola partizione.
      // - Un dominio può superare i 20 GB del limite per partizione logica, perché la partizione
      //   logica è la coppia completa, non il solo dominio.
      partitionKey: {
        paths: [
          '/domain'
          '/document_id'
        ]
        kind: 'MultiHash'
        version: 2
      }

      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          { path: '/*' }
        ]
        // Ogni path indicizzato costa RU a ogni scrittura. L'embedding (1536 numeri) e il testo
        // del chunk non si filtrano mai con WHERE: escluderli dall'indice range riduce il costo
        // delle scritture. Il vettore ha il suo indice dedicato (vectorIndexes).
        excludedPaths: [
          { path: '/"_etag"/?' }
          { path: '/embedding/*' }
          { path: '/text/?' }
        ]
        // quantizedFlat: ricerca esaustiva su vettori compressi, consigliata fino a ~50.000 vettori
        // per query, tanto più se la query filtra per partition key. diskANN conviene oltre.
        // Sotto i 1.000 vettori Cosmos fa comunque una scansione completa.
        vectorIndexes: [
          {
            path: '/embedding'
            type: 'quantizedFlat'
          }
        ]
      }

      // La policy vettoriale non si può modificare dopo la creazione: dimensioni e distanza
      // vanno scelte insieme al modello di embedding.
      vectorEmbeddingPolicy: {
        vectorEmbeddings: [
          {
            path: '/embedding'
            dataType: 'float32'
            distanceFunction: 'cosine'
            dimensions: embeddingDimensions
          }
        ]
      }
    }
  }
}

// Lease container del change feed processor (trigger Cosmos DB di Azure Functions):
// un documento "segnalibro" per ogni intervallo di partizioni letto. Va creato qui perché
// con l'RBAC nativo di Cosmos (Entra ID) il trigger non può creare container da solo.
// Partition key /id: è quella richiesta per i lease container.
resource leases 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2025-04-15' = {
  parent: database
  name: 'leases'
  properties: {
    resource: {
      id: 'leases'
      partitionKey: {
        paths: [
          '/id'
        ]
        kind: 'Hash'
      }
    }
  }
}

output containerId string = chunks.id
