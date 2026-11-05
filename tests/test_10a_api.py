from fastapi.testclient import TestClient

from main import app, pipeline


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert data["service"] == "raca-backend"


def test_repository_status() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/repository/status"
        )

    assert response.status_code == 200

    data = response.json()

    assert data["repository"] == "httpx"
    assert data["ready"] is True