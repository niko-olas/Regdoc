from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_info_legge_la_configurazione_dall_ambiente(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    monkeypatch.setenv("APP_ENV", "test")
    body = client.get("/info").json()
    assert body["version"] == "1.2.3"
    assert body["environment"] == "test"

def test_version(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    assert client.get("/version").json() == {"version": "9.9.9"}



# --- /ask con servizi finti: nessuna risorsa Azure ---------------------------------------------
import contextlib  # noqa: E402
from datetime import date  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import api.assistant as assistant  # noqa: E402
import api.main as main  # noqa: E402
from api.retrieval import ManualPage  # noqa: E402
from fielddata.installations import Installation  # noqa: E402
from fielddata.search import SimilarIntervention  # noqa: E402
from shared.config import RuntimeConfig  # noqa: E402


class FakeChat:
    def __init__(self):
        self.messages = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.messages = kwargs["messages"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Pulire la sonda [M1] [I1]"))],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10))


def fake_services(flags):
    chat = FakeChat()
    return SimpleNamespace(
        config=RuntimeConfig(defaults=flags),
        embedder=SimpleNamespace(embed=lambda texts: [[0.1] * 3 for _ in texts]),
        chat=chat, chat_deployment="gpt-test", chunks=None,
        pool=SimpleNamespace(connection=lambda: contextlib.nullcontext(object())),
        cache=None, _chat=chat,
    )


def install_fakes(monkeypatch, flags):
    svc = fake_services(flags)
    app.dependency_overrides[main.get_services] = lambda: svc
    monkeypatch.setattr(assistant, "search_manuals", lambda *a, **k: (
        [ManualPage("karolina.pdf", "uso-manutenzione", 12, "Pulizia della sonda fumi...", 0.82)], 3.1))
    calls = []
    monkeypatch.setattr(assistant, "similar_interventions", lambda conn, vec, **k: calls.append(k) or [
        SimilarIntervention("INT-00145", date(2026, 1, 17), "extraflame", "karolina", "Errore fumi", "Sonda sostituita", 0.2)])
    monkeypatch.setattr(assistant, "get_installation", lambda conn, serial: Installation(
        serial, "stufe-pellet", "extraflame", "karolina", date(2020, 1, 1), "Famiglia Rossi", "Trento", {"potenza_kw": "8"}))
    monkeypatch.setattr(assistant, "history", lambda conn, serial: [])
    return svc, calls


def test_ask_usa_impianto_manuali_e_interventi(monkeypatch):
    svc, calls = install_fakes(monkeypatch, {"use-interventions": True})
    try:
        body = client.post("/ask", json={"question": "allarme sonda fumi", "serial_number": "EXT-KAR-00026"}).json()
    finally:
        app.dependency_overrides.clear()
    assert body["answer"] == "Pulire la sonda [M1] [I1]"
    assert [s["id"] for s in body["sources"]] == ["M1", "I1"]
    assert body["scope"]["model"] == "karolina" and body["cache"] == "miss"
    assert calls[0]["model"] == "karolina"  # gli interventi sono filtrati sul modello dell'impianto
    prompt = svc._chat.messages[1]["content"]
    assert "[M1] karolina.pdf, pagina 12" in prompt and "[I1] INT-00145" in prompt and "EXT-KAR-00026" in prompt


def test_feature_flag_disattiva_gli_interventi(monkeypatch):
    svc, calls = install_fakes(monkeypatch, {"use-interventions": False})
    try:
        body = client.post("/ask", json={"question": "allarme sonda fumi", "serial_number": "EXT-KAR-00026"}).json()
    finally:
        app.dependency_overrides.clear()
    assert calls == [] and [s["kind"] for s in body["sources"]] == ["manuale"]
    assert body["flags"]["use-interventions"] is False


def test_manuali_disponibili_per_l_impianto(monkeypatch):
    from fielddata.documents import CatalogDocument

    install_fakes(monkeypatch, {})
    monkeypatch.setattr(main, "get_installation", assistant.get_installation)
    monkeypatch.setattr(main, "documents_for_model", lambda conn, d, m, mo: [
        CatalogDocument("karolina.pdf", "manuale-utente", "indicizzato", None, None)] if mo == "karolina" else [])
    try:
        body = client.get("/installations/EXT-KAR-00026/documents").json()
    finally:
        app.dependency_overrides.clear()
    assert body["model"] == "extraflame karolina"
    assert body["documents"][0]["status"] == "indicizzato"


def test_la_cache_scrive_con_la_versione_dei_manuali_letta(monkeypatch):
    svc, _ = install_fakes(monkeypatch, {"use-interventions": True})
    stored = {}

    class FakeCache:
        def version(self, domain):
            return 7

        def get_exact(self, domain, ver, scope, question):
            return None

        def store(self, domain, ver, scope, question, vector, response):
            stored["ver"] = ver

    svc.cache = FakeCache()
    try:
        body = client.post("/ask", json={"question": "allarme sonda fumi", "serial_number": "EXT-KAR-00026"}).json()
    finally:
        app.dependency_overrides.clear()
    # Se scrivesse con un'altra versione, l'invalidazione dal change feed non avrebbe effetto.
    assert body["cache"] == "miss" and stored["ver"] == 7


def test_impianto_inesistente_404(monkeypatch):
    install_fakes(monkeypatch, {})
    monkeypatch.setattr(assistant, "get_installation", lambda conn, serial: None)
    try:
        res = client.post("/ask", json={"question": "allarme sonda fumi", "serial_number": "NON-ESISTE"})
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 404


def test_si_mostrano_solo_le_fonti_citate():
    from api.answer import cited_only

    sources = [{"id": i} for i in ("M1", "M2", "M3", "M4", "I1", "I2")]
    text = "Spegnere la stufa [M3]. Poi premere il tasto 5 [M4, I2]."
    assert [s["id"] for s in cited_only(sources, text)] == ["M3", "M4", "I2"]
    assert cited_only(sources, "nessuna citazione") == []


def test_gli_interventi_lontani_non_entrano_nel_prompt(monkeypatch):
    svc, _ = install_fakes(monkeypatch, {"use-interventions": True})
    monkeypatch.setattr(assistant, "similar_interventions", lambda conn, vec, **k: [
        SimilarIntervention("INT-00001", date(2025, 1, 1), "extraflame", "karolina", "Display spento", "Fusibile", 0.47)])
    try:
        client.post("/ask", json={"question": "come imposto la data?", "serial_number": "EXT-KAR-00026"})
    finally:
        app.dependency_overrides.clear()
    assert "INT-00001" not in svc._chat.messages[1]["content"]
