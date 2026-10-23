"""OpenTelemetry → Application Insights con la distro Azure Monitor."""
import logging
import os

from azure.core.credentials import TokenCredential


def setup(service_name: str, credential: TokenCredential | None = None) -> bool:
    """Attiva tracce, metriche e log verso Application Insights, se configurato.

    Va chiamata PRIMA di creare l'app FastAPI: la distro strumenta FastAPI, requests e gli SDK
    Azure (Cosmos, ecc.) agganciandosi alle librerie quando vengono usate.
    Restituisce False in locale/test, dove APPLICATIONINSIGHTS_CONNECTION_STRING non c'è.
    """
    if not os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return False
    # service.name diventa cloud_RoleName in Application Insights: distingue API, worker, ecc.
    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
    from azure.monitor.opentelemetry import configure_azure_monitor

    # La connection string identifica la risorsa (non è un segreto da Key Vault); con `credential`
    # l'invio dei dati si autentica con Entra ID (ruolo Monitoring Metrics Publisher), quindi
    # sulla risorsa si può disattivare l'autenticazione locale.
    configure_azure_monitor(credential=credential, logger_name="regdoc")
    logging.getLogger("regdoc").setLevel(logging.INFO)
    return True
