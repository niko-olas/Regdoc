# Cancella TUTTO l'ambiente RegDoc: costi a zero fino al prossimo up.ps1.
# Si perdono i dati (manuali indicizzati, interventi, cache): up.ps1 li ricarica dagli esempi.
#
# Uso: . .\scripts\env.ps1 ; .\scripts\deploy\down.ps1

$ErrorActionPreference = "Stop"
if (-not $RG) { throw "Carica prima le variabili: . .\scripts\env.ps1" }
$SUFFIX = $ACR_NAME -replace '^acrregdoc', ''

$answer = Read-Host "Cancello il resource group $RG e tutto quello che contiene? Scrivi il nome del resource group per confermare"
if ($answer -ne $RG) { Write-Host "Annullato."; return }

Write-Host "Cancellazione in corso (10-20 minuti)..."
az group delete -n $RG --yes

# Foundry (Cognitive Services) va in soft-delete per 48 ore: il nome resta occupato e up.ps1
# fallirebbe. Purge = cancellazione definitiva, libera il nome subito.
Write-Host "Purge di Foundry ($FOUNDRY)..."
try { az cognitiveservices account purge -l $LOCATION -g $RG -n $FOUNDRY -o none } catch { Write-Host "  niente da eliminare" }

# App Configuration: anche lui ha il soft-delete (solo nei tier a pagamento, ma non costa provare).
$appConfig = "appcs-regdoc-$SUFFIX"
try { az appconfig purge -n $appConfig -l $LOCATION --yes -o none 2>$null } catch { Write-Host "  App Configuration: niente da eliminare" }

Write-Host "Fatto. Restano solo i costi zero; per ricreare tutto: .\scripts\deploy\up.ps1"
