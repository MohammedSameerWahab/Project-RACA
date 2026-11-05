from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class WorkspaceError(RuntimeError):
    """Base exception for repository workspace errors."""


class WorkspaceNotReadyError(WorkspaceError):
    """Raised when no repository has been indexed."""


class WorkspacePathError(WorkspaceError):
    """Raised when a requested path is invalid or outside the repository."""


class WorkspaceFileError(WorkspaceError):
    """Raised when a repository file cannot be read."""


@dataclass(frozen=True)
class WorkspaceFile:
    path: str
    name: str
    extension: str
    size: int
    content: str


@dataclass(frozen=True)
class WorkspaceEntry:
    name: str
    path: str
    type: str
    children: list["WorkspaceEntry"] | None = None


class RepositoryWorkspace:
    """
    Read-only access to the currently active repository.

    This phase deliberately does not allow file modification.
    """

    IGNORED_DIRECTORIES = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        "target",
    }

    MAX_FILE_SIZE = 2 * 1024 * 1024

    def __init__(
        self,
        repository_path: Path | None = None,
    ) -> None:
        self._repository_path = (
            repository_path.resolve()
            if repository_path is not None
            else None
        )

    @property
    def repository_path(self) -> Path | None:
        return self._repository_path

    def set_repository(
        self,
        repository_path: Path,
    ) -> None:
        resolved = repository_path.resolve()

        if not resolved.exists():
            raise WorkspaceError(
                f"Repository does not exist: {resolved}"
            )

        if not resolved.is_dir():
            raise WorkspaceError(
                f"Repository path is not a directory: {resolved}"
            )

        self._repository_path = resolved

    def clear_repository(self) -> None:
        self._repository_path = None

    def get_tree(self) -> WorkspaceEntry:
        root = self._require_repository()

        return WorkspaceEntry(
            name=root.name,
            path="",
            type="directory",
            children=self._build_tree(root, root),
        )

    def read_file(
        self,
        relative_path: str,
    ) -> WorkspaceFile:
        root = self._require_repository()

        file_path = self._resolve_safe_path(
            relative_path
        )

        if not file_path.exists():
            raise WorkspaceFileError(
                f"File does not exist: {relative_path}"
            )

        if not file_path.is_file():
            raise WorkspaceFileError(
                f"Path is not a file: {relative_path}"
            )

        file_size = file_path.stat().st_size

        if file_size > self.MAX_FILE_SIZE:
            raise WorkspaceFileError(
                f"File is too large to open. "
                f"Maximum size is "
                f"{self.MAX_FILE_SIZE} bytes."
            )

        try:
            content = file_path.read_text(
                encoding="utf-8"
            )
        except UnicodeDecodeError as exc:
            raise WorkspaceFileError(
                f"File is not a supported UTF-8 text file: "
                f"{relative_path}"
            ) from exc
        except OSError as exc:
            raise WorkspaceFileError(
                f"Could not read file: {relative_path}"
            ) from exc

        normalized_path = file_path.relative_to(
            root
        ).as_posix()

        return WorkspaceFile(
            path=normalized_path,
            name=file_path.name,
            extension=file_path.suffix.lower(),
            size=file_size,
            content=content,
        )

    def _build_tree(
        self,
        directory: Path,
        root: Path,
    ) -> list[WorkspaceEntry]:
        entries: list[WorkspaceEntry] = []

        try:
            children = sorted(
                directory.iterdir(),
                key=lambda path: (
                    not path.is_dir(),
                    path.name.lower(),
                ),
            )
        except OSError as exc:
            raise WorkspaceError(
                f"Could not read directory: {directory}"
            ) from exc

        for path in children:
            if (
                path.is_dir()
                and path.name in self.IGNORED_DIRECTORIES
            ):
                continue

            relative_path = path.relative_to(
                root
            ).as_posix()

            if path.is_dir():
                entries.append(
                    WorkspaceEntry(
                        name=path.name,
                        path=relative_path,
                        type="directory",
                        children=self._build_tree(
                            path,
                            root,
                        ),
                    )
                )
            else:
                entries.append(
                    WorkspaceEntry(
                        name=path.name,
                        path=relative_path,
                        type="file",
                    )
                )

        return entries

    def _resolve_safe_path(
        self,
        relative_path: str,
    ) -> Path:
        root = self._require_repository()

        if not relative_path.strip():
            raise WorkspacePathError(
                "File path cannot be empty."
            )

        requested = Path(relative_path)

        if requested.is_absolute():
            raise WorkspacePathError(
                "Absolute file paths are not allowed."
            )

        candidate = (
            root / requested
        ).resolve()

        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise WorkspacePathError(
                "Requested path is outside the repository."
            ) from exc

        return candidate

    def _require_repository(self) -> Path:
        if self._repository_path is None:
            raise WorkspaceNotReadyError(
                "No repository is currently active."
            )

        if not self._repository_path.exists():
            raise WorkspaceNotReadyError(
                "The active repository no longer exists."
            )

        return self._repository_path