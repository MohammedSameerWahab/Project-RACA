from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
import subprocess

from dotenv import load_dotenv

load_dotenv()

import asyncpg
from neo4j import AsyncGraphDatabase

from src.ingestion.github import clone_repository
from src.workspace import RepositoryWorkspace
from src.assistant import RepositoryAssistant




PROJECT_ROOT = Path(__file__).resolve().parent.parent

POSTGRES_TABLE = "raca_code_embeddings"

COCOINDEX_STATE = PROJECT_ROOT / "data" / "cocoindex.db"
COCOINDEX_GRAPH_STATE = PROJECT_ROOT / "data" / "cocoindex_graph.db"
REPOSITORIES_DIR = PROJECT_ROOT / "data" / "repositories"

INDEX_FLOW_SCRIPT = PROJECT_ROOT / "src" / "indexing" / "index_flow.py"
GRAPH_SCRIPT = PROJECT_ROOT / "src" / "indexing" / "graph.py"


class PipelineError(RuntimeError):
    """Raised when repository ingestion or cleanup fails."""


@dataclass(frozen=True)
class IngestionResult:
    repository: str
    local_path: Path
    postgres_indexed: bool
    neo4j_indexed: bool


@dataclass(frozen=True)
class ClearResult:
    postgres_deleted: int
    neo4j_deleted: int
    repositories_deleted: int
    state_files_deleted: int


