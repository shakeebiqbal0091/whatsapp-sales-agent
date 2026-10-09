from fastapi.testclient import TestClient

from app.main import app


def test_health():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["health"].endswith("/health")
    assert body["webhook"].endswith("/webhook")
