"""Function App di RegDoc: una cartella per funzione, registrate qui come blueprint.

  blob_created/  on_blob_created       Event Grid (BlobCreated) → topic `documents`
  catalog/       on_document_uploaded  subscription `catalog` → catalogo dei documenti (PostgreSQL)
  changefeed/    on_chunks_changed     change feed di `chunks` → evento, catalogo, invalidazione cache
"""
import logging

import azure.functions as func

from blob_created.function import bp as blob_created_bp
from catalog.function import bp as catalog_bp
from changefeed.function import bp as changefeed_bp

app = func.FunctionApp()
for blueprint in (blob_created_bp, catalog_bp, changefeed_bp):
    app.register_functions(blueprint)

# Gli SDK Azure registrano ogni richiesta HTTP (URL e header) a livello INFO:
# in Application Insights diventerebbero più righe dei log applicativi.
logging.getLogger("azure").setLevel(logging.WARNING)
