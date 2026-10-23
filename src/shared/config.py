"""Configurazione a runtime da Azure App Configuration: impostazioni e feature flag.

Senza APPCONFIG_ENDPOINT (sviluppo locale, test) valgono i default del codice: l'app funziona
comunque, App Configuration serve a cambiare comportamento senza un nuovo deploy.
"""
import logging
import os

from azure.core.credentials import TokenCredential

log = logging.getLogger(__name__)

# Chiavi del progetto in App Configuration: prefisso RegDoc:, tolto al caricamento.
KEY_PREFIX = "RegDoc:"
# La sentinella: si aggiorna DOPO aver cambiato le altre chiavi, e solo lei viene controllata
# a ogni intervallo. Così un gruppo di modifiche arriva all'app tutto insieme e il controllo
# costa una richiesta sola invece di una per chiave.
SENTINEL = "RegDoc:Sentinel"
REFRESH_SECONDS = 30


class RuntimeConfig:
    def __init__(self, credential: TokenCredential | None = None, defaults: dict[str, bool] | None = None):
        self._defaults = defaults or {}
        self._config = None
        self._features = None
        endpoint = os.getenv("APPCONFIG_ENDPOINT")
        if not endpoint:
            return
        from azure.appconfiguration.provider import SettingSelector, WatchKey, load
        from featuremanagement import FeatureManager

        self._config = load(
            endpoint=endpoint,
            credential=credential,
            selects=[SettingSelector(key_filter=f"{KEY_PREFIX}*")],
            trim_prefixes=[KEY_PREFIX],
            refresh_on=[WatchKey(SENTINEL)],
            refresh_interval=REFRESH_SECONDS,
            # I feature flag hanno un loro meccanismo di refresh, indipendente dalla sentinella.
            feature_flag_enabled=True,
            feature_flag_refresh_enabled=True,
        )
        self._features = FeatureManager(self._config)

    def refresh(self) -> None:
        """Da chiamare a ogni richiesta: contatta App Configuration solo se è passato l'intervallo."""
        if self._config is not None:
            try:
                self._config.refresh()
            except Exception:  # noqa: BLE001 — una config vecchia di qualche secondo è meglio di un errore
                log.warning("Refresh di App Configuration fallito, uso i valori già caricati", exc_info=True)

    def is_enabled(self, flag: str) -> bool:
        if self._features is None:
            return self._defaults.get(flag, False)
        return self._features.is_enabled(flag)

    def get(self, key: str, default: str) -> str:
        if self._config is None:
            return default
        return self._config.get(key, default)
