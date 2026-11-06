"""Function App ingest di RegDoc: riceve gli eventi sui documenti caricati e li mette sul topic.

  blob_created/  on_blob_created  Event Grid (BlobCreated) → topic `documents`

App separata da catalog per il minimo privilegio: riceve eventi su file caricati da fuori, e la sua
identità può solo leggere i blob e inviare sul topic.
"""
import logging
import os

import azure.functions as func

if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.identity import DefaultAzureCredential
    from azure.monitor.opentelemetry import configure_azure_monitor

    # host.json ha telemetryMode OpenTelemetry. Con Entra ID l'autenticazione va data due volte: all'host
    # (APPLICATIONINSIGHTS_AUTHENTICATION_STRING) e al worker Python, qui, con la credenziale. Per questo
    # la configurazione è esplicita invece dell'app setting PYTHON_APPLICATIONINSIGHTS_ENABLE_TELEMETRY.
    configure_azure_monitor(credential=DefaultAzureCredential())

from blob_created.function import bp as blob_created_bp  # noqa: E402

app = func.FunctionApp()
app.register_functions(blob_created_bp)

# Gli SDK Azure registrano ogni richiesta HTTP (URL e header) a livello INFO:
# in Application Insights diventerebbero più righe dei log applicativi.
logging.getLogger("azure").setLevel(logging.WARNING)
