from pathlib import Path

from fastapi.testclient import TestClient

import src.main as main_module
from src.analysis.navigation import CodeNavigationService
from src.workspace import RepositoryWorkspace


def test_navigation_endpoints_return_actual_repository_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "main.py").write_text(
        "def process_request():\n    return True\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    navigation = CodeNavigationService(RepositoryWorkspace(tmp_path))

    async def skip_restore():
        return None

    async def skip_close():
        return None

    monkeypatch.setattr(main_module, "_navigation_service", lambda: navigation)
    monkeypatch.setattr(main_module.pipeline, "restore_existing_repository", skip_restore)
    monkeypatch.setattr(main_module.pipeline, "close", skip_close)

    with TestClient(main_module.app) as client:
        definition_response = client.get(
            "/api/navigation/function",
            params={"query": "process_request"},
        )
        configuration_response = client.get("/api/navigation/config")

    assert definition_response.status_code == 200
    definitions = definition_response.json()["results"]
    assert definitions[0]["file_path"] == "main.py"
    assert definitions[0]["line"] == 1
    assert configuration_response.status_code == 200
    assert configuration_response.json()["results"] == [
        {"file_path": "pyproject.toml", "category": "Python / project"}
    ]
