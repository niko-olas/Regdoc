"""Function App ingest di RegDoc: riceve gli eventi sui documenti caricati e li mette sul topic.

  blob_created/  on_blob_created  Event Grid (BlobCreated) → topic `documents`

App separata da catalog per il minimo privilegio: riceve eventi su file caricati da fuori, e la sua
identità può solo leggere i blob e inviare sul topic.
"""
import logging

import azure.functions as func

from blob_created.function import bp as blob_created_bp

app = func.FunctionApp()
app.register_functions(blob_created_bp)

# Gli SDK Azure registrano ogni richiesta HTTP (URL e header) a livello INFO:
# in Application Insights diventerebbero più righe dei log applicativi.
logging.getLogger("azure").setLevel(logging.WARNING)
