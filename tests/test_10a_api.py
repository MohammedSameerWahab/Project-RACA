from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import src.main as main_module
from src.generation.providers import PROVIDERS

app = main_module.app
pipeline = main_module.pipeline


async def skip_restore() -> None:
    return None


async def skip_close() -> None:
    return None


async def skip_embedding_preload() -> None:
    return None


def isolate_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "restore_existing_repository", skip_restore)
    monkeypatch.setattr(pipeline, "close", skip_close)
    monkeypatch.setattr(main_module, "preload_embedding_model", skip_embedding_preload)


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


def test_llm_model_options(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_lifespan(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/llm/models")

    assert response.status_code == 200
    data = response.json()
    assert [model["id"] for model in data["models"]] == [
        provider.id for provider in PROVIDERS
    ]
    assert data["default_model"] == next(
        (
            provider.id
            for provider in PROVIDERS
            if provider.is_configured()
        ),
        PROVIDERS[0].id,
    )


def test_embedding_model_is_preloaded_during_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_lifespan(monkeypatch)
    called = False

    async def record_preload() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(main_module, "preload_embedding_model", record_preload)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    assert called