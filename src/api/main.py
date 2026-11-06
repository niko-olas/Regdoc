import os
import pathlib
import socket

from api.services import credential
from shared import telemetry

# Prima di creare l'app FastAPI: la strumentazione automatica si aggancia alla creazione dell'app.
telemetry.setup("regdoc-api", credential)

from fastapi import Depends, FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from opentelemetry import trace  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from api import assistant  # noqa: E402
from api.services import Services, get_services  # noqa: E402
from fielddata.documents import documents_for_model  # noqa: E402
from fielddata.products import list_products  # noqa: E402

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


@app.get("/products")
def products(svc: Services = Depends(get_services)) -> list[dict]:
    # Il tecnico sceglie il prodotto, non il cliente: l'API non espone l'elenco dei clienti.
    with svc.pool.connection() as conn:
        return [p.__dict__ for p in list_products(conn)]


@app.get("/products/{domain}/{manufacturer}/{model}/documents")
def product_documents(domain: str, manufacturer: str, model: str, svc: Services = Depends(get_services)) -> dict:
    """I manuali disponibili per il modello: il tecnico sa subito su cosa si basano le risposte."""
    with svc.pool.connection() as conn:
        docs = documents_for_model(conn, domain, manufacturer, model)
    # Il nome leggibile del tipo di documento viene dal profilo del dominio in App Configuration.
    profile = svc.config.profile(domain)
    return {
        "model": f"{manufacturer} {model}",
        "documents": [{**d.__dict__, "doc_type_label": profile.doc_type_label(d.doc_type)} for d in docs],
    }


@app.post("/ask")
def ask(req: AskRequest, svc: Services = Depends(get_services)) -> dict:
    try:
        result = assistant.ask(svc, req.question, serial_number=req.serial_number, domain=req.domain,
                               manufacturer=req.manufacturer, model=req.model)
    except assistant.InstallationNotFound:
        raise HTTPException(404, f"Impianto {req.serial_number} non trovato") from None
    # Esito della cache (exact, semantic, miss) sullo span della richiesta: in KQL è una colonna di
    # AppRequests (Properties), da cui si calcola il tasso di hit senza leggere le risposte.
    span = trace.get_current_span()
    span.set_attribute("regdoc.cache", result["cache"])
    span.set_attribute("regdoc.model", f"{result['scope']['manufacturer']} {result['scope']['model']}")
    return result
