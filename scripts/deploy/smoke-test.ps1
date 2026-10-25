# Verifica dell'app pubblicata: health, versione, prodotti e una domanda vera (due volte, per la cache).
# Uso: . .\scripts\env.ps1 ; .\scripts\deploy\smoke-test.ps1
$ErrorActionPreference = "Stop"
$base = "https://$WEBAPP.azurewebsites.net"

Write-Host "health:  $((Invoke-RestMethod "$base/health").status)"
Write-Host "versione: $((Invoke-RestMethod "$base/version").version)"
$products = Invoke-RestMethod "$base/products"
Write-Host "prodotti: $($products.Count)"
$karolina = $products | Where-Object model -eq "karolina" | Select-Object -First 1
Write-Host "manuali indicizzati per $($karolina.manufacturer) $($karolina.model): $($karolina.indexed_documents)"

$body = @{
    question     = "La stufa va in allarme sonda fumi e si spegne dopo mezz'ora: cosa controllo?"
    domain       = $karolina.domain
    manufacturer = $karolina.manufacturer
    model        = $karolina.model
} | ConvertTo-Json
foreach ($n in 1, 2) {
    $r = Invoke-RestMethod "$base/ask" -Method Post -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($body))
    Write-Host "`n--- domanda $n su $($karolina.model): cache=$($r.cache), $($r.timings_ms.totale) ms"
    if ($n -eq 1) {
        Write-Host $r.answer
        Write-Host "`nfonti: $(($r.sources | ForEach-Object id) -join ', ')"
    }
}
