"""Configurazione a runtime da Azure App Configuration: impostazioni, feature flag e profili di dominio.

Senza APPCONFIG_ENDPOINT (sviluppo locale, test) valgono i default del codice: l'app funziona
comunque, App Configuration serve a cambiare comportamento senza un nuovo deploy.
"""
import logging
import os
from dataclasses import dataclass, field

from azure.core.credentials import TokenCredential

log = logging.getLogger(__name__)

# Chiavi del progetto in App Configuration: prefisso RegDoc:, tolto al caricamento.
KEY_PREFIX = "RegDoc:"
# Profilo di dominio: stesse chiavi per ogni dominio, distinte dalla label (= nome del dominio).
PROFILE_PREFIX = "RegDoc:Profile:"
# La sentinella: si aggiorna DOPO aver cambiato le altre chiavi, e solo lei viene controllata
# a ogni intervallo. Così un gruppo di modifiche arriva all'app tutto insieme e il controllo
# costa una richiesta sola invece di una per chiave.
SENTINEL = "RegDoc:Sentinel"
REFRESH_SECONDS = 30


@dataclass(frozen=True)
class DomainProfile:
    """Ciò che cambia da un dominio all'altro senza toccare il codice."""

    prompt: str | None = None
    # doc_type → nome leggibile, es. "manuale-utente" → "Manuale utente".
    doc_types: dict[str, str] = field(default_factory=dict)

    def doc_type_label(self, doc_type: str) -> str:
        return self.doc_types.get(doc_type, doc_type)


class RuntimeConfig:
    def __init__(self, credential: TokenCredential | None = None, defaults: dict[str, bool] | None = None):
        self._defaults = defaults or {}
        self._credential = credential
        self._endpoint = os.getenv("APPCONFIG_ENDPOINT")
        self._config = None
        self._features = None
        self._profiles: dict = {}
        if not self._endpoint:
            return
        from azure.appconfiguration.provider import SettingSelector, WatchKey, load
        from featuremanagement import FeatureManager

        self._config = load(
            endpoint=self._endpoint,
            credential=credential,
            # Senza label_filter si leggono solo le chiavi senza label: i profili (con label) restano fuori.
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
        for provider in [self._config, *self._profiles.values()]:
            if provider is None:
                continue
            try:
                provider.refresh()
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

    def profile(self, domain: str) -> DomainProfile:
        """Il profilo del dominio (label = dominio); senza App Configuration, quello vuoto."""
        if self._config is None:
            return DomainProfile()
        provider = self._profiles.get(domain)
        if provider is None:
            try:
                provider = self._profiles[domain] = self._load_profile(domain)
            except Exception:  # noqa: BLE001 — senza profilo valgono i default del codice
                log.warning("Profilo del dominio %s non caricato, uso i default", domain, exc_info=True)
                return DomainProfile()
        return DomainProfile(prompt=provider.get("Prompt"), doc_types=dict(provider.get("DocTypes") or {}))

    def _load_profile(self, domain: str):
        from azure.appconfiguration.provider import SettingSelector, WatchKey, load

        # Un caricamento per dominio: il provider unisce le chiavi in un solo dizionario, quindi la stessa
        # chiave con label diverse non può convivere in un caricamento. Il filtro sulla label sceglie il
        # dominio; DocTypes ha content type application/json e arriva già come dizionario.
        return load(
            endpoint=self._endpoint,
            credential=self._credential,
            selects=[SettingSelector(key_filter=f"{PROFILE_PREFIX}*", label_filter=domain)],
            trim_prefixes=[PROFILE_PREFIX],
            refresh_on=[WatchKey(SENTINEL)],
            refresh_interval=REFRESH_SECONDS,
        )
