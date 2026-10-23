# Simula la consegna di un evento BlobCreated di Event Grid alla Function in locale.
# Prerequisiti: func start in src/ingestion e variabili caricate con . .\scripts\env.ps1
#
# Uso:
#   .\scripts\tools\send-test-event.ps1                      # nuovo id evento
#   .\scripts\tools\send-test-event.ps1 -EventId <id>        # stesso id: prova la duplicate detection
param(
    [string]$BlobPath = "stufe-pellet/edilkamin/blade-h/uso-manutenzione/prova.pdf",
    [string]$EventId = [guid]::NewGuid().ToString()
)

if (-not $STORAGE) { throw "Variabili non caricate: esegui prima . .\scripts\env.ps1" }

# Event Grid invia sempre un array di eventi, anche quando ce n'è uno solo.
$events = @(
    @{
        id              = $EventId
        eventType       = "Microsoft.Storage.BlobCreated"
        subject         = "/blobServices/default/containers/documents/blobs/$BlobPath"
        eventTime       = (Get-Date).ToUniversalTime().ToString("o")
        topic           = "/subscriptions/x/resourceGroups/$RG/providers/Microsoft.Storage/storageAccounts/$STORAGE"
        dataVersion     = ""
        metadataVersion = "1"
        data            = @{
            url         = "https://$STORAGE.blob.core.windows.net/documents/$BlobPath"
            contentType = "application/pdf"
        }
    }
)

# L'header aeg-event-type distingue una notifica dalla validation handshake
# che Event Grid esegue quando si crea la event subscription.
Invoke-RestMethod -Method Post `
    -Uri "http://localhost:7071/runtime/webhooks/EventGrid?functionName=on_blob_created" `
    -Headers @{ "aeg-event-type" = "Notification" } `
    -ContentType "application/json" `
    -Body (ConvertTo-Json -InputObject $events -Depth 5)

Write-Host "Evento inviato, id: $EventId"
