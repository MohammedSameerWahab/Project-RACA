from pathlib import Path

import pytest

from src.workspace import (
    RepositoryWorkspace,
    WorkspaceFileError,
    WorkspacePathError,
)


def create_test_repository(
    tmp_path: Path,
) -> Path:
    repository = (
        tmp_path / "test-repository"
    )

    src = repository / "src"

    src.mkdir(
        parents=True
    )

    (src / "main.py").write_text(
        "print('hello')\n",
        encoding="utf-8",
    )

    (repository / "README.md").write_text(
        "# Test Repository\n",
        encoding="utf-8",
    )

    (repository / ".env").write_text(
        "SECRET=value\n",
        encoding="utf-8",
    )

    return repository


def test_get_tree(
    tmp_path: Path,
) -> None:
    repository = create_test_repository(
        tmp_path
    )

    workspace = RepositoryWorkspace(
        repository
    )

    tree = workspace.get_tree()

    names = {
        entry.name
        for entry in tree.children or []
    }

    assert "src" in names
    assert "README.md" in names
    assert ".env" in names


def test_read_file(
    tmp_path: Path,
) -> None:
    repository = create_test_repository(
        tmp_path
    )

    workspace = RepositoryWorkspace(
        repository
    )

    file = workspace.read_file(
        "src/main.py"
    )

    assert file.name == "main.py"
    assert file.extension == ".py"
    assert file.content == (
        "print('hello')\n"
    )


def test_reject_absolute_path(
    tmp_path: Path,
) -> None:
    repository = create_test_repository(
        tmp_path
    )

    workspace = RepositoryWorkspace(
        repository
    )

    with pytest.raises(
        WorkspacePathError
    ):
        workspace.read_file(
            str(
                tmp_path / "outside.txt"
            )
        )


def test_reject_path_traversal(
    tmp_path: Path,
) -> None:
    repository = create_test_repository(
        tmp_path
    )

    workspace = RepositoryWorkspace(
        repository
    )

    with pytest.raises(
        WorkspacePathError
    ):
        workspace.read_file(
            "../../outside.txt"
        )


def test_missing_file(
    tmp_path: Path,
) -> None:
    repository = create_test_repository(
        tmp_path
    )

    workspace = RepositoryWorkspace(
        repository
    )

    with pytest.raises(
        WorkspaceFileError
    ):
        workspace.read_file(
            "does-not-exist.py"
        )


def test_write_file(
    tmp_path: Path,
) -> None:
    repository = create_test_repository(tmp_path)
    workspace = RepositoryWorkspace(repository)

    saved_file = workspace.write_file(
        "src/main.py",
        "print('updated')\n",
    )

    assert saved_file.content == "print('updated')\n"
    assert (repository / "src" / "main.py").read_text(
        encoding="utf-8"
    ) == "print('updated')\n"


def test_write_file_rejects_path_traversal(
    tmp_path: Path,
) -> None:
    repository = create_test_repository(tmp_path)
    workspace = RepositoryWorkspace(repository)

    with pytest.raises(WorkspacePathError):
        workspace.write_file("../../outside.txt", "unsafe")


def test_write_file_rejects_oversized_content(
    tmp_path: Path,
) -> None:
    repository = create_test_repository(tmp_path)
    workspace = RepositoryWorkspace(repository)

    with pytest.raises(WorkspaceFileError, match="too large"):
        workspace.write_file(
            "src/main.py",
            "x" * (workspace.MAX_FILE_SIZE + 1),
        )