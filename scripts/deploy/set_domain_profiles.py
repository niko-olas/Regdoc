"""Profili di dominio in App Configuration, dai file infra/appconfig/<dominio>.json.

Ogni file diventa le chiavi RegDoc:Profile:* con label = nome del dominio: aggiungere un dominio
(es. caldaie) è aggiungere un file, non scrivere codice. La sentinella si aggiorna per ultima,
così le app ricaricano il profilo entro 30 s senza riavvio.

Uso, dalla radice con il venv di sviluppo (lo chiama up.ps1):
    .venv\\Scripts\\python.exe scripts\\deploy\\set_domain_profiles.py <endpoint di App Configuration>

Richiede App Configuration Data Owner (assegnato all'utente dal Bicep).
"""
import json
import pathlib
import sys
from datetime import datetime, timezone

from azure.appconfiguration import AzureAppConfigurationClient, ConfigurationSetting
from azure.identity import DefaultAzureCredential

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROFILES = ROOT / "infra" / "appconfig"
PREFIX = "RegDoc:Profile:"
SENTINEL = "RegDoc:Sentinel"


def settings_for(domain: str, profile: dict) -> list[ConfigurationSetting]:
    return [
        ConfigurationSetting(key=f"{PREFIX}Prompt", label=domain, value=profile["prompt"], content_type="text/plain"),
        # application/json: il provider lo restituisce già come dizionario.
        ConfigurationSetting(key=f"{PREFIX}DocTypes", label=domain, content_type="application/json",
                             value=json.dumps(profile["doc_types"], ensure_ascii=False)),
    ]


def main() -> None:
    client = AzureAppConfigurationClient(sys.argv[1], DefaultAzureCredential())
    for path in sorted(PROFILES.glob("*.json")):
        domain = path.stem
        for setting in settings_for(domain, json.loads(path.read_text(encoding="utf-8"))):
            client.set_configuration_setting(setting)
        print(f"  profilo {domain}: {PREFIX}Prompt, {PREFIX}DocTypes")
    # Per ultima: un valore nuovo a ogni esecuzione, altrimenti le app non vedrebbero il cambiamento.
    client.set_configuration_setting(ConfigurationSetting(key=SENTINEL, value=datetime.now(timezone.utc).isoformat()))


if __name__ == "__main__":
    main()
