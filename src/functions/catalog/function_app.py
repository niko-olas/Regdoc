"""Function App catalog di RegDoc: catalogo dei documenti e reazione ai manuali indicizzati.

  document_uploaded/  on_document_uploaded  subscription `catalog` → catalogo dei documenti (PostgreSQL)
  changefeed/         on_chunks_changed     manifest dal change feed di `chunks` → evento, catalogo, cache

Le due funzioni scrivono la stessa tabella (catalog_store.py) e restano nella stessa app.
"""
import logging
import os

import azure.functions as func

if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.identity import DefaultAzureCredential
    from azure.monitor.opentelemetry import configure_azure_monitor

    # Come in ingest: con Entra ID il worker Python riceve la credenziale qui (vedi ingest/function_app.py).
    configure_azure_monitor(credential=DefaultAzureCredential())

from changefeed.function import bp as changefeed_bp  # noqa: E402
from document_uploaded.function import bp as document_uploaded_bp  # noqa: E402

app = func.FunctionApp()
for blueprint in (document_uploaded_bp, changefeed_bp):
    app.register_functions(blueprint)

# Gli SDK Azure registrano ogni richiesta HTTP (URL e header) a livello INFO:
# in Application Insights diventerebbero più righe dei log applicativi.
logging.getLogger("azure").setLevel(logging.WARNING)
