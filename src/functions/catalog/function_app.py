"""Function App catalog di RegDoc: catalogo dei documenti e reazione ai manuali indicizzati.

  document_uploaded/  on_document_uploaded  subscription `catalog` → catalogo dei documenti (PostgreSQL)
  changefeed/         on_chunks_changed     manifest dal change feed di `chunks` → evento, catalogo, cache

Le due funzioni scrivono la stessa tabella (catalog_store.py) e restano nella stessa app.
"""
import logging

import azure.functions as func

from changefeed.function import bp as changefeed_bp
from document_uploaded.function import bp as document_uploaded_bp

app = func.FunctionApp()
for blueprint in (document_uploaded_bp, changefeed_bp):
    app.register_functions(blueprint)

# Gli SDK Azure registrano ogni richiesta HTTP (URL e header) a livello INFO:
# in Application Insights diventerebbero più righe dei log applicativi.
logging.getLogger("azure").setLevel(logging.WARNING)
