from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_info_legge_la_configurazione_dall_ambiente(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_SECRET", "valore-segreto")
    body = client.get("/info").json()
    assert body["version"] == "1.2.3"
    assert body["environment"] == "test"
    assert body["secret_configured"] is True
    assert "valore-segreto" not in str(body)

def test_version(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    assert client.get("/version").json() == {"version": "9.9.9"}

