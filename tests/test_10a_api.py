from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from src.main import app, pipeline


async def skip_restore() -> None:
    return None


async def skip_close() -> None:
    return None


def isolate_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "restore_existing_repository", skip_restore)
    monkeypatch.setattr(pipeline, "close", skip_close)


def test_health(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_lifespan(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert data["service"] == "raca-backend"


def test_repository_status(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_lifespan(monkeypatch)
    monkeypatch.setattr(
        pipeline,
        "_active_index",
        SimpleNamespace(
            repository="test-repository",
            repository_key="test-repository-key",
        ),
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/repository/status"
        )

    assert response.status_code == 200

    data = response.json()

    assert data["repository"] == "test-repository"
    assert data["repository_key"] == "test-repository-key"
    assert data["ready"] is True