from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

import asyncpg
from neo4j import AsyncGraphDatabase

from src.assistant import (
    AssistantNotReadyError,
    RepositoryAssistant,
)
from src.config import (
    COCOINDEX_DB_PATH,
    COCOINDEX_GRAPH_DB_PATH,
    DATA_DIR,
    REPOSITORIES_DIR,
)
from src.ingestion.github import (
    GitHubRepositoryError,
    clone_repository,
    get_repository_name,
)
from src.workspace import RepositoryWorkspace, WorkspaceFile

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
POSTGRES_TABLE = "raca_code_embeddings"
ACTIVE_REPOSITORY_FILE = DATA_DIR / "active_repository.json"
INDEX_STATE_DIR = DATA_DIR / "cocoindex_state"
INDEX_FLOW_SCRIPT = PROJECT_ROOT / "src" / "indexing" / "index_flow.py"
GRAPH_SCRIPT = PROJECT_ROOT / "src" / "indexing" / "graph.py"
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _validate_table_name(table_name: str) -> str:
    if len(table_name) > 63 or not _IDENTIFIER_PATTERN.fullmatch(table_name):
        raise ValueError(f"Invalid PostgreSQL table name: {table_name!r}")
    return table_name


@dataclass(frozen=True)
class RepositoryIndex:
    repository: str
    repository_key: str
    local_path: Path
    postgres_table: str
    cocoindex_state: Path
    graph_state: Path
    legacy: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["local_path"] = str(self.local_path)
        data["cocoindex_state"] = str(self.cocoindex_state)
        data["graph_state"] = str(self.graph_state)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepositoryIndex:
        repository = str(data["repository"])
        repository_key = str(data["repository_key"])
        local_path = Path(data["local_path"]).resolve()
        postgres_table = _validate_table_name(
            str(data["postgres_table"])
        )
        cocoindex_state = Path(data["cocoindex_state"]).resolve()
        graph_state = Path(data["graph_state"]).resolve()
        legacy = bool(data.get("legacy", False))

        if not re.fullmatch(r"[A-Za-z0-9._-]+", repository):
            raise ValueError("Invalid repository name in active index manifest.")

        if legacy:
            if (
                postgres_table != POSTGRES_TABLE
                or local_path != (REPOSITORIES_DIR / repository).resolve()
                or cocoindex_state != COCOINDEX_DB_PATH.resolve()
                or graph_state != COCOINDEX_GRAPH_DB_PATH.resolve()
                or repository_key != repository
            ):
                raise ValueError("Invalid legacy repository manifest paths.")
        else:
            match = re.fullmatch(
                r"raca_code_embeddings_([0-9a-f]{32})",
                postgres_table,
            )
            if match is None:
                raise ValueError("Invalid repository table in manifest.")
            index_id = match.group(1)
            if (
                repository_key != f"{repository}-{index_id}"
                or local_path
                != (REPOSITORIES_DIR / f"{repository}-{index_id}").resolve()
                or cocoindex_state
                != (INDEX_STATE_DIR / index_id / "cocoindex.db").resolve()
                or graph_state
                != (INDEX_STATE_DIR / index_id / "cocoindex_graph.db").resolve()
            ):
                raise ValueError("Invalid staged repository manifest paths.")

        return cls(
            repository=repository,
            repository_key=repository_key,
            local_path=local_path,
            postgres_table=postgres_table,
            cocoindex_state=cocoindex_state,
            graph_state=graph_state,
            legacy=legacy,
        )


@dataclass(frozen=True)
class IngestionResult:
    repository: str
    repository_key: str
    local_path: Path
    postgres_indexed: bool
    neo4j_indexed: bool
    cleanup_warning: str | None = None


@dataclass(frozen=True)
class ClearResult:
    postgres_deleted: int
    neo4j_deleted: int
    repositories_deleted: int
    state_files_deleted: int


class PipelineError(RuntimeError):
    """Raised when repository ingestion or cleanup fails."""


