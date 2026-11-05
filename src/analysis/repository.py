from __future__ import annotations

import logging
import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from neo4j import AsyncGraphDatabase

from src.workspace import RepositoryWorkspace, WorkspaceError

logger = logging.getLogger(__name__)

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
IMPORTANT_FILES = {
    "readme.md",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "cargo.toml",
    "go.mod",
    "pom.xml",
    "dockerfile",
    "docker-compose.yml",
}
MAX_ANALYSIS_FILES = 80
MAX_CONTEXT_CHARS = 24000


class AnalysisError(RuntimeError):
    """Raised when a repository-grounded analysis cannot be completed."""


class RepositoryAnalysisService:
    def __init__(
        self,
        workspace: RepositoryWorkspace,
        repository_key: str,
        neo4j_uri: str | None = None,
        neo4j_user: str | None = None,
        neo4j_password: str | None = None,
        neo4j_database: str | None = None,
        repository_name: str | None = None,
    ) -> None:
        root = workspace.repository_path
        if root is None:
            raise AnalysisError("No repository is active.")
        self.workspace = workspace
        self.root = root
        self.repository_name = repository_name or root.name
        self.repository_key = repository_key
        self.neo4j_uri = neo4j_uri or os.environ.get(
            "NEO4J_URI", "neo4j://127.0.0.1:7687"
        )
        self.neo4j_user = neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
        self.neo4j_password = (
            neo4j_password
            if neo4j_password is not None
            else os.environ.get("NEO4J_PASSWORD", "")
        )
        self.neo4j_database = neo4j_database or os.environ.get(
            "NEO4J_DATABASE", "raca_graph"
        )

    def _files(self) -> list[str]:
        paths: list[str] = []
        for directory, dirnames, filenames in os.walk(
            self.root, followlinks=False
        ):
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name not in IGNORED_DIRECTORIES
                and not (Path(directory) / name).is_symlink()
            )
            for filename in filenames:
                file_path = Path(directory) / filename
                if file_path.is_symlink():
                    continue
                paths.append(file_path.relative_to(self.root).as_posix())
        return sorted(paths)

    @staticmethod
    def _readme_summary(content: str) -> str:
        paragraphs = [
            line.strip()
            for line in content.splitlines()
            if line.strip()
            and not line.lstrip().startswith(("#", "```", "![", "[!["))
        ]
        if not paragraphs:
            return ""
        summary = re.sub(r"[`*_~]", "", paragraphs[0])
        summary = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", summary)
        return summary[:320]

    @staticmethod
    def _safe_remote_url(root: Path) -> str | None:
        try:
            process = subprocess.run(
                ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if process.returncode != 0:
            return None
        remote = process.stdout.strip()
        if remote.startswith("git@") and ":" in remote:
            host, path = remote[4:].split(":", 1)
            return f"https://{host}/{path.removesuffix('.git')}"
        parsed = urlsplit(remote)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        clean_path = parsed.path.removesuffix(".git")
        return urlunsplit((parsed.scheme, parsed.hostname, clean_path, "", ""))

    def profile(self, index_status: dict[str, str]) -> dict[str, Any]:
        files = self._files()
        readme = next(
            (path for path in files if Path(path).name.lower() == "readme.md"),
            None,
        )
        summary = ""
        if readme:
            try:
                summary = self._readme_summary(
                    self.workspace.read_file(readme).content
                )
            except WorkspaceError:
                logger.info("README unavailable while preparing repository profile")
        return {
            "name": self.repository_name,
            "repository": self.repository_name,
            "url": self._safe_remote_url(self.root),
            "description": summary,
            "file_count": len(files),
            "status": index_status.get("status", "ready"),
            "index_message": index_status.get("message", ""),
        }

    def structure(self) -> dict[str, Any]:
        files = self._files()
        extensions = Counter(
            Path(path).suffix.lower() or "[no extension]" for path in files
        )
        top_level: dict[str, list[str]] = {}
        for path in files:
            parts = Path(path).parts
            if len(parts) > 1:
                top_level.setdefault(parts[0], []).append(path)
            else:
                top_level.setdefault(".", []).append(path)
        important = [
            path
            for path in files
            if Path(path).name.lower() in IMPORTANT_FILES
            or Path(path).name.lower().startswith(".env.")
        ]
        directory_count = 0
        for directory, dirnames, _ in os.walk(self.root, followlinks=False):
            dirnames[:] = [
                name
                for name in dirnames
                if name not in IGNORED_DIRECTORIES
                and not (Path(directory) / name).is_symlink()
            ]
            directory_count += len(dirnames)
        return {
            "file_count": len(files),
            "directory_count": directory_count,
            "languages": [
                {"extension": extension, "files": count}
                for extension, count in extensions.most_common(16)
            ],
            "important_files": important[:100],
            "top_level": [
                {
                    "name": name,
                    "files": len(paths),
                    "examples": paths[:12],
                }
                for name, paths in sorted(top_level.items())
            ],
        }

    async def graph_snapshot(self, limit: int = 160) -> dict[str, Any]:
        if not self.neo4j_password:
            raise AnalysisError("Neo4j credentials are not configured.")
        driver = AsyncGraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_user, self.neo4j_password),
        )
        try:
            result = await driver.execute_query(
                """
                MATCH (n {repository: $repository})
                OPTIONAL MATCH (n)-[r]-(m {repository: $repository})
                RETURN n.id AS id, n.kind AS kind, n.name AS name,
                       n.file_path AS file_path, n.start_line AS start_line,
                       n.end_line AS end_line, type(r) AS relation,
                       r.relation AS relation_name, m.id AS related_id,
                       m.kind AS related_kind, m.name AS related_name,
                       m.file_path AS related_file_path,
                       m.start_line AS related_start_line,
                       m.end_line AS related_end_line
                LIMIT $limit
                """,
                repository=self.repository_key,
                limit=limit,
                database_=self.neo4j_database,
            )
            return {
                "items": [record.data() for record in result.records],
                "truncated": len(result.records) >= limit,
            }
        except Exception as exc:
            logger.exception("Repository graph lookup failed")
            raise AnalysisError("Could not retrieve repository graph data.") from exc
        finally:
            await driver.close()

    async def relationships(self, query: str, limit: int = 80) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValueError("Enter a module, file, class, or symbol to explain.")
        if len(query) > 200:
            raise ValueError("Relationship query must be 200 characters or fewer.")
        if not self.neo4j_password:
            raise AnalysisError("Neo4j credentials are not configured.")
        driver = AsyncGraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_user, self.neo4j_password),
        )
        try:
            result = await driver.execute_query(
                """
                MATCH (n {repository: $repository})
                WHERE toLower(coalesce(n.name, '')) CONTAINS toLower($query)
                   OR toLower(coalesce(n.file_path, '')) CONTAINS toLower($query)
                OPTIONAL MATCH (n)-[r]-(m {repository: $repository})
                RETURN DISTINCT n.id AS id, n.kind AS kind, n.name AS name,
                       n.file_path AS file_path, n.start_line AS start_line,
                       type(r) AS relation, r.relation AS relation_name,
                       m.id AS related_id, m.kind AS related_kind,
                       m.name AS related_name, m.file_path AS related_file_path,
                       m.start_line AS related_start_line
                LIMIT $limit
                """,
                repository=self.repository_key,
                query=query,
                limit=limit,
                database_=self.neo4j_database,
            )
            items = [record.data() for record in result.records]
            return {"items": items, "truncated": len(items) >= limit}
        except Exception as exc:
            logger.exception("Module relationship lookup failed")
            raise AnalysisError("Could not retrieve module relationships.") from exc
        finally:
            await driver.close()

    async def graph_usages(self, symbol: str, limit: int = 120) -> list[dict[str, Any]]:
        symbol = symbol.strip()
        if not symbol:
            raise ValueError("Enter a symbol name.")
        if len(symbol) > 200:
            raise ValueError("Symbol search must be 200 characters or fewer.")
        if not self.neo4j_password:
            raise AnalysisError("Neo4j credentials are not configured.")
        driver = AsyncGraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_user, self.neo4j_password),
        )
        try:
            result = await driver.execute_query(
                """
                MATCH (n {repository: $repository})
                WHERE toLower(coalesce(n.name, '')) = toLower($symbol)
                   OR toLower(coalesce(n.name, '')) ENDS WITH toLower('.' + $symbol)
                CALL {
                    WITH n
                    OPTIONAL MATCH (other {repository: $repository})
                           -[r:RELATES_TO]->(n)
                    WHERE r.relation IN ['CALLS', 'IMPORTS']
                    RETURN collect(CASE WHEN other IS NULL THEN null ELSE {
                        file_path: other.file_path,
                        line: other.start_line,
                        name: other.name,
                        relation: r.relation,
                        direction: 'incoming'
                    } END) AS incoming
                }
                CALL {
                    WITH n
                    OPTIONAL MATCH (n)-[r:RELATES_TO]->
                           (other {repository: $repository})
                    WHERE r.relation IN ['CALLS', 'IMPORTS']
                    RETURN collect(CASE WHEN other IS NULL THEN null ELSE {
                        file_path: other.file_path,
                        line: other.start_line,
                        name: other.name,
                        relation: r.relation,
                        direction: 'outgoing'
                    } END) AS outgoing
                }
                RETURN n.name AS symbol, n.kind AS kind,
                       n.file_path AS definition_file,
                       n.start_line AS definition_line,
                       incoming + outgoing AS usages
                LIMIT $limit
                """,
                repository=self.repository_key,
                symbol=symbol,
                limit=limit,
                database_=self.neo4j_database,
            )
            usages: list[dict[str, Any]] = []
            for record in result.records:
                definition = record.get("definition_file")
                definition_line = record.get("definition_line")
                if definition and definition_line:
                    usages.append({
                        "file_path": definition,
                        "line": definition_line,
                        "kind": "definition",
                        "symbol": record.get("symbol"),
                    })
                for usage in record.get("usages", []):
                    if usage and usage.get("file_path") and usage.get("line"):
                        usages.append({
                            **usage,
                            "kind": str(usage.get("relation", "reference")).lower(),
                        })
            return usages
        except Exception as exc:
            logger.exception("Graph symbol usage lookup failed")
            raise AnalysisError("Could not retrieve graph symbol usages.") from exc
        finally:
            await driver.close()

    def architecture_context(self, structure: dict[str, Any], graph: dict[str, Any]) -> str:
        parts = [
            f"Repository: {self.repository_name}",
            f"Structure summary: {structure}",
            f"Observed graph records: {graph['items'][:100]}",
        ]
        remaining = MAX_CONTEXT_CHARS - sum(map(len, parts))
        for path in self._files():
            if remaining <= 500:
                break
            if (
                Path(path).name.lower() not in IMPORTANT_FILES
                and Path(path).suffix.lower()
                not in {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java"}
            ):
                continue
            try:
                file = self.workspace.read_file(path)
            except WorkspaceError:
                continue
            excerpt = file.content[: min(1800, remaining)]
            part = f"\nFILE {path}\n{excerpt}\n"
            parts.append(part)
            remaining -= len(part)
            if len(parts) >= MAX_ANALYSIS_FILES:
                break
        return "\n".join(parts)[:MAX_CONTEXT_CHARS]
