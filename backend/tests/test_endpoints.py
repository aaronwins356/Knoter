from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"


def test_config_round_trip():
    response = client.get("/config")
    assert response.status_code == 200
    payload = response.json()
    payload["volatility_threshold"] = 7.5
    update = client.post("/config", json=payload)
    assert update.status_code == 200
    assert update.json()["volatility_threshold"] == 7.5