class RACAPipeline:
    """
    Application-level orchestration for Project RACA.

    Phase 10A responsibilities:
        - ingest one GitHub repository
        - run the existing PostgreSQL indexer
        - run the existing Neo4j graph indexer
        - completely clear the active RACA workspace

    Repository isolation is intentionally NOT implemented here yet.
    """

    def __init__(self) -> None:
        self._operation_lock = asyncio.Lock()
        self._current_repository: str | None = None

        self.postgres_url = os.environ.get("POSTGRES_URL")

        self._assistant = None

        self.neo4j_uri = os.environ.get(
            "NEO4J_URI",
            "neo4j://127.0.0.1:7687",
        )
        self.neo4j_user = os.environ.get(
            "NEO4J_USER",
            "neo4j",
        )
        self.neo4j_password = os.environ.get(
            "NEO4J_PASSWORD",
        )
        self.neo4j_database = os.environ.get(
            "NEO4J_DATABASE",
            "raca_graph",
        )

        self.workspace = RepositoryWorkspace()

        # self.assistant = RepositoryAssistant(self.workspace)



        REPOSITORIES_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )


    @property
    def assistant(self) -> RepositoryAssistant:
        if self._assistant is None:
            self._assistant = RepositoryAssistant(self.workspace)
        return self._assistant

    async def restore_existing_repository(self) -> None:
        if not self.postgres_url:
            raise PipelineError("POSTGRES_URL is not configured.")

        conn = await asyncpg.connect(self.postgres_url)

        try:
            rows = await conn.fetch(
                """
                SELECT DISTINCT repository
                FROM raca_code_embeddings
                ORDER BY repository
                """
            )
        finally:
            await conn.close()

        if not rows:
            return

        repositories = [row["repository"] for row in rows]

        if len(repositories) > 1:
            raise PipelineError(
                "Multiple repositories are present in the database. "
                "Repository isolation must be implemented before automatic "
                "workspace restoration can safely select one."
            )

        repository_name = repositories[0]
        repository_path = REPOSITORIES_DIR / repository_name

        if not repository_path.exists() or not repository_path.is_dir():
            raise PipelineError(
                f"Indexed repository '{repository_name}' was found in PostgreSQL "
                "but its local repository directory is missing."
            )

        self._current_repository = repository_name
        self.workspace.set_repository(repository_path)

        os.environ["RACA_REPOSITORY_PATH"] = str(
            repository_path.resolve()
        )

        # Force creation of retrieval/LLM components only after the
        # active repository environment has been established.
        self._assistant = None

    @property
    def current_repository(self) -> str | None:
        """
        Return the repository currently known by this application process.

        A repository is considered active only after both indexing stages
        complete successfully.
        """
        return self._current_repository

    async def ingest_repository(
        self,
        github_url: str,
    ) -> IngestionResult:
        """
        Clone and index one GitHub repository.

        Sequence:
            GitHub
              -> local repository
              -> PostgreSQL indexing
              -> Neo4j graph indexing
        """

        if not github_url.strip():
            raise ValueError(
                "GitHub repository URL cannot be empty."
            )

        self._validate_environment()

        async with self._operation_lock:
            if self._current_repository is not None:
                raise PipelineError(
                    "A repository is already active. "
                    "Clear the workspace before ingesting another repository."
                )
            postgres_indexed = False
            neo4j_indexed = False
            local_path: Path | None = None

        try:
            local_path = await asyncio.to_thread(
                clone_repository,
                github_url,
                REPOSITORIES_DIR,
            )

            repository_name = local_path.name

            # -----------------------------------------------------
            # PostgreSQL / semantic + keyword indexing
            # -----------------------------------------------------

            await self._run_cocoindex(
                INDEX_FLOW_SCRIPT,
                local_path,
            )


            postgres_count = await self._get_postgres_repository_count(
                repository_name
            )

            if postgres_count == 0:
                raise PipelineError(
                    f"PostgreSQL indexing completed but no chunks "
                    f"were found for repository '{repository_name}'."
                )

            postgres_indexed = True

            # -----------------------------------------------------
            # Neo4j graph indexing
            # -----------------------------------------------------

            await self._run_cocoindex(
                GRAPH_SCRIPT,
                local_path,
            )

            neo4j_count = await self._get_neo4j_repository_count(
                repository_name
            )

            if neo4j_count == 0:
                raise PipelineError(
                    f"Neo4j indexing completed but no graph nodes "
                    f"were found for repository '{repository_name}'."
                )

            neo4j_indexed = True

            async def _get_neo4j_repository_count(
                self,
                repository_name: str,
            ) -> int:
                driver = AsyncGraphDatabase.driver(
                    self.neo4j_uri,
                    auth=(
                        self.neo4j_user,
                        self.neo4j_password,
                    ),
                )

                try:
                    async with driver.session(
                        database=self.neo4j_database
                    ) as session:
                        result = await session.run(
                            """
                            MATCH (n {repository: $repository})
                            RETURN count(n) AS count
                            """,
                            repository=repository_name,
                        )

                        record = await result.single()

                        return int(record["count"]) if record else 0

                finally:
                    await driver.close()

            self._current_repository = repository_name
            self.workspace.set_repository(local_path)

            # Make the active repository available to retrieval
            # modules in the FastAPI process as well.
            os.environ["RACA_REPOSITORY_PATH"] = str(
                local_path.resolve()
            )

            return IngestionResult(
                repository=repository_name,
                local_path=local_path,
                postgres_indexed=postgres_indexed,
                neo4j_indexed=neo4j_indexed,
            )

        except Exception as exc:
            import traceback

            traceback.print_exc()

            if local_path is not None and local_path.exists():
                try:
                    await asyncio.to_thread(
                        shutil.rmtree,
                        local_path,
                    )
                except Exception:
                    pass

            self._current_repository = None
            self.workspace.clear_repository()
            os.environ.pop("RACA_REPOSITORY_PATH", None)

            raise PipelineError(
                f"Repository ingestion failed: {type(exc).__name__}: {exc!r}"
            ) from exc
    async def clear_workspace(self) -> ClearResult:
        """
        Completely clear the current RACA workspace.

        This deliberately clears ALL currently indexed repository data.

        It does NOT:
            - drop the PostgreSQL database
            - drop the PostgreSQL table
            - drop PostgreSQL indexes
            - stop PostgreSQL
            - stop Neo4j
            - delete the Neo4j database

        It only removes RACA's stored repository data and local indexing
        state so another repository can be ingested cleanly.
        """

        self._validate_environment()

        async with self._operation_lock:
            postgres_deleted = await self._clear_postgres()

            neo4j_deleted = await self._clear_neo4j()

            repositories_deleted = await asyncio.to_thread(
                self._clear_local_repositories
            )

            state_files_deleted = await asyncio.to_thread(
                self._clear_cocoindex_state
            )

            self._current_repository = None

            self.workspace.clear_repository()

            os.environ.pop("RACA_REPOSITORY_PATH", None,)

            self._assistant = None

            return ClearResult(
                postgres_deleted=postgres_deleted,
                neo4j_deleted=neo4j_deleted,
                repositories_deleted=repositories_deleted,
                state_files_deleted=state_files_deleted,
            )

    async def _run_cocoindex(
        self,
        script_path: Path,
        repository_path: Path,
    ) -> None:
        """
        Run one of the existing CocoIndex applications.

        The indexing scripts are executed in a worker thread so that
        subprocess handling works correctly with the Windows asyncio
        environment used by FastAPI/Uvicorn.
        """

        if not script_path.exists():
            raise PipelineError(
                f"CocoIndex script not found: {script_path}"
            )

        environment = os.environ.copy()

        environment["RACA_REPOSITORY_PATH"] = str(
            repository_path.resolve()
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
            )

        process = await asyncio.to_thread(run_process)

        output = process.stdout

        if process.returncode != 0:
            tail = output[-8000:]

            raise PipelineError(
                "CocoIndex execution failed.\n\n"
                f"Script: {script_path.name}\n"
                f"Exit code: {process.returncode}\n\n"
                f"Output:\n{tail}"
            )
        
    async def _clear_postgres(self) -> int:
        """
        Delete all indexed code/embedding rows.

        The table itself and all of its indexes remain intact.
        """

        pool = await asyncpg.create_pool(
            self.postgres_url,
        )

        try:
            async with pool.acquire() as connection:
                result = await connection.execute(
                    f'DELETE FROM "{POSTGRES_TABLE}"'
                )
        finally:
            await pool.close()

        # PostgreSQL returns strings such as "DELETE 123".
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    async def _clear_neo4j(self) -> int:
        """
        Delete all graph nodes and their relationships.

        The Neo4j database itself remains running and intact.
        """

        driver = AsyncGraphDatabase.driver(
            self.neo4j_uri,
            auth=(
                self.neo4j_user,
                self.neo4j_password,
            ),
        )

        try:
            async with driver.session(
                database=self.neo4j_database,
            ) as session:
                result = await session.run(
                    """
                    MATCH (n)
                    DETACH DELETE n
                    RETURN count(n) AS deleted_nodes
                    """
                )

                record = await result.single()

                if record is None:
                    return 0

                return int(
                    record["deleted_nodes"]
                )

        finally:
            await driver.close()

    @staticmethod
    def _clear_local_repositories() -> int:
        """
        Remove every cloned repository from data/repositories/.
        """

        if not REPOSITORIES_DIR.exists():
            return 0

        deleted = 0

        for path in REPOSITORIES_DIR.iterdir():
            if path.is_dir():
                shutil.rmtree(path)
                deleted += 1
            else:
                path.unlink()
                deleted += 1

        return deleted

    @staticmethod
    def _clear_cocoindex_state() -> int:
        """
        Remove CocoIndex's local state databases.

        They will be recreated automatically during the next indexing run.
        """

        deleted = 0

        for state_file in (
            COCOINDEX_STATE,
            COCOINDEX_GRAPH_STATE,
        ):
            if state_file.exists():
                state_file.unlink()
                deleted += 1

        return deleted

    def _validate_environment(self) -> None:
        if not self.postgres_url:
            raise PipelineError(
                "POSTGRES_URL environment variable is not set."
            )

        if not self.neo4j_password:
            raise PipelineError(
                "NEO4J_PASSWORD environment variable is not set."
            )

    async def _get_postgres_repository_count(
        self,
        repository_name: str,
    ) -> int:
        if not self.postgres_url:
            raise PipelineError("POSTGRES_URL is not configured.")

        conn = await asyncpg.connect(self.postgres_url)

        try:
            return await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM raca_code_embeddings
                WHERE repository = $1
                """,
                repository_name,
            )
        finally:
            await conn.close()