class RACAPipeline:
    """Orchestrate safe repository replacement and incremental indexing."""

    def __init__(self) -> None:
        self._operation_lock = asyncio.Lock()
        self._active_index: RepositoryIndex | None = None
        self._pending_cleanup: list[RepositoryIndex] = []
        self._assistant: RepositoryAssistant | None = None
        self._sync_task: asyncio.Task[None] | None = None
        self._refresh_requested = False
        self._closing = False
        self._index_status: dict[str, str] = {
            "status": "idle",
            "message": "No index refresh is pending.",
            "updated_at": self._now(),
        }

        self.postgres_url = os.environ.get("POSTGRES_URL")
        self.neo4j_uri = os.environ.get(
            "NEO4J_URI",
            "neo4j://127.0.0.1:7687",
        )
        self.neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
        self.neo4j_password = os.environ.get("NEO4J_PASSWORD")
        self.neo4j_database = os.environ.get(
            "NEO4J_DATABASE",
            "raca_graph",
        )

        self.workspace = RepositoryWorkspace()
        REPOSITORIES_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @property
    def current_repository(self) -> str | None:
        if self._active_index is None:
            return None
        return self._active_index.repository

    @property
    def current_repository_key(self) -> str | None:
        if self._active_index is None:
            return None
        return self._active_index.repository_key

    @property
    def assistant(self) -> RepositoryAssistant:
        active = self._active_index
        if active is None:
            raise AssistantNotReadyError("No repository is currently active.")

        if self._assistant is None:
            self._assistant = RepositoryAssistant(
                self.workspace,
                database_url=self.postgres_url,
                repository_key=active.repository_key,
                table_name=active.postgres_table,
            )
        return self._assistant

    def index_status(self) -> dict[str, str]:
        return dict(self._index_status)

    async def restore_existing_repository(self) -> None:
        """Restore the active index, including legacy single-repository data."""
        self._validate_environment()

        if ACTIVE_REPOSITORY_FILE.is_file():
            try:
                manifest = json.loads(
                    ACTIVE_REPOSITORY_FILE.read_text(encoding="utf-8")
                )
                active = RepositoryIndex.from_dict(manifest["active"])
                pending = [
                    RepositoryIndex.from_dict(item)
                    for item in manifest.get("pending_cleanup", [])
                ]
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise PipelineError(
                    f"Could not read repository index manifest: {exc}"
                ) from exc

            self._validate_repository_path(active.local_path)
            self._active_index = active
            self._pending_cleanup = pending
            self.workspace.set_repository(active.local_path)
            self._assistant = None

            try:
                await self._validate_index(active)
            except Exception:
                self._active_index = None
                self.workspace.clear_repository()
                raise

            await self._finish_pending_cleanup()
            return

        legacy = await self._restore_legacy_repository()
        if legacy is not None:
            self._active_index = legacy
            self.workspace.set_repository(legacy.local_path)

    async def _restore_legacy_repository(self) -> RepositoryIndex | None:
        conn = await asyncpg.connect(self.postgres_url)
        try:
            rows = await conn.fetch(
                f"""
                SELECT DISTINCT repository
                FROM "{POSTGRES_TABLE}"
                ORDER BY repository
                """
            )
        except asyncpg.UndefinedTableError:
            return None
        finally:
            await conn.close()

        repositories = [str(row["repository"]) for row in rows]
        if not repositories:
            return None
        if len(repositories) != 1:
            raise PipelineError(
                "The legacy index contains multiple repositories. "
                "It was left untouched because the active repository is ambiguous."
            )

        repository = repositories[0]
        local_path = (REPOSITORIES_DIR / repository).resolve()
        self._validate_repository_path(local_path)
        if not local_path.is_dir():
            raise PipelineError(
                f"Indexed repository '{repository}' has no local clone at {local_path}."
            )

        return RepositoryIndex(
            repository=repository,
            repository_key=repository,
            local_path=local_path,
            postgres_table=POSTGRES_TABLE,
            cocoindex_state=COCOINDEX_DB_PATH.resolve(),
            graph_state=COCOINDEX_GRAPH_DB_PATH.resolve(),
            legacy=True,
        )

    async def ingest_repository(self, github_url: str) -> IngestionResult:
        """Build isolated indexes, switch only after validation, then retire old data."""
        if not github_url.strip():
            raise ValueError("GitHub repository URL cannot be empty.")
        self._validate_environment()

        async with self._operation_lock:
            if self._active_index is None:
                await self.restore_existing_repository()

            repository_name = get_repository_name(github_url.strip())
            repository_uuid = uuid.uuid4().hex
            repository_key = f"{repository_name}-{repository_uuid}"
            postgres_table = f"raca_code_embeddings_{repository_uuid}"
            state_dir = INDEX_STATE_DIR / repository_uuid
            local_path: Path | None = None
            staged = RepositoryIndex(
                repository=repository_name,
                repository_key=repository_key,
                local_path=REPOSITORIES_DIR / f"{repository_name}-{repository_uuid}",
                postgres_table=postgres_table,
                cocoindex_state=state_dir / "cocoindex.db",
                graph_state=state_dir / "cocoindex_graph.db",
            )
            previous = self._active_index
            indexing_started = False

            self._index_status = self._status(
                "cloning",
                f"Cloning {repository_name}. The current repository remains available.",
            )

            try:
                local_path = await asyncio.to_thread(
                    clone_repository,
                    github_url.strip(),
                    REPOSITORIES_DIR,
                    staged.local_path.name,
                )
                staged = RepositoryIndex(
                    repository=repository_name,
                    repository_key=repository_key,
                    local_path=local_path.resolve(),
                    postgres_table=postgres_table,
                    cocoindex_state=staged.cocoindex_state,
                    graph_state=staged.graph_state,
                )
                staged.cocoindex_state.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                self._index_status = self._status(
                    "indexing",
                    f"Building semantic, keyword, and graph indexes for {repository_name}.",
                )
                indexing_started = True
                await self._run_index_flows(staged)
                await self._validate_index(staged)

            except Exception as exc:
                cleanup_error = await self._discard_staged_repository(
                    staged,
                    local_path,
                    clean_indexes=indexing_started,
                )
                self._index_status = self._status(
                    "error",
                    f"Indexing {repository_name} failed: {exc}",
                )
                if cleanup_error:
                    raise PipelineError(
                        f"Repository indexing failed: {exc}. "
                        f"Staging cleanup also failed: {cleanup_error}"
                    ) from exc
                if isinstance(exc, (ValueError, GitHubRepositoryError)):
                    raise
                raise PipelineError(
                    f"Repository indexing failed: {exc}"
                ) from exc

            previous_pending = self._pending_cleanup
            pending_cleanup = [*previous_pending]
            if previous is not None and previous != staged:
                pending_cleanup.append(previous)

            self.workspace.set_repository(staged.local_path)
            self._active_index = staged
            self._pending_cleanup = pending_cleanup
            try:
                self._write_manifest()
            except Exception as exc:
                self._active_index = previous
                self._pending_cleanup = previous_pending
                if previous is None:
                    self.workspace.clear_repository()
                else:
                    self.workspace.set_repository(previous.local_path)
                self._assistant = None
                cleanup_error = await self._discard_staged_repository(
                    staged,
                    local_path,
                    clean_indexes=True,
                )
                self._index_status = self._status(
                    "error",
                    f"Could not activate {repository_name}: {exc}",
                )
                if cleanup_error:
                    raise PipelineError(
                        f"Could not activate {repository_name}: {exc}. "
                        f"Staging cleanup also failed: {cleanup_error}"
                    ) from exc
                raise PipelineError(
                    f"Could not activate {repository_name}: {exc}"
                ) from exc

            self._assistant = None

            cleanup_warning = await self._finish_pending_cleanup()
            self._index_status = self._status(
                "ready",
                (
                    f"{repository_name} is indexed and ready."
                    if cleanup_warning is None
                    else f"{repository_name} is ready; previous-index cleanup is pending: "
                    f"{cleanup_warning}"
                ),
            )

            return IngestionResult(
                repository=staged.repository,
                repository_key=staged.repository_key,
                local_path=staged.local_path,
                postgres_indexed=True,
                neo4j_indexed=True,
                cleanup_warning=cleanup_warning,
            )

    async def _run_index_flows(self, repository: RepositoryIndex) -> None:
        await self._run_cocoindex(INDEX_FLOW_SCRIPT, repository)
        await self._run_cocoindex(GRAPH_SCRIPT, repository)

    async def _run_cocoindex(
        self,
        script_path: Path,
        repository: RepositoryIndex,
    ) -> None:
        if not script_path.is_file():
            raise PipelineError(f"CocoIndex script not found: {script_path}")

        environment = os.environ.copy()
        environment.update(
            {
                "RACA_REPOSITORY_PATH": str(repository.local_path.resolve()),
                "RACA_REPOSITORY_KEY": repository.repository_key,
                "RACA_POSTGRES_TABLE": repository.postgres_table,
                "RACA_COCOINDEX_DB_PATH": str(repository.cocoindex_state),
                "RACA_COCOINDEX_GRAPH_DB_PATH": str(repository.graph_state),
                "RACA_CODE_FLOW_NAME": (
                    "RACA_CodeIndex"
                    if repository.legacy
                    else f"RACA_CodeIndex_{repository.postgres_table.rsplit('_', 1)[-1]}"
                ),
                "RACA_GRAPH_FLOW_NAME": (
                    "RACA_CodeGraph"
                    if repository.legacy
                    else f"RACA_CodeGraph_{repository.postgres_table.rsplit('_', 1)[-1]}"
                ),
                "RACA_FTS_INDEX_NAME": (
                    "raca_code_fts_idx"
                    if repository.legacy
                    else f"raca_code_fts_{repository.postgres_table.rsplit('_', 1)[-1]}"
                ),
            }
        )

        command = [
            "uv",
            "run",
            "cocoindex",
            "update",
            str(script_path.relative_to(PROJECT_ROOT)),
        ]

        def run_process() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

        process = await asyncio.to_thread(run_process)
        if process.returncode:
            output = (process.stdout + "\n" + process.stderr)[-8000:]
            raise PipelineError(
                f"CocoIndex execution failed for {script_path.name} "
                f"(exit {process.returncode}).\n{output}"
            )

    async def _validate_index(self, repository: RepositoryIndex) -> None:
        count = await self._get_postgres_repository_count(
            repository.postgres_table,
            repository.repository_key,
        )
        if count <= 0:
            raise PipelineError(
                f"PostgreSQL index for '{repository.repository}' contains no chunks."
            )

        graph_count = await self._get_neo4j_repository_count(
            repository.repository_key
        )
        if graph_count <= 0:
            raise PipelineError(
                f"Neo4j index for '{repository.repository}' contains no nodes."
            )

    async def _get_postgres_repository_count(
        self,
        table_name: str,
        repository_key: str,
    ) -> int:
        table_name = _validate_table_name(table_name)
        conn = await asyncpg.connect(self.postgres_url)
        try:
            count = await conn.fetchval(
                f'SELECT COUNT(*) FROM "{table_name}" WHERE repository = $1',
                repository_key,
            )
            return int(count or 0)
        finally:
            await conn.close()

    async def _get_neo4j_repository_count(
        self,
        repository_key: str,
    ) -> int:
        driver = AsyncGraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_user, self.neo4j_password),
        )
        try:
            async with driver.session(database=self.neo4j_database) as session:
                result = await session.run(
                    """
                    MATCH (n {repository: $repository})
                    RETURN count(n) AS count
                    """,
                    repository=repository_key,
                )
                record = await result.single()
                return int(record["count"]) if record else 0
        finally:
            await driver.close()

    def _status(self, status: str, message: str) -> dict[str, str]:
        return {
            "status": status,
            "message": message,
            "updated_at": self._now(),
        }

    def _write_manifest(self) -> None:
        if self._active_index is None:
            if ACTIVE_REPOSITORY_FILE.exists():
                ACTIVE_REPOSITORY_FILE.unlink()
            return

        manifest = {
            "active": self._active_index.to_dict(),
            "pending_cleanup": [
                repository.to_dict()
                for repository in self._pending_cleanup
            ],
        }
        temporary_path = ACTIVE_REPOSITORY_FILE.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, ACTIVE_REPOSITORY_FILE)

    def _validate_repository_path(self, path: Path) -> None:
        resolved = path.resolve()
        try:
            resolved.relative_to(REPOSITORIES_DIR.resolve())
        except ValueError as exc:
            raise PipelineError(
                "Repository path in the active index is outside data/repositories."
            ) from exc

    async def _finish_pending_cleanup(self) -> str | None:
        remaining: list[RepositoryIndex] = []
        errors: list[str] = []

        for repository in self._pending_cleanup:
            try:
                await self._cleanup_repository(repository)
            except Exception as exc:
                logger.exception(
                    "Could not remove previous repository index %s",
                    repository.repository,
                )
                remaining.append(repository)
                errors.append(f"{repository.repository}: {exc}")

        self._pending_cleanup = remaining
        if self._active_index is not None:
            try:
                self._write_manifest()
            except OSError as exc:
                logger.exception("Could not persist pending cleanup state")
                errors.append(f"manifest update failed: {exc}")
        return "; ".join(errors) or None

    async def _cleanup_repository(self, repository: RepositoryIndex) -> tuple[int, int, int, int]:
        self._validate_repository_path(repository.local_path)
        postgres_deleted = await self._delete_postgres_rows(repository)
        neo4j_deleted = await self._delete_neo4j_nodes(repository.repository_key)

        repository_deleted = 0
        if repository.local_path.exists():
            await asyncio.to_thread(shutil.rmtree, repository.local_path)
            repository_deleted = 1

        states_deleted = 0
        for state_path in (
            repository.cocoindex_state,
            repository.graph_state,
        ):
            if self._remove_state_path(state_path):
                states_deleted += 1

        state_parent = repository.cocoindex_state.parent
        if state_parent != repository.graph_state.parent:
            self._remove_state_path(repository.graph_state.parent)
        if not repository.legacy:
            self._remove_state_path(state_parent)
        if not repository.legacy:
            await self._drop_postgres_table(repository.postgres_table)

        return postgres_deleted, neo4j_deleted, repository_deleted, states_deleted

    async def _discard_staged_repository(
        self,
        repository: RepositoryIndex,
        local_path: Path | None,
        clean_indexes: bool = True,
    ) -> str | None:
        errors: list[str] = []
        if clean_indexes:
            try:
                await self._delete_neo4j_nodes(repository.repository_key)
            except Exception as exc:
                errors.append(f"Neo4j staging cleanup failed: {exc}")

            try:
                await self._drop_postgres_table(repository.postgres_table)
            except Exception as exc:
                errors.append(f"PostgreSQL staging cleanup failed: {exc}")

        for state_path in (
            repository.cocoindex_state,
            repository.graph_state,
        ):
            try:
                self._remove_state_path(state_path)
            except OSError as exc:
                errors.append(f"CocoIndex state cleanup failed: {exc}")
        try:
            self._remove_state_path(repository.cocoindex_state.parent)
        except OSError as exc:
            errors.append(f"CocoIndex state directory cleanup failed: {exc}")

        if local_path is not None:
            try:
                self._validate_repository_path(local_path)
                if local_path.exists():
                    await asyncio.to_thread(shutil.rmtree, local_path)
            except OSError as exc:
                errors.append(f"Staging clone cleanup failed: {exc}")
        return "; ".join(errors) or None

    @staticmethod
    def _remove_state_path(path: Path) -> bool:
        resolved = path.resolve()
        try:
            resolved.relative_to(DATA_DIR.resolve())
        except ValueError as exc:
            raise PipelineError(
                "Refusing to remove a CocoIndex state path outside the data directory."
            ) from exc
        if resolved == DATA_DIR.resolve() or not resolved.exists():
            return False
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        return True

    async def _delete_postgres_rows(self, repository: RepositoryIndex) -> int:
        table_name = _validate_table_name(repository.postgres_table)
        conn = await asyncpg.connect(self.postgres_url)
        try:
            try:
                result = await conn.execute(
                    f'DELETE FROM "{table_name}" WHERE repository = $1',
                    repository.repository_key,
                )
            except asyncpg.UndefinedTableError:
                return 0
        finally:
            await conn.close()
        return int(result.split()[-1]) if result.startswith("DELETE ") else 0

    async def _drop_postgres_table(self, table_name: str) -> None:
        table_name = _validate_table_name(table_name)
        if table_name == POSTGRES_TABLE:
            raise PipelineError("Refusing to drop the legacy shared index table.")
        conn = await asyncpg.connect(self.postgres_url)
        try:
            await conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        finally:
            await conn.close()

    async def _delete_neo4j_nodes(self, repository_key: str) -> int:
        driver = AsyncGraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_user, self.neo4j_password),
        )
        try:
            async with driver.session(database=self.neo4j_database) as session:
                result = await session.run(
                    """
                    MATCH (n {repository: $repository})
                    DETACH DELETE n
                    RETURN count(n) AS deleted_nodes
                    """,
                    repository=repository_key,
                )
                record = await result.single()
                return int(record["deleted_nodes"]) if record else 0
        finally:
            await driver.close()

    def queue_index_refresh(self) -> dict[str, str]:
        if self._active_index is None:
            raise PipelineError("No repository is currently active.")

        self._refresh_requested = True
        self._index_status = self._status(
            "queued",
            "Saved file queued for incremental indexing.",
        )
        if self._sync_task is None or self._sync_task.done():
            self._start_index_refresh()
        return self.index_status()

    def _start_index_refresh(self) -> None:
        task = asyncio.create_task(self._refresh_indexes_after_save())
        self._sync_task = task
        task.add_done_callback(self._on_index_refresh_done)

    def _on_index_refresh_done(
        self,
        task: asyncio.Task[None],
    ) -> None:
        if self._sync_task is not task:
            return
        self._sync_task = None
        if self._refresh_requested and not self._closing:
            self._start_index_refresh()

    async def save_file(
        self,
        relative_path: str,
        content: str,
        expected_repository_key: str,
    ) -> WorkspaceFile:
        async with self._operation_lock:
            active = self._active_index
            if active is None:
                raise PipelineError("No repository is currently active.")
            if active.repository_key != expected_repository_key:
                raise PipelineError(
                    "The active repository changed. Reload the file before saving."
                )

            saved_file = self.workspace.write_file(
                relative_path,
                content,
            )
            self.queue_index_refresh()
            return saved_file

    async def _refresh_indexes_after_save(self) -> None:
        try:
            await asyncio.sleep(0.75)
            async with self._operation_lock:
                self._refresh_requested = False
                active = self._active_index
                if active is None:
                    raise PipelineError(
                        "Repository was cleared before the save could be indexed."
                    )

                self._index_status = self._status(
                    "indexing",
                    "Updating semantic, keyword, and graph indexes from saved files.",
                )
                await self._run_index_flows(active)
                await self._validate_index(active)
                self._index_status = self._status(
                    "ready",
                    "Saved files are indexed and searchable.",
                )
        except Exception as exc:
            logger.exception("Background CocoIndex refresh failed")
            self._index_status = self._status(
                "error",
                f"Background index refresh failed: {exc}",
            )

    async def clear_workspace(self) -> ClearResult:
        """Clear only the active repository's data; never truncate shared databases."""
        async with self._operation_lock:
            active = self._active_index
            if active is None:
                return ClearResult(0, 0, 0, 0)

            postgres_deleted, neo4j_deleted, repositories_deleted, states_deleted = (
                await self._cleanup_repository(active)
            )
            self._active_index = None
            self._pending_cleanup = []
            self.workspace.clear_repository()
            self._assistant = None
            self._write_manifest()
            self._index_status = self._status("idle", "No active repository.")
            return ClearResult(
                postgres_deleted=postgres_deleted,
                neo4j_deleted=neo4j_deleted,
                repositories_deleted=repositories_deleted,
                state_files_deleted=states_deleted,
            )

    async def close(self) -> None:
        self._closing = True
        if self._sync_task is not None and not self._sync_task.done():
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        if self._assistant is not None:
            await self._assistant.llm.close()
            self._assistant = None

    def _validate_environment(self) -> None:
        if not self.postgres_url:
            raise PipelineError("POSTGRES_URL environment variable is not set.")
        if not self.neo4j_password:
            raise PipelineError("NEO4J_PASSWORD environment variable is not set.")
