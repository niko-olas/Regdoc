# Recap 01 — Hosting di applicazioni container

Dominio d'esame: **1. Soluzioni containerizzate su Azure (20–25%)** → *Hosting di applicazioni container*.
Completato il 2026-10-19. Componente usato: l'API scheletro (`src/api`, endpoint `/health`, `/info`, `/version`).

| Skill | Come è stata coperta |
|---|---|
| Creare, archiviare, versionare e gestire immagini con ACR | Registry Basic, admin user disabilitato, tag `1.0.0` / `1.1.0` / `latest` |
| Build ed esecuzione di immagini con ACR Tasks | Due quick task con `az acr build`, `--build-arg`, cache dei layer |
| Deploy di container su App Service con env vars e secret | Pull con managed identity + `AcrPull`, app settings, `WEBSITES_PORT`, health check, cambio immagine |

---

## 1. Preparazione

- **Variabili di sessione** in `infra/scripts/env.ps1` (ignorato da git), caricate con `. .\infra\scripts\env.ps1`. Il punto iniziale (*dot-sourcing*) lascia le variabili nella sessione. Nel repo c'è solo `env.example.ps1` con i segnaposto.
- **Login con MFA**: se il tenant richiede l'MFA, `az login` senza tenant non trova subscription (`AADSTS50076`). Soluzione: `az login --tenant <tenant-id>`.
- **Resource group** `rg-regdoc-dev` con tag `project=regdoc env=dev`: contenitore logico, si cancella tutto con `az group delete`.
- **Resource provider**: ogni servizio è un provider (`Microsoft.ContainerRegistry`, `Microsoft.Web`…). Su una subscription nuova va registrato, altrimenti la `create` fallisce con `MissingSubscriptionRegistration`. La registrazione è **asincrona** (`Registering` → `Registered`). Il portale registra i provider da solo, la CLI no.
- **Budget** (Cost Management → Budgets): manda solo un'email, **non blocca la spesa**, e i dati arrivano con 8–24 h di ritardo.

## 2. Azure Container Registry

```powershell
az acr check-name --name $ACR_NAME
az acr create --resource-group $RG --name $ACR_NAME --sku Basic --admin-enabled false
```

- Il nome è **globale** (`<nome>.azurecr.io`), solo alfanumerico.
- **SKU**: Basic < Standard < **Premium**. Solo Premium ha **geo-replica**, **private endpoint** e content trust.
- **Admin user**: username/password condivisi, da lasciare disabilitato. Si usa la managed identity.
- **Repository e tag**: un repository per immagine, più tag per versione. I tag fissi (`1.0.0`) vanno usati per il deploy. `latest` si sposta a ogni build e non dice cosa sta girando. I tag vecchi servono per il rollback.

```powershell
az acr repository list --name $ACR_NAME -o table
az acr repository show-tags --name $ACR_NAME --repository regdoc-api -o table
```

## 3. ACR Tasks

```powershell
az acr build --registry $ACR_NAME --image regdoc-api:1.1.0 --image regdoc-api:latest `
  --build-arg APP_VERSION=1.1.0 -f src/api/Dockerfile src/
az acr task list-runs --registry $ACR_NAME -o table
```

- **Quick task**: la CLI comprime il **contesto di build** (`src/`), lo carica e la build avviene in Azure. Non serve Docker in locale.
- `-f` indica il Dockerfile, l'ultimo argomento è il contesto. Il contesto è `src/` e non `src/api/`, così il Dockerfile potrà copiare `shared/`.
- In `list-runs` un quick task ha **TASK vuoto** e **TRIGGER `Manual`**.
- **Cache dei layer**: `requirements.txt` viene copiato prima del codice, quindi `pip install` resta in cache finché le dipendenze non cambiano.
- Altri tipi di task (`az acr task create`): trigger su **commit Git**, su **aggiornamento dell'immagine base**, su **timer**. I **multi-step task** sono definiti in YAML.

## 4. App Service con container

```powershell
az appservice plan create --resource-group $RG --name $PLAN --is-linux --sku B1
az webapp create --resource-group $RG --plan $PLAN --name $WEBAPP `
  --container-image-name "$($ACR_NAME).azurecr.io/regdoc-api:1.0.0"
```

- Il **plan** è la macchina (CPU, RAM, prezzo). La **web app** è l'applicazione. Più app possono condividere un plan.
- I container Linux richiedono un plan **Linux**. Deployment slot e autoscale richiedono almeno **Standard**.
- Il plan si paga **finché esiste**, anche con la web app ferma.

### Il pull con managed identity

Primo avvio → errore atteso `ImagePullUnauthorizedFailure`: la web app non ha identità né permessi. I pezzi della soluzione sono tre:

```powershell
# 1. chi è: system-assigned identity
$PRINCIPAL_ID = az webapp identity assign --resource-group $RG --name $WEBAPP --query principalId -o tsv

# 2. cosa può fare: AcrPull con scope sul solo registry
$ACR_ID = az acr show --resource-group $RG --name $ACR_NAME --query id -o tsv
az role assignment create --assignee-object-id $PRINCIPAL_ID --assignee-principal-type ServicePrincipal `
  --role AcrPull --scope $ACR_ID

