from __future__ import annotations

import ast
import os
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cocoindex as coco

from cocoindex.connectors import localfs, neo4j
from cocoindex.ops.text import detect_code_language
from cocoindex.resources.file import FileLike, PatternFilePathMatcher

from src.config import COCOINDEX_GRAPH_DB_PATH
from src.models.graph import CodeNode, CodeRelation


# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

REPOSITORY_PATH = os.environ["RACA_REPOSITORY_PATH"]

REPOSITORY_DIR = Path(REPOSITORY_PATH).resolve()
REPOSITORY_NAME = os.environ.get(
    "RACA_REPOSITORY_KEY",
    REPOSITORY_DIR.name,
)

NEO4J_URI = os.environ.get(
    "NEO4J_URI",
    "neo4j://127.0.0.1:7687",
)

NEO4J_USER = os.environ.get(
    "NEO4J_USER",
    "neo4j",
)

NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]

NEO4J_DATABASE = os.environ.get(
    "NEO4J_DATABASE",
    "raca_graph",
)
COCOINDEX_GRAPH_STATE_PATH = Path(
    os.environ.get(
        "RACA_COCOINDEX_GRAPH_DB_PATH",
        str(COCOINDEX_GRAPH_DB_PATH),
    )
)


# -------------------------------------------------------------------
# CocoIndex shared resource
# -------------------------------------------------------------------

KG_DB = coco.ContextKey[
    neo4j.ConnectionFactory
]("raca_graph_db")


# -------------------------------------------------------------------
# Internal extraction structures
# -------------------------------------------------------------------

@dataclass
class Definition:
    """A Python function or class definition."""

    kind: str
    name: str
    qualname: str
    start_line: int
    end_line: int


@dataclass
class Call:
    """A function call made from another function."""

    caller: str
    callee: str
    line: int


class PythonGraphCollector(ast.NodeVisitor):
    """
    Extract simple structural relationships from Python code.

    Current relationships:
        - class/function definitions
        - imports
        - function calls
    """

    def __init__(self) -> None:
        self.scope: list[str] = []
        self.current_function: str | None = None

        self.definitions: list[Definition] = []
        self.imports: list[str] = []
        self.calls: list[Call] = []

    def visit_ClassDef(
        self,
        node: ast.ClassDef,
    ) -> None:
        qualname = ".".join(
            [*self.scope, node.name]
        )

        self.definitions.append(
            Definition(
                kind="class",
                name=node.name,
                qualname=qualname,
                start_line=node.lineno,
                end_line=getattr(
                    node,
                    "end_lineno",
                    node.lineno,
                ),
            )
        )

        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(
        self,
        node: ast.FunctionDef,
    ) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:
        self._visit_function(node)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        qualname = ".".join(
            [*self.scope, node.name]
        )

        self.definitions.append(
            Definition(
                kind="function",
                name=node.name,
                qualname=qualname,
                start_line=node.lineno,
                end_line=getattr(
                    node,
                    "end_lineno",
                    node.lineno,
                ),
            )
        )

        previous_function = self.current_function

        self.scope.append(node.name)
        self.current_function = qualname

        self.generic_visit(node)

        self.scope.pop()
        self.current_function = previous_function

    def visit_Import(
        self,
        node: ast.Import,
    ) -> None:
        for alias in node.names:
            self.imports.append(alias.name)

        self.generic_visit(node)

    def visit_ImportFrom(
        self,
        node: ast.ImportFrom,
    ) -> None:
        module = node.module or ""

        relative_prefix = "." * node.level

        self.imports.append(
            f"{relative_prefix}{module}"
        )

        self.generic_visit(node)

    def visit_Call(
        self,
        node: ast.Call,
    ) -> None:
        if self.current_function is not None:
            callee = self._get_call_name(
                node.func
            )

            if callee:
                self.calls.append(
                    Call(
                        caller=self.current_function,
                        callee=callee,
                        line=node.lineno,
                    )
                )

        self.generic_visit(node)

    @staticmethod
    def _get_call_name(
        node: ast.expr,
    ) -> str | None:
        if isinstance(node, ast.Name):
            return node.id

        if isinstance(node, ast.Attribute):
            return node.attr

        return None


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def make_node_id(
    kind: str,
    name: str,
) -> str:
    """Create a stable graph node ID."""
    return (
        f"{kind}:"
        f"{REPOSITORY_NAME}:"
        f"{name}"
    )


