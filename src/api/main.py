import os
import socket

from fastapi import FastAPI

app = FastAPI(title="RegDoc API")


@app.get("/health")
def health() -> dict:
    # Endpoint di probe: App Service (health check), AKS (liveness/readiness)
    # e Container Apps lo usano per sapere se il container è vivo.
    return {"status": "ok"}


@app.get("/info")
def info() -> dict:
    # Mostra come la configurazione arriva al container: su App Service le
    # "Application settings" diventano variabili d'ambiente, e un secret
    # (es. riferimento a Key Vault) arriva nello stesso modo. Del secret
    # esponiamo solo la presenza, mai il valore.
    return {
        "version": os.getenv("APP_VERSION", "dev"),
        "environment": os.getenv("APP_ENV", "local"),
        "secret_configured": bool(os.getenv("APP_SECRET")),
        "instance": socket.gethostname(),  # utile per vedere più repliche/pod
    }

@app.get("/version")
def version() -> dict:
    return {
        "version": os.getenv("APP_VERSION", "dev")
    }