# 3. usala: di' alla web app di fare il pull con l'identità
$CONFIG_ID = az webapp config show --resource-group $RG --name $WEBAPP --query id -o tsv
az resource update --ids $CONFIG_ID --set properties.acrUseManagedIdentityCreds=true
```

- **System-assigned**: nasce e muore con la risorsa. **User-assigned**: è una risorsa a sé, condivisibile tra più app.
- `AcrPull` permette solo il download (**minimo privilegio**). `AcrPush` permette anche l'upload. Contributor/Owner sono eccessivi.
- L'assegnazione di un ruolo può impiegare **qualche minuto** a propagarsi.
- Nel portale: *Identity* (punto 1), *Access control (IAM) → Add role assignment* sul registry (punto 2), *Deployment Center → Authentication: Managed Identity* (punto 3).

### Porta, configurazione, health check

```powershell
az webapp config appsettings set --resource-group $RG --name $WEBAPP --settings WEBSITES_PORT=8000
az webapp config appsettings set --resource-group $RG --name $WEBAPP --settings APP_ENV=dev APP_SECRET=valore-di-prova
az resource update --ids $CONFIG_ID --set properties.healthCheckPath=/health
```

- App Service si aspetta la porta **80**. Con una porta diversa serve `WEBSITES_PORT`, altrimenti il container parte ma l'avvio va in timeout.
- Le **app settings diventano variabili d'ambiente** nel container. Il codice usa `os.getenv` e non dipende da Azure.
- Ogni modifica alle app settings **riavvia l'app**.
- Le app settings sono cifrate a riposo ma **leggibili in chiaro** da chi accede alla web app. Per i segreti si usa il riferimento a Key Vault (`@Microsoft.KeyVault(SecretUri=...)`), che arriverà in F5.
- L'**health check** toglie dal bilanciamento le istanze che non rispondono. È l'equivalente delle liveness/readiness probe di AKS e Container Apps.

### Log

```powershell
az webapp log config --resource-group $RG --name $WEBAPP --docker-container-logging filesystem
az webapp log tail --resource-group $RG --name $WEBAPP
```

Nel portale: *Monitoring → Log stream*.

### Rilascio di una nuova versione

```powershell
az webapp config appsettings delete --resource-group $RG --name $WEBAPP --setting-names APP_VERSION
az webapp config container set --resource-group $RG --name $WEBAPP `
  --container-image-name "$($ACR_NAME).azurecr.io/regdoc-api:1.1.0"
```

- La versione viene impostata **nell'immagine** (`ARG`/`ENV` nel Dockerfile, `--build-arg` nella build) e coincide con il tag.
- Le app settings vengono iniettate all'avvio e **sovrascrivono** le `ENV` dell'immagine, per questo l'app setting `APP_VERSION` è stata rimossa.
- `instance` in `/info` cambia: è un container nuovo.
- Su B1 il cambio di immagine dà qualche secondo di downtime. In produzione si usano i **deployment slot** (staging → swap, con rollback tramite un altro swap) o il **continuous deployment** con webhook ACR.

---

## Trappole d'esame

| Situazione | Risposta |
|---|---|
| `MissingSubscriptionRegistration` | Registrare il resource provider (non è RBAC né quota) |
| `ImagePullUnauthorizedFailure` con admin user disabilitato | Managed identity + `AcrPull` sul registry + `acrUseManagedIdentityCreds` |
| L'identità ha AcrPull ma il pull fallisce ancora | Manca il terzo pezzo (`acrUseManagedIdentityCreds`) oppure il ruolo non si è ancora propagato |
| Container avviato ma l'app non risponde / timeout all'avvio | Porta diversa da 80 senza `WEBSITES_PORT` |
| Registry replicato in più regioni / private endpoint | SKU **Premium** |
| Deployment slot o autoscale su App Service | Almeno SKU **Standard** |
| `ENV` nell'immagine e app setting con lo stesso nome | Vince l'**app setting** |
| Build senza Docker locale | `az acr build` (quick task) |
| Ricostruire automaticamente quando si aggiorna l'immagine base | ACR Task con trigger *base image update* |

## Domande di ripasso

1. Quali tre pezzi servono perché App Service scarichi da ACR senza admin user?
2. Che differenza c'è tra identità system-assigned e user-assigned? Quando conviene la seconda?
3. Perché nel Dockerfile `requirements.txt` viene copiato prima del codice?
4. Perché si fa il deploy di `:1.1.0` e non di `:latest`?
5. Che cosa fa `--build-arg`, e che differenza c'è tra `ARG` ed `ENV`?
6. Un segreto in un'app setting è sicuro? Che alternativa c'è?
7. Che cosa succede alle istanze di App Service che non rispondono sull'health check path?
8. Come si rilascia una nuova versione senza downtime su App Service?
