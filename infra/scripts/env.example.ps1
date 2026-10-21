# Variabili comuni per i comandi az di RegDoc.
# Copia questo file in env.ps1 (ignorato da git), compila i valori e caricalo
# nella sessione PowerShell con:  . .\infra\scripts\env.ps1
# Mai committare env.ps1: il repo è pubblico.

$SUBSCRIPTION_ID = "<subscription-id>"
$TENANT_ID       = "<tenant-id>"

# Una sola regione per tutto il progetto: evita traffico cross-region e
# semplifica le regole di rete. Verificare che i servizi delle fasi successive
# (Foundry, Managed Redis, PostgreSQL Flexible) siano disponibili nella regione.
$LOCATION = "swedencentral"

$RG = "rg-regdoc-dev"

# Il nome dell'ACR è globale (diventa <nome>.azurecr.io): solo alfanumerici, 5-50 caratteri.
$ACR_NAME = "acrregdoc<suffisso>"

# App Service (F4). Anche il nome della web app è globale: <nome>.azurewebsites.net
$PLAN   = "plan-regdoc-dev"
$WEBAPP = "app-regdoc-api-<suffisso>"

# Ingestion (F1). Nome globale: 3-24 caratteri, solo minuscole e numeri (niente trattini).
$STORAGE = "stregdoc<suffisso>"

# Nome globale (<nome>.servicebus.windows.net): 6-50 caratteri, lettere, numeri e trattini.
$SB_NAMESPACE = "sb-regdoc-<suffisso>"

# Function App di ingestion e il suo storage "di servizio" (chiavi dell'host, pacchetti di deploy),
# separato da quello dei documenti. Stesse regole di nome dello storage sopra.
$FUNC_STORAGE = "stregdocfn<suffisso>"
$FUNCAPP      = "func-regdoc-ingest-<suffisso>"
$EG_TOPIC = "evgt-regdoc-documents"

