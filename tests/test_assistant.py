from __future__ import annotations

from pathlib import Path

import pytest

from assistant import RepositoryAssistant
from workspace import RepositoryWorkspace


def create_test_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "test-repository"

    repository.mkdir()

    source = repository / "src"
    source.mkdir()

    (source / "main.py").write_text(
        "\n".join(
            [
                "def hello():",
                "    message = 'hello'",
                "    return message",
                "",
                "",
                "def goodbye():",
                "    return 'goodbye'",
            ]
        ),
        encoding="utf-8",
    )

    return repository


def test_cursor_context_reads_file(tmp_path):
    repository = create_test_repository(tmp_path)

    workspace = RepositoryWorkspace(repository)

    assistant = RepositoryAssistant.__new__(
        RepositoryAssistant
    )

    assistant.workspace = workspace

    context = assistant._build_cursor_context(
        file_path="src/main.py",
        cursor_line=2,
        cursor_column=10,
        selected_code="message = 'hello'",
    )

    assert context is not None
    assert context.file_path == "src/main.py"
    assert context.line == 2
    assert context.column == 10
    assert context.selected_code == "message = 'hello'"
    assert "message = 'hello'" in context.surrounding_code


def test_retrieval_query_without_cursor():
    query = RepositoryAssistant._build_retrieval_query(
        query="Explain Flask routing",
        cursor_context=None,
    )

    assert query == "Explain Flask routing"


def test_retrieval_query_with_cursor(tmp_path):
    repository = create_test_repository(tmp_path)

    workspace = RepositoryWorkspace(repository)

    assistant = RepositoryAssistant.__new__(
        RepositoryAssistant
    )

    assistant.workspace = workspace

    cursor = assistant._build_cursor_context(
        file_path="src/main.py",
        cursor_line=2,
        cursor_column=5,
        selected_code="message = 'hello'",
    )

    query = assistant._build_retrieval_query(
        query="Explain this",
        cursor_context=cursor,
    )

    assert "Explain this" in query
    assert "src/main.py" in query
    assert "message = 'hello'" in query