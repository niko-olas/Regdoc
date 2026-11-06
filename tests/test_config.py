import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "deploy"))
sys.path.insert(0, str(ROOT / "scripts" / "tools"))

from redis_peek import PAIRS, cosine_distance  # noqa: E402
from set_domain_profiles import PREFIX, settings_for  # noqa: E402

from shared.config import DomainProfile, RuntimeConfig  # noqa: E402


def test_senza_app_configuration_il_profilo_e_vuoto(monkeypatch):
    monkeypatch.delenv("APPCONFIG_ENDPOINT", raising=False)
    profile = RuntimeConfig().profile("stufe-pellet")
    assert profile == DomainProfile()
    # Senza nome leggibile si mostra il doc_type del percorso del blob.
    assert profile.doc_type_label("manuale-utente") == "manuale-utente"


def test_il_profilo_arriva_dal_caricamento_con_la_label_del_dominio(monkeypatch):
    monkeypatch.delenv("APPCONFIG_ENDPOINT", raising=False)
    config = RuntimeConfig()
    config._config = object()  # come se App Configuration fosse configurato
    # Il provider restituisce le chiavi senza prefisso e il JSON già come dizionario.
    config._profiles["stufe-pellet"] = {"Prompt": "Prompt delle stufe", "DocTypes": {"manuale-utente": "Manuale utente"}}
    profile = config.profile("stufe-pellet")
    assert profile.prompt == "Prompt delle stufe"
    assert profile.doc_type_label("manuale-utente") == "Manuale utente"
    assert profile.doc_type_label("scheda-nuova") == "scheda-nuova"


def test_ogni_file_di_infra_appconfig_diventa_un_profilo_con_label():
    path = ROOT / "infra" / "appconfig" / "stufe-pellet.json"
    settings = settings_for(path.stem, json.loads(path.read_text(encoding="utf-8")))
    assert {(s.key, s.label, s.content_type) for s in settings} == {
        (f"{PREFIX}Prompt", "stufe-pellet", "text/plain"),
        (f"{PREFIX}DocTypes", "stufe-pellet", "application/json"),
    }
    doc_types = json.loads(next(s.value for s in settings if s.key.endswith("DocTypes")))
    # Il manuale di prova di up.ps1 è caricato come manuale-utente: deve avere un nome leggibile.
    assert doc_types["manuale-utente"] == "Manuale utente"


def test_distanza_coseno_come_l_indice_redisearch():
    assert cosine_distance([1.0, 0.0], [2.0, 0.0]) == 0
    assert cosine_distance([1.0, 0.0], [0.0, 3.0]) == 1
    # Le coppie di prova coprono sia le parafrasi sia le domande diverse.
    assert {same for *_, same in PAIRS} == {True, False}
