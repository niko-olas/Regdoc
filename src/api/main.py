import os
import pathlib
import socket

from api.services import credential
from shared import telemetry

# Prima di creare l'app FastAPI: la strumentazione automatica si aggancia alla creazione dell'app.
telemetry.setup("regdoc-api", credential)

from fastapi import Depends, FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from api import assistant  # noqa: E402
from api.services import Services, get_services  # noqa: E402
from fielddata.documents import documents_for_model  # noqa: E402
from fielddata.installations import get_installation, list_installations  # noqa: E402

STATIC = pathlib.Path(__file__).parent / "static"

app = FastAPI(title="RegDoc API")


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    serial_number: str | None = None
    domain: str = "stufe-pellet"
    manufacturer: str | None = None
    model: str | None = None


@app.get("/health")
def health() -> dict:
    # Endpoint di probe: l'health check di App Service lo usa per sapere se il container è vivo.
    return {"status": "ok"}


@app.get("/info")
def info() -> dict:
    # Su App Service le "Application settings" arrivano al container come variabili d'ambiente.
    return {
        "version": os.getenv("APP_VERSION", "dev"),
        "environment": os.getenv("APP_ENV", "local"),
        "instance": socket.gethostname(),  # utile per vedere più repliche
    }


@app.get("/version")
def version() -> dict:
    return {"version": os.getenv("APP_VERSION", "dev")}


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/installations")
def installations(svc: Services = Depends(get_services)) -> list[dict]:
    with svc.pool.connection() as conn:
        return [
            {"serial_number": i.serial_number, "customer": i.customer, "city": i.city,
             "manufacturer": i.manufacturer, "model": i.model, "domain": i.domain}
            for i in list_installations(conn)
        ]


@app.get("/installations/{serial_number}/documents")
def installation_documents(serial_number: str, svc: Services = Depends(get_services)) -> dict:
    """I manuali disponibili per il modello dell'impianto: il tecnico sa subito su cosa si basano le risposte."""
    with svc.pool.connection() as conn:
        installation = get_installation(conn, serial_number)
        if installation is None:
            raise HTTPException(404, f"Impianto {serial_number} non trovato")
        docs = documents_for_model(conn, installation.domain, installation.manufacturer, installation.model)
    return {
        "model": f"{installation.manufacturer} {installation.model}",
        "documents": [d.__dict__ for d in docs],
    }


@app.post("/ask")
def ask(req: AskRequest, svc: Services = Depends(get_services)) -> dict:
    try:
        return assistant.ask(svc, req.question, serial_number=req.serial_number, domain=req.domain,
                             manufacturer=req.manufacturer, model=req.model)
    except assistant.InstallationNotFound:
        raise HTTPException(404, f"Impianto {req.serial_number} non trovato") from None
