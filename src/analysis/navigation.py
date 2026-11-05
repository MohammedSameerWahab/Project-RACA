from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

from src.analysis.repository import AnalysisError, IGNORED_DIRECTORIES
from src.workspace import RepositoryWorkspace, WorkspaceError

CONFIG_NAMES = {
    ".env": "Environment",
    ".env.example": "Environment",
    ".env.sample": "Environment",
    "pyproject.toml": "Python / project",
    "requirements.txt": "Python / project",
    "setup.py": "Python / project",
    "package.json": "Frontend / JavaScript",
    "tsconfig.json": "Frontend / TypeScript",
    "dockerfile": "Docker / deployment",
    "docker-compose.yml": "Docker / deployment",
    "docker-compose.yaml": "Docker / deployment",
    "compose.yml": "Docker / deployment",
    "compose.yaml": "Docker / deployment",
    "makefile": "Build",
}
SYMBOL_PATTERN = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*\Z")


class CodeNavigationService:
    def __init__(self, workspace: RepositoryWorkspace) -> None:
        if workspace.repository_path is None:
            raise AnalysisError("No repository is active.")
        self.workspace = workspace
        self.root = workspace.repository_path

    def _files(self) -> list[str]:
        results: list[str] = []
        for directory, dirnames, filenames in os.walk(self.root, followlinks=False):
            dirnames[:] = [
                name
                for name in dirnames
                if name not in IGNORED_DIRECTORIES
                and not (Path(directory) / name).is_symlink()
            ]
            for name in filenames:
                path = Path(directory) / name
                if not path.is_symlink():
                    results.append(path.relative_to(self.root).as_posix())
        return sorted(results)

    @staticmethod
    def _python_symbols(path: str, content: str) -> list[dict[str, Any]]:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []
        symbols: list[dict[str, Any]] = []

        class Visitor(ast.NodeVisitor):
            scopes: list[str] = []

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                symbols.append({
                    "name": node.name,
                    "qualified_name": ".".join([*self.scopes, node.name]),
                    "type": "class",
                    "file_path": path,
                    "line": node.lineno,
                    "end_line": node.end_lineno or node.lineno,
                })
                self.scopes.append(node.name)
                self.generic_visit(node)
                self.scopes.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self._function(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self._function(node)

            def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
                symbols.append({
                    "name": node.name,
                    "qualified_name": ".".join([*self.scopes, node.name]),
                    "type": "method" if self.scopes else "function",
                    "file_path": path,
                    "line": node.lineno,
                    "end_line": node.end_lineno or node.lineno,
                })
                self.scopes.append(node.name)
                self.generic_visit(node)
                self.scopes.pop()

        Visitor().visit(tree)
        return symbols

    @staticmethod
    def _generic_symbols(path: str, content: str) -> list[dict[str, Any]]:
        pattern = re.compile(
            r"^\s*(?:export\s+)?(?:default\s+)?"
            r"(?:async\s+)?(function|class|interface|type|enum)\s+"
            r"([A-Za-z_$][A-Za-z0-9_$]*)",
            re.MULTILINE,
        )
        results = []
        for match in pattern.finditer(content):
            line = content.count("\n", 0, match.start()) + 1
            results.append({
                "name": match.group(2),
                "qualified_name": match.group(2),
                "type": match.group(1).lower(),
                "file_path": path,
                "line": line,
                "end_line": line,
            })
        return results

    def definitions(self, query: str, kind: str | None = None) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            raise ValueError("Enter a symbol name.")
        if len(query) > 200:
            raise ValueError("Symbol search must be 200 characters or fewer.")
        matches: list[dict[str, Any]] = []
        for path in self._files():
            if Path(path).suffix.lower() not in {
                ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"
            }:
                continue
            try:
                content = self.workspace.read_file(path).content
            except WorkspaceError:
                continue
            found = (
                self._python_symbols(path, content)
                if Path(path).suffix.lower() == ".py"
                else self._generic_symbols(path, content)
            )
            lines = content.splitlines()
            for item in found:
                if query.lower() not in item["name"].lower() and query.lower() not in item["qualified_name"].lower():
                    continue
                if kind and item["type"] != kind:
                    continue
                item["preview"] = "\n".join(
                    lines[max(0, item["line"] - 2): min(len(lines), item["line"] + 5)]
                )
                matches.append(item)
        matches.sort(key=lambda item: (item["file_path"].lower(), item["line"]))
        return matches[:100]

    def usages(self, query: str) -> list[dict[str, Any]]:
        query = query.strip()
        if not SYMBOL_PATTERN.fullmatch(query):
            raise ValueError("Enter a valid symbol identifier.")
        results: list[dict[str, Any]] = []
        for path in self._files():
            if Path(path).suffix.lower() not in {
                ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".c", ".h"
            }:
                continue
            try:
                content = self.workspace.read_file(path).content
            except WorkspaceError:
                continue
            lines = content.splitlines()
            if path.endswith(".py"):
                try:
                    tree = ast.parse(content)
                except SyntaxError:
                    tree = None
                if tree is not None:
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call):
                            name = node.func.id if isinstance(node.func, ast.Name) else (
                                node.func.attr if isinstance(node.func, ast.Attribute) else None
                            )
                            if name == query:
                                results.append(self._usage(path, lines, node.lineno, "call"))
                        elif isinstance(node, ast.Import):
                            for alias in node.names:
                                if query in {alias.name, alias.name.split(".")[-1], alias.asname}:
                                    results.append(self._usage(path, lines, node.lineno, "import"))
                        elif isinstance(node, ast.ImportFrom):
                            for alias in node.names:
                                if query in {alias.name, alias.asname}:
                                    results.append(self._usage(path, lines, node.lineno, "import"))
            # Textual fallback catches references outside the Python call/import AST.
            for number, line in enumerate(lines, 1):
                if re.search(rf"(?<![\w$]){re.escape(query)}(?![\w$])", line):
                    if not any(item["file_path"] == path and item["line"] == number for item in results):
                        results.append(self._usage(path, lines, number, "reference"))
        results.sort(key=lambda item: (item["file_path"].lower(), item["line"]))
        return results[:300]

    @staticmethod
    def _usage(path: str, lines: list[str], number: int, kind: str) -> dict[str, Any]:
        return {
            "file_path": path,
            "line": number,
            "kind": kind,
            "preview": lines[number - 1].strip()[:300] if number <= len(lines) else "",
        }

    def configurations(self) -> list[dict[str, str]]:
        results = []
        for path in self._files():
            name = Path(path).name.lower()
            category = CONFIG_NAMES.get(name)
            if category is None and (
                name.startswith(".env.")
                or Path(path).suffix.lower() in {".toml", ".ini", ".yaml", ".yml", ".json"}
            ):
                category = {
                    ".toml": "Project configuration",
                    ".ini": "Project configuration",
                    ".yaml": "Project configuration",
                    ".yml": "Project configuration",
                    ".json": "Project configuration",
                }.get(Path(path).suffix.lower(), "Environment")
            if category is None and (
                name in {"config.py", "settings.py"}
                or "config" in Path(path).parts[:-1]
                or "settings" in Path(path).parts[:-1]
            ):
                category = "Application configuration"
            if category:
                results.append({"file_path": path, "category": category})
        return results

    def source_excerpt(self, path: str, line: int, radius: int = 4) -> dict[str, Any]:
        file = self.workspace.read_file(path)
        lines = file.content.splitlines()
        if line < 1 or line > max(len(lines), 1):
            raise ValueError("Source line is outside the file.")
        start = max(1, line - radius)
        end = min(len(lines), line + radius)
        return {
            "file_path": file.path,
            "line": line,
            "start_line": start,
            "end_line": end,
            "code": "\n".join(
                f"{number}: {lines[number - 1]}"
                for number in range(start, end + 1)
            ),
        }
