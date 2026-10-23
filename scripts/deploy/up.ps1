# Crea (o aggiorna) tutto l'ambiente RegDoc da zero: infrastruttura Bicep, immagini, Function,
# feature flag, database con i dati di esempio e manuale di prova.
#
# Uso, dalla radice del repo:
#   . .\scripts\env.ps1
#   .\scripts\deploy\up.ps1
#
# Idempotente: si può rilanciare dopo un errore, i passi già fatti non cambiano nulla.
# Tempo da zero: 30-40 minuti (Redis e PostgreSQL sono i più lenti).

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
if (-not $RG -or -not $ACR_NAME) { throw "Carica prima le variabili: . .\scripts\env.ps1" }

$SUFFIX     = $ACR_NAME -replace '^acrregdoc', ''
$API_TAG    = "2.2.0"
$WORKER_TAG = "0.2.0"
$ME_ID      = az ad signed-in-user show --query id -o tsv
$ME_UPN     = az ad signed-in-user show --query userPrincipalName -o tsv
# IP pubblico di questo PC, per il firewall di PostgreSQL (gli script locali si collegano da qui).
$MY_IP      = (Invoke-RestMethod "https://api.ipify.org").Trim()

function Step($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }

function Deploy-Bicep([string]$workloads) {
    # L'amministratore Entra di PostgreSQL si crea solo la prima volta (vedi il parametro nel Bicep).
    $pgAdmins = try { az postgres flexible-server microsoft-entra-admin list -g $RG -s $PG --query "[].principalType" -o tsv 2>$null } catch { $null }
    $configureAdmin = if ($pgAdmins) { "false" } else { "true" }
    az deployment group create -g $RG -n "regdoc-main" -f infra/main.bicep `
        -p suffix=$SUFFIX location=$LOCATION userObjectId=$ME_ID userPrincipalName=$ME_UPN `
           clientIpAddress=$MY_IP apiImageTag=$API_TAG workerImageTag=$WORKER_TAG deployWorkloads=$workloads `
           configurePostgresAdmin=$configureAdmin `
        --query "properties.outputs" -o json | ConvertFrom-Json
}

# Le capability di Cosmos si applicano solo alla creazione dell'account: se l'account esiste già
# senza ricerca vettoriale (es. creato da una versione precedente del Bicep), la si aggiunge qui.
function Ensure-CosmosVectorSearch {
    $caps = try { az cosmosdb show -g $RG -n $COSMOS --query "capabilities[].name" -o tsv 2>$null } catch { $null }
    if ($caps -and ($caps -notcontains "EnableNoSQLVectorSearch")) {
        Write-Host "  attivo la ricerca vettoriale sull'account Cosmos esistente (qualche minuto)"
        az cosmosdb update -g $RG -n $COSMOS --capabilities EnableServerless EnableNoSQLVectorSearch -o none
    }
}

# I ruoli appena assegnati impiegano qualche minuto a valere: riprova un comando finché non passa.
function Retry([scriptblock]$action, [string]$what, [int]$times = 12, [int]$seconds = 30) {
    for ($i = 1; $i -le $times; $i++) {
        try { & $action; return } catch {
            if ($i -eq $times) { throw }
            Write-Host "  $what non ancora possibile (modifiche in propagazione), riprovo tra $seconds s ($i/$times)"
            Start-Sleep -Seconds $seconds
        }
    }
}

Step "1/8 Resource group $RG"
az group create -n $RG -l $LOCATION -o none

Step "2/8 Infrastruttura (Bicep, prima passata)"
Ensure-CosmosVectorSearch
# Riprova: la capability appena attivata può richiedere qualche minuto prima che Cosmos accetti il container.
Retry { $script:out = Deploy-Bicep "false" } "Prima passata" 6 90
Write-Host "  ok"