def make_relation_id(
    source_id: str,
    target_id: str,
    relation: str,
) -> str:
    """Create a stable relationship ID."""
    return (
        f"{relation}:"
        f"{source_id}:"
        f"{target_id}"
    )


# -------------------------------------------------------------------
# CocoIndex lifecycle
# -------------------------------------------------------------------

@coco.lifespan
async def coco_lifespan(
    builder: coco.EnvironmentBuilder,
) -> AsyncIterator[None]:
    """
    Configure CocoIndex state and Neo4j connection.
    """

    builder.settings.db_path = COCOINDEX_GRAPH_STATE_PATH

    builder.provide(
        KG_DB,
        neo4j.ConnectionFactory(
            uri=NEO4J_URI,
            auth=(
                NEO4J_USER,
                NEO4J_PASSWORD,
            ),
            database=NEO4J_DATABASE,
        ),
    )

    yield


# -------------------------------------------------------------------
# Process one Python file
# -------------------------------------------------------------------

@coco.fn(memo=True)
async def process_file(
    file: FileLike,
    node_table: neo4j.TableTarget[CodeNode],
    relation_table: neo4j.RelationTarget[CodeRelation],
) -> None:
    """
    Convert one Python file into graph nodes and relationships.
    """

    text = await file.read_text()

    relative_path = file.file_path.path.relative_to(
        REPOSITORY_DIR
    ).as_posix()

    language = detect_code_language(
        filename=str(
            file.file_path.path.name
        )
    )

    # ---------------------------------------------------------------
    # Every indexed file becomes a FILE node.
    # ---------------------------------------------------------------

    file_node_id = make_node_id(
        "file",
        relative_path,
    )

    line_count = text.count("\n") + 1

    node_table.declare_record(
        row=CodeNode(
            id=file_node_id,
            repository=REPOSITORY_NAME,
            kind="file",
            name=relative_path,
            file_path=relative_path,
            start_line=1,
            end_line=line_count,
        )
    )

    # ---------------------------------------------------------------
    # Initial graph implementation is Python-specific.
    # ---------------------------------------------------------------

    if language != "python":
        return

    try:
        tree = ast.parse(
            text,
            filename=str(
                file.file_path.path
            ),
        )
    except SyntaxError:
        return

    collector = PythonGraphCollector()
    collector.visit(tree)

    # ---------------------------------------------------------------
    # Create definition nodes (functions, classes).
    # ---------------------------------------------------------------

    definition_nodes_by_qualname: dict[
        str,
        list[tuple[str, Definition]]
    ] = defaultdict(list)

    for definition in collector.definitions:
        node_id = make_node_id(
            definition.kind,
            f"{relative_path}:"
            f"{definition.qualname}:"
            f"L{definition.start_line}",
        )

        definition_nodes_by_qualname[
            definition.qualname
        ].append((node_id, definition))

        node_table.declare_record(
            row=CodeNode(
                id=node_id,
                repository=REPOSITORY_NAME,
                kind=definition.kind,
                name=definition.qualname,
                file_path=relative_path,
                start_line=definition.start_line,
                end_line=definition.end_line,
            )
        )

        relation_table.declare_relation(
            from_id=file_node_id,
            to_id=node_id,
            record=CodeRelation(
                id=make_relation_id(
                    file_node_id,
                    node_id,
                    "CONTAINS",
                ),
                relation="CONTAINS",
            ),
        )

    # ---------------------------------------------------------------
    # Create IMPORTS relationships.
    # Scope module IDs to relative_path to prevent concurrent locking collisions.
    # ---------------------------------------------------------------

    seen_imports: set[str] = set()

    for module_name in collector.imports:
        if not module_name:
            continue

        if module_name in seen_imports:
            continue

        seen_imports.add(module_name)

        module_node_id = make_node_id(
            "module",
            f"{relative_path}:{module_name}",
        )

        node_table.declare_record(
            row=CodeNode(
                id=module_node_id,
                repository=REPOSITORY_NAME,
                kind="module",
                name=module_name,
                file_path=relative_path,
                start_line=0,
                end_line=0,
            )
        )

        relation_table.declare_relation(
            from_id=file_node_id,
            to_id=module_node_id,
            record=CodeRelation(
                id=make_relation_id(
                    file_node_id,
                    module_node_id,
                    "IMPORTS",
                ),
                relation="IMPORTS",
            ),
        )

    # ---------------------------------------------------------------
    # Build a lookup for function/class names.
    # ---------------------------------------------------------------

    definitions_by_short_name: dict[
        str,
        list[tuple[str, Definition]]
    ] = defaultdict(list)

    for entries in definition_nodes_by_qualname.values():
        for node_id, definition in entries:
            definitions_by_short_name[
                definition.name
            ].append((node_id, definition))

    # ---------------------------------------------------------------
    # Create CALLS relationships.
    # ---------------------------------------------------------------

    seen_calls: set[tuple[str, str]] = set()

    for call in collector.calls:
        candidates = definitions_by_short_name.get(
            call.callee,
            [],
        )

        if len(candidates) != 1:
            continue

        target_id, target_definition = candidates[0]

        caller_id: str | None = None
        caller_candidates = definition_nodes_by_qualname.get(call.caller, [])

        for candidate_id, candidate_def in caller_candidates:
            if candidate_def.start_line <= call.line <= candidate_def.end_line:
                caller_id = candidate_id
                break

        if caller_id is None and caller_candidates:
            caller_id = caller_candidates[0][0]

        if caller_id is None:
            continue

        key = (
            caller_id,
            target_id,
        )

        if key in seen_calls:
            continue

        seen_calls.add(key)

        relation_table.declare_relation(
            from_id=caller_id,
            to_id=target_id,
            record=CodeRelation(
                id=make_relation_id(
                    caller_id,
                    target_id,
                    "CALLS",
                ),
                relation="CALLS",
            ),
        )


