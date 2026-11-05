import asyncio
from pathlib import Path

import pytest

from src.analysis import investigation as investigation_module
from src.analysis import repository as repository_module
from src.analysis.investigation import InvestigationService
from src.analysis.navigation import CodeNavigationService
from src.analysis.repository import RepositoryAnalysisService
from src.analysis.stacktrace import parse_stack_trace, resolve_stack_frames
from src.retrieval.hybrid import HybridSearchResult
from src.workspace import RepositoryWorkspace, WorkspacePathError


def create_repository(root: Path) -> RepositoryWorkspace:
    (root / "src").mkdir(parents=True)
    (root / "README.md").write_text(
        "# Sample project\nA small repository for service tests.\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    (root / ".env.example").write_text("API_KEY=\n", encoding="utf-8")
    (root / "src" / "main.py").write_text(
        "from src.worker import run_task\n\n"
        "class Service:\n"
        "    def execute(self):\n"
        "        return run_task()\n\n"
        "def run_task():\n"
        "    return 'done'\n",
        encoding="utf-8",
    )
    (root / "src" / "module.ts").write_text(
        "export function parseInput(value) { return value; }\n",
        encoding="utf-8",
    )
    return RepositoryWorkspace(root)


def services(root: Path):
    workspace = create_repository(root)
    return (
        workspace,
        RepositoryAnalysisService(
            workspace,
            "sample-key",
            repository_name="sample",
            neo4j_password="test",
        ),
        CodeNavigationService(workspace),
    )


def test_repository_profile_and_structure(tmp_path: Path) -> None:
    workspace, repository, _ = services(tmp_path)

    profile = repository.profile({"status": "ready", "message": "Indexed"})
    structure = repository.structure()

    assert profile["name"] == "sample"
    assert profile["description"] == "A small repository for service tests."
    assert profile["file_count"] == 5
    assert profile["status"] == "ready"
    assert structure["file_count"] == 5
    assert {item["extension"] for item in structure["languages"]} >= {
        ".py",
        ".md",
        ".toml",
        ".ts",
    }
    assert "pyproject.toml" in structure["important_files"]
    assert ".env.example" in structure["important_files"]
    assert workspace.repository_path == tmp_path.resolve()


def test_architecture_context_uses_real_files_and_graph_data(tmp_path: Path) -> None:
    _, repository, _ = services(tmp_path)
    context = repository.architecture_context(
        repository.structure(),
        {"items": [{"kind": "function", "name": "Service.execute"}], "truncated": False},
    )

    assert "FILE README.md" in context
    assert "src/main.py" in context
    assert "Service.execute" in context


def test_symbol_and_function_lookup(tmp_path: Path) -> None:
    _, _, navigation = services(tmp_path)

    implementations = navigation.definitions("Service")
    functions = navigation.definitions("run_task", kind="function")
    methods = navigation.definitions("execute", kind="method")
    generic = navigation.definitions("parseInput")

    assert implementations[0]["type"] == "class"
    assert functions[0]["line"] == 7
    assert methods[0]["qualified_name"] == "Service.execute"
    assert generic[0]["file_path"] == "src/module.ts"
    assert generic[0]["line"] == 1


def test_usages_detect_calls_and_imports(tmp_path: Path) -> None:
    _, _, navigation = services(tmp_path)

    results = navigation.usages("run_task")

    assert any(item["kind"] == "import" and item["line"] == 1 for item in results)
    assert any(item["kind"] == "call" and item["line"] == 5 for item in results)


def test_configuration_discovery_is_filesystem_based(tmp_path: Path) -> None:
    _, _, navigation = services(tmp_path)

    files = navigation.configurations()

    assert {"file_path": "pyproject.toml", "category": "Python / project"} in files
    assert {"file_path": ".env.example", "category": "Environment"} in files
    assert all(item["file_path"] != ".env" for item in files)


def test_source_navigation_rejects_traversal(tmp_path: Path) -> None:
    _, _, navigation = services(tmp_path)

    with pytest.raises(WorkspacePathError):
        navigation.source_excerpt("../../outside.py", 1)


def test_python_stack_trace_parsing_and_in_repository_resolution(
    tmp_path: Path,
) -> None:
    workspace, _, navigation = services(tmp_path)
    target = tmp_path / "src" / "main.py"
    trace = (
        f'Traceback (most recent call last):\n  File "{target}", line 5, in execute\n'
        '  File "C:\\Python\\Lib\\site-packages\\external.py", line 22, in call\n'
        "RuntimeError: task failed"
    )

    parsed = parse_stack_trace(trace)
    frames = resolve_stack_frames(parsed, navigation)

    assert parsed["exception_type"] == "RuntimeError"
    assert parsed["message"] == "task failed"
    assert frames[0]["file_path"] == "src/main.py"
    assert frames[0]["resolved"] is True
    assert frames[1]["resolved"] is False
    assert frames[1]["external"] is True
    assert workspace.repository_path == tmp_path.resolve()


def test_node_stack_trace_frame_parser() -> None:
    parsed = parse_stack_trace(
        "Error: bad input\n    at parse (src/index.js:12:8)"
    )

    assert parsed["exception_type"] == "Error"
    assert parsed["frames"] == [
        {
            "raw_path": "src/index.js",
            "line": 12,
            "column": 8,
            "function": "parse",
            "format": "node",
        }
    ]


class FakeLLM:
    async def generate_analysis(self, query: str, verified_context: str) -> str:
        assert verified_context
        return "Evidence-based analysis."


class FakeRetriever:
    async def search(self, query: str, top_k: int, retrieval_k: int):
        assert top_k > 0
        return [
            HybridSearchResult(
                repository="sample-key",
                filename="src/main.py",
                language="python",
                code="return run_task()",
                start_line=4,
                end_line=5,
                hybrid_score=0.82,
                graph_node="Service.execute",
            )
        ]


def test_likely_bug_locations_use_hybrid_evidence(tmp_path: Path) -> None:
    workspace, repository, navigation = services(tmp_path)
    service = InvestigationService(repository, navigation, FakeRetriever(), FakeLLM())

    result = asyncio.run(service.investigate_bug("Task fails on execution"))

    assert result["analysis"] == "Evidence-based analysis."
    assert result["candidates"][0]["file_path"] == "src/main.py"
    assert result["candidates"][0]["start_line"] == 4
    assert result["candidates"][0]["relevance"] == 0.82


def test_file_scoped_improvements_use_source_context(tmp_path: Path) -> None:
    workspace, repository, navigation = services(tmp_path)
    service = InvestigationService(repository, navigation, FakeRetriever(), FakeLLM())

    result = asyncio.run(
        service.suggest_improvements("file", file_path="src/main.py")
    )

    assert result["scope"] == "file"
    assert result["suggestions"] == "Evidence-based analysis."


def test_stack_trace_response_does_not_expose_external_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, repository, navigation = services(tmp_path)
    service = InvestigationService(repository, navigation, FakeRetriever(), FakeLLM())

    async def no_graph_neighbors(locations):
        return []

    monkeypatch.setattr(service, "_graph_neighbors", no_graph_neighbors)
    trace = (
        f'Traceback (most recent call last):\n  File "{tmp_path / "src" / "main.py"}", line 5, in execute\n'
        '  File "C:\\Python\\Lib\\site-packages\\external.py", line 22, in call\n'
        "RuntimeError: task failed"
    )

    result = asyncio.run(service.explain_stack_trace(trace))

    assert "raw_path" not in repr(result)
    assert "C:\\Python" not in repr(result)
    assert result["frames"][0]["file_path"] == "src/main.py"
    assert result["frames"][1]["external"] is True
    assert result["explanation"] == "Evidence-based analysis."


class FakeRecord(dict):
    def data(self):
        return dict(self)


class FakeGraphResult:
    def __init__(self, records):
        self.records = [FakeRecord(item) for item in records]


class FakeGraphDriver:
    def __init__(self, responses):
        self.responses = iter(responses)

    async def execute_query(self, cypher, **kwargs):
        return FakeGraphResult(next(self.responses))

    async def close(self):
        return None


def test_graph_relationships_and_usage_retrieval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, repository, _ = services(tmp_path)
    driver = FakeGraphDriver([
        [{
            "id": "function:sample-key:run_task",
            "kind": "function",
            "name": "run_task",
            "file_path": "src/main.py",
            "start_line": 7,
            "relation": "CALLS",
            "relation_name": "CALLS",
            "related_id": "function:sample-key:Service.execute",
            "related_kind": "function",
            "related_name": "Service.execute",
            "related_file_path": "src/main.py",
            "related_start_line": 4,
        }],
    ])
    monkeypatch.setattr(
        repository_module.AsyncGraphDatabase,
        "driver",
        lambda *args, **kwargs: driver,
    )

    relationships = asyncio.run(repository.relationships("run_task"))
    assert relationships["items"][0]["related_name"] == "Service.execute"

    usages_driver = FakeGraphDriver([
        [{
            "definition_file": "src/main.py",
            "definition_line": 7,
            "symbol": "run_task",
            "usages": [{
                "file_path": "src/main.py",
                "line": 5,
                "name": "Service.execute",
                "relation": "CALLS",
                "direction": "incoming",
            }],
        }],
    ])
    monkeypatch.setattr(
        repository_module.AsyncGraphDatabase,
        "driver",
        lambda *args, **kwargs: usages_driver,
    )
    usages = asyncio.run(repository.graph_usages("run_task"))
    assert {item["kind"] for item in usages} == {"definition", "calls"}
    assert usages[1]["line"] == 5


def test_execution_flow_uses_indexed_call_edges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, repository, navigation = services(tmp_path)
    driver = FakeGraphDriver([
        [{
            "id": "target-id",
            "kind": "function",
            "name": "run_task",
            "file_path": "src/main.py",
            "start_line": 7,
        }],
        [{
            "source": "caller-id",
            "target": "target-id",
            "source_name": "Service.execute",
            "source_kind": "function",
            "source_file": "src/main.py",
            "source_line": 4,
            "target_name": "run_task",
            "target_kind": "function",
            "target_file": "src/main.py",
            "target_line": 7,
        }],
        [],
    ])
    monkeypatch.setattr(
        investigation_module.AsyncGraphDatabase,
        "driver",
        lambda *args, **kwargs: driver,
    )
    service = InvestigationService(repository, navigation, FakeRetriever(), FakeLLM())

    result = asyncio.run(service.execution_flow("run_task"))

    assert result["edges"] == [
        {"source": "caller-id", "target": "target-id", "relation": "CALLS"}
    ]
    assert any(node["name"] == "Service.execute" for node in result["nodes"])
    assert result["explanation"] == "Evidence-based analysis."