Step "3/8 Immagini in ACR"
foreach ($img in @(@("regdoc-worker", $WORKER_TAG, "src/worker/Dockerfile"), @("regdoc-api", $API_TAG, "src/api/Dockerfile"))) {
    $name, $tag, $dockerfile = $img
    $tags = try { az acr repository show-tags -n $ACR_NAME --repository $name -o tsv 2>$null } catch { @() }
    if ($tags -notcontains $tag) {
        az acr build --registry $ACR_NAME --image "${name}:$tag" --build-arg APP_VERSION=$tag -f $dockerfile src/ -o none
    }
    Write-Host "  ${name}:$tag -> ok"
}

Step "4/8 Codice della Function"
Push-Location src/ingestion
try { Retry { func azure functionapp publish $out.funcAppName.value --python } "Pubblicazione della Function" }
finally { Pop-Location }

Step "5/8 Worker e sottoscrizioni Event Grid (Bicep, seconda passata)"
Retry { $script:out = Deploy-Bicep "true" } "Seconda passata" 6
Write-Host "  ok"

Step "6/8 Feature flag in App Configuration"
$ac = $out.appConfigEndpoint.value
Retry {
    az appconfig feature set --endpoint $ac --auth-mode login --feature use-interventions `
        --description "Usa gli interventi simili (PostgreSQL) nelle risposte" --yes -o none
    az appconfig feature enable --endpoint $ac --auth-mode login --feature use-interventions --yes -o none
    az appconfig feature set --endpoint $ac --auth-mode login --feature semantic-cache `
        --description "Cache semantica delle risposte su Redis" --yes -o none
    az appconfig feature enable --endpoint $ac --auth-mode login --feature semantic-cache --yes -o none
    az appconfig kv set --endpoint $ac --auth-mode login --key "RegDoc:Sentinel" --value "1" --yes -o none
} "Scrittura dei feature flag"
Write-Host "  use-interventions=on, semantic-cache=on"

Step "7/8 PostgreSQL: schema, ruoli di API e Function, dati di esempio"
$state = az postgres flexible-server show -g $RG -n $PG --query state -o tsv
if ($state -eq "Stopped") { az postgres flexible-server start -g $RG -n $PG -o none }
$env:PGHOST = $out.pgHost.value
$env:PGUSER = $ME_UPN
$env:FOUNDRY_ENDPOINT = $out.foundryEndpoint.value
Retry { .venv\Scripts\python.exe scripts\db\apply_schema.py } "Schema PostgreSQL"
.venv\Scripts\python.exe scripts\db\grant_app_role.py $out.webAppName.value api
.venv\Scripts\python.exe scripts\db\grant_app_role.py $out.funcAppName.value catalog
Retry { .venv\Scripts\python.exe scripts\db\import_field_data.py } "Import dei dati (embedding)"

Step "8/8 Manuale di prova e riavvio dell'API"
$blob = "stufe-pellet/extraflame/karolina/manuale-utente/extraflame_karolina_manuale_utente.pdf"
$exists = az storage blob exists --account-name $out.storageName.value -c documents -n $blob --auth-mode login --query exists -o tsv
if ($exists -ne "true" -and (Test-Path samples\Extraflame_Karolina_Manuale_Utente.pdf)) {
    # Il caricamento avvia la pipeline: Event Grid → Function → Service Bus → worker → Cosmos.
    Retry { az storage blob upload --account-name $out.storageName.value -c documents -n $blob `
        -f samples\Extraflame_Karolina_Manuale_Utente.pdf --auth-mode login -o none } "Caricamento del manuale"
    Write-Host "  manuale caricato: l'indicizzazione richiede 1-3 minuti"
} else { Write-Host "  manuale già presente" }
# Catalogo allineato con storage e Cosmos (es. documenti caricati prima che il catalogo esistesse).
$env:STORAGE_ACCOUNT = $out.storageName.value
$env:COSMOS_ENDPOINT = $out.cosmosEndpoint.value
Retry { .venv\Scripts\python.exe scripts\db\sync_catalog.py } "Riallineamento del catalogo"
az webapp restart -g $RG -n $out.webAppName.value -o none

Step "Fatto"
Write-Host "App:    $($out.webAppUrl.value)"
Write-Host "Prova:  .\scripts\deploy\smoke-test.ps1   (dopo qualche minuto: avvio del container e indicizzazione)"
Write-Host "Spegni: .\scripts\deploy\down.ps1"