# -------------------------------------------------------------------
# Main graph indexing function
# -------------------------------------------------------------------

@coco.fn
async def app_main(
    sourcedir: Path,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Build the repository structure graph."""

    node_table = await neo4j.mount_table_target(
        KG_DB,
        table_name="CodeNode",
        table_schema=await neo4j.TableSchema.from_class(
            CodeNode,
            primary_key="id",
        ),
        primary_key="id",
    )

    relation_table = await neo4j.mount_relation_target(
        KG_DB,
        table_name="RELATES_TO",
        from_table=node_table,
        to_table=node_table,
        table_schema=await neo4j.TableSchema.from_class(
            CodeRelation,
            primary_key="id",
        ),
        primary_key="id",
    )

    files = localfs.walk_dir(
        sourcedir,
        recursive=True,
        path_matcher=PatternFilePathMatcher(
            included_patterns=[
                "**/*.py",
                "**/*.js",
                "**/*.jsx",
                "**/*.ts",
                "**/*.tsx",
                "**/*.java",
                "**/*.c",
                "**/*.h",
                "**/*.cpp",
                "**/*.hpp",
                "**/*.rs",
                "**/*.go",
                "**/*.cs",
                "**/*.rb",
                "**/*.php",
                "**/*.swift",
                "**/*.kt",
                "**/*.kts",
                "**/*.scala",
                "**/*.sh",
                "**/*.sql",
                "**/*.html",
                "**/*.css",
                "**/*.scss",
                "**/*.json",
                "**/*.yaml",
                "**/*.yml",
                "**/*.toml",
                "**/*.md",
                "**/*.mdx",
            ],
            excluded_patterns=[
                "**/.git/**",
                "**/.venv/**",
                "**/venv/**",
                "**/__pycache__/**",
                "**/node_modules/**",
                "**/dist/**",
                "**/build/**",
            ],
        ),
        live=True,
    )

    await coco.mount_each(
        process_file,
        files.items(),
        node_table,
        relation_table,
    )


# -------------------------------------------------------------------
# CocoIndex application
# -------------------------------------------------------------------

app = coco.App(
    coco.AppConfig(
        name=os.environ.get(
            "RACA_GRAPH_FLOW_NAME",
            "RACA_CodeGraph",
        ),
    ),
    app_main,
    lifespan=coco_lifespan,
    sourcedir=REPOSITORY_DIR,
)