from __future__ import annotations

import logging
from typing import Any

from neo4j import AsyncGraphDatabase

from src.analysis.navigation import CodeNavigationService
from src.analysis.repository import AnalysisError, RepositoryAnalysisService
from src.analysis.stacktrace import parse_stack_trace, resolve_stack_frames
from src.generation.llm import LLMGenerator
from src.generation.providers import DEFAULT_MODEL
from src.retrieval.hybrid import HybridRetriever
from src.workspace import WorkspaceError

logger = logging.getLogger(__name__)
MAX_RETRIEVAL_RESULTS = 8
MAX_EXECUTION_NODES = 60
MAX_EXECUTION_DEPTH = 2


class InvestigationService:
    def __init__(
        self,
        repository: RepositoryAnalysisService,
        navigation: CodeNavigationService,
        retriever: HybridRetriever,
        llm: LLMGenerator,
        model: str | None = None,
    ) -> None:
        self.repository = repository
        self.navigation = navigation
        self.retriever = retriever
        self.llm = llm
        self.model = model or DEFAULT_MODEL

    async def explain_architecture(self) -> dict[str, Any]:
        structure = self.repository.structure()
        graph = await self.repository.graph_snapshot()
        context = self.repository.architecture_context(structure, graph)
        relevant = await self.retriever.search(
            "repository architecture main entry points components dependencies data flow",
            top_k=8,
            retrieval_k=16,
        )
        if relevant:
            context += "\n\nRelevant hybrid-retrieval source chunks:\n" + "\n".join(
                f"FILE {item.filename}:{item.start_line}-{item.end_line}\n{item.code[:1800]}"
                for item in relevant
            )
            context = context[:24000]
        explanation = await self.llm.generate_analysis(
            "Explain this repository's architecture, major components, "
            "entry points, dependencies, and main data flow. Separate facts "
            "supported by the supplied context from any uncertainty.",
            context,
            model=self.model,
        )
        return {
            "explanation": explanation,
            "structure": structure,
            "graph_records": len(graph["items"]),
            "graph_truncated": graph["truncated"],
        }

    async def explain_relationships(self, query: str) -> dict[str, Any]:
        graph = await self.repository.relationships(query)
        if not graph["items"]:
            return {"explanation": "", "relationships": [], "message": "No indexed relationships matched."}
        source_context = []
        seen: set[str] = set()
        for item in graph["items"]:
            for path, line in (
                (item.get("file_path"), item.get("start_line")),
                (item.get("related_file_path"), item.get("related_start_line")),
            ):
                if path and path not in seen and line:
                    seen.add(path)
                    try:
                        source_context.append(
                            self.navigation.source_excerpt(path, int(line))["code"]
                        )
                    except (WorkspaceError, ValueError):
                        continue
        context = (
            f"Repository: {self.repository.repository_name}\n"
            f"Actual indexed graph relationships: {graph['items']}\n"
            f"Verified source excerpts:\n{'\n'.join(source_context)[:12000]}"
        )
        explanation = await self.llm.generate_analysis(
            f"Explain how the repository components related to {query!r} "
            "interact. Use only the graph edges and source excerpts as facts. "
            "Mention limitations where graph data is incomplete.",
            context,
            model=self.model,
        )
        return {
            "explanation": explanation,
            "relationships": graph["items"],
            "truncated": graph["truncated"],
        }

    async def investigate_bug(
        self,
        description: str,
        file_path: str | None = None,
        selected_code: str | None = None,
    ) -> dict[str, Any]:
        description = description.strip()
        if not description:
            raise ValueError("Describe the issue to investigate.")
        if len(description) > 4000:
            raise ValueError("Issue description must be 4,000 characters or fewer.")
        results = await self.retriever.search(
            description,
            top_k=MAX_RETRIEVAL_RESULTS,
            retrieval_k=16,
        )
        candidates = [
            {
                "file_path": item.filename,
                "start_line": item.start_line,
                "end_line": item.end_line,
                "function": item.graph_node,
                "relevance": round(float(item.hybrid_score), 4),
                "evidence": item.code[:2000],
            }
            for item in results
        ]
        context_parts = [
            f"Issue description: {description}",
            f"Hybrid retrieval evidence (semantic, keyword, graph): {candidates}",
        ]
        if file_path:
            file = self.navigation.workspace.read_file(file_path)
            numbered_source = "\n".join(
                f"{number}: {line}"
                for number, line in enumerate(file.content.splitlines(), 1)
            )
            context_parts.append(
                f"Selected file {file.path}:\n{numbered_source[:6000]}"
            )
        if selected_code:
            context_parts.append(f"User-selected code:\n{selected_code[:5000]}")
        if not candidates and not selected_code:
            raise AnalysisError(
                "No repository evidence was retrieved for this issue. "
                "Try a more specific description or include a file selection."
            )
        explanation = await self.llm.generate_analysis(
            "Investigate the described software issue. Rank only the supplied "
            "locations as hypotheses, state supporting evidence, distinguish "
            "hypotheses from confirmed facts, and give concrete next debugging "
            "steps. Do not claim a root cause without direct evidence.",
            "\n\n".join(context_parts)[:22000],
            model=self.model,
        )
        return {"analysis": explanation, "candidates": candidates}

    async def explain_stack_trace(self, text: str) -> dict[str, Any]:
        parsed = parse_stack_trace(text)
        frames = resolve_stack_frames(parsed, self.navigation)
        safe_exception = {
            "exception_type": parsed["exception_type"],
            "message": parsed["message"],
            "frames": [
                {
                    "line": frame["line"],
                    "function": frame["function"],
                    "format": frame["format"],
                }
                for frame in parsed["frames"]
            ],
        }
        related = await self._graph_neighbors(
            [
                (frame["file_path"], frame["line"], frame["function"])
                for frame in frames
                if frame["resolved"] and frame["file_path"]
            ]
        )
        context = (
            f"Repository: {self.repository.repository_name}\n"
            f"Parsed exception: {safe_exception}\n"
            f"Resolved in-repository frames with source: "
            f"{[frame for frame in frames if frame['resolved']]}\n"
            f"Related indexed graph edges: {related}"
        )
        explanation = await self.llm.generate_analysis(
            "Explain this stack trace using only the parsed exception, resolved "
            "repository frames, and graph edges. Explain execution order, mark "
            "external/unresolved frames as such, distinguish hypotheses from "
            "facts, and recommend focused debugging steps.",
            context[:22000],
            model=self.model,
        )
        return {
            "exception": safe_exception,
            "frames": frames,
            "graph_edges": related,
            "explanation": explanation,
        }

    async def execution_flow(self, symbol: str) -> dict[str, Any]:
        symbol = symbol.strip()
        if not symbol or len(symbol) > 200:
            raise ValueError("Enter a symbol name up to 200 characters.")
        if not self.repository.neo4j_password:
            raise AnalysisError("Neo4j credentials are not configured.")
        driver = AsyncGraphDatabase.driver(
            self.repository.neo4j_uri,
            auth=(
                self.repository.neo4j_user,
                self.repository.neo4j_password,
            ),
        )
        try:
            target_result = await driver.execute_query(
                """
                MATCH (n {repository: $repository})
                WHERE n.kind IN ['function', 'class']
                  AND (toLower(n.name) = toLower($symbol)
                    OR toLower(n.name) ENDS WITH toLower('.' + $symbol))
                RETURN n.id AS id, n.kind AS kind, n.name AS name,
                       n.file_path AS file_path, n.start_line AS start_line
                LIMIT 12
                """,
                repository=self.repository.repository_key,
                symbol=symbol,
                database_=self.repository.neo4j_database,
            )
            targets = [record.data() for record in target_result.records]
            if not targets:
                return {"nodes": [], "edges": [], "explanation": "", "message": "No indexed symbol matched."}

            nodes: dict[str, dict[str, Any]] = {
                item["id"]: {**item, "depth": 0} for item in targets
            }
            edges: dict[tuple[str, str, str], dict[str, Any]] = {}
            frontier = list(nodes)
            for depth in range(MAX_EXECUTION_DEPTH):
                if not frontier or len(nodes) >= MAX_EXECUTION_NODES:
                    break
                current_frontier = [
                    node_id for node_id in frontier
                    if node_id in nodes
                ]
                next_frontier: list[str] = []
                result = await driver.execute_query(
                    """
                    MATCH (a {repository: $repository})
                          -[r:RELATES_TO]-(b {repository: $repository})
                    WHERE a.id IN $ids AND r.relation = 'CALLS'
                    RETURN startNode(r).id AS source,
                           endNode(r).id AS target,
                           startNode(r).name AS source_name,
                           startNode(r).kind AS source_kind,
                           startNode(r).file_path AS source_file,
                           startNode(r).start_line AS source_line,
                           endNode(r).name AS target_name,
                           endNode(r).kind AS target_kind,
                           endNode(r).file_path AS target_file,
                           endNode(r).start_line AS target_line
                    LIMIT 120
                    """,
                    ids=current_frontier,
                    repository=self.repository.repository_key,
                    database_=self.repository.neo4j_database,
                )
                for record in result.records:
                    item = record.data()
                    source = item["source"]
                    target = item["target"]
                    relation = (source, target, "CALLS")
                    edges[relation] = {
                        "source": source,
                        "target": target,
                        "relation": "CALLS",
                    }
                    for node_id, prefix, node_depth in (
                        (source, "source", depth + 1),
                        (target, "target", depth + 1),
                    ):
                        if node_id and node_id not in nodes and len(nodes) < MAX_EXECUTION_NODES:
                            nodes[node_id] = {
                                "id": node_id,
                                "name": item[f"{prefix}_name"],
                                "kind": item[f"{prefix}_kind"],
                                "file_path": item[f"{prefix}_file"],
                                "line": item[f"{prefix}_line"],
                                "depth": node_depth,
                            }
                            next_frontier.append(node_id)
                frontier = next_frontier
        except Exception as exc:
            logger.exception("Execution-flow graph lookup failed")
            raise AnalysisError("Could not retrieve execution-flow relationships.") from exc
        finally:
            await driver.close()

        for node in nodes.values():
            node["source"] = None
            if node.get("file_path") and node.get("line"):
                try:
                    node["source"] = self.navigation.source_excerpt(
                        node["file_path"], int(node["line"])
                    )["code"]
                except (WorkspaceError, ValueError):
                    pass
        context = (
            f"Graph nodes: {list(nodes.values())}\n"
            f"Actual CALLS relationships: {list(edges.values())}\n"
            "These are static indexed relationships, not proof of runtime execution order."
        )
        explanation = await self.llm.generate_analysis(
            f"Explain the indexed static call flow around {symbol!r}. "
            "Do not present it as a guaranteed runtime sequence.",
            context[:18000],
            model=self.model,
        )
        return {
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
            "truncated": len(nodes) >= MAX_EXECUTION_NODES,
            "explanation": explanation,
        }

    async def suggest_improvements(
        self,
        scope: str,
        file_path: str | None = None,
        selected_code: str | None = None,
    ) -> dict[str, Any]:
        if scope not in {"repository", "file", "selection"}:
            raise ValueError("Scope must be repository, file, or selection.")
        if scope == "file" and not file_path:
            raise ValueError("Choose a file for file-scoped suggestions.")
        if scope == "selection" and not selected_code:
            raise ValueError("Select code in the editor first.")

        context: list[str] = [f"Repository: {self.repository.repository_name}"]
        if scope == "file":
            file = self.navigation.workspace.read_file(str(file_path))
            numbered_source = "\n".join(
                f"{number}: {line}"
                for number, line in enumerate(file.content.splitlines(), 1)
            )
            context.append(
                f"FILE {file.path}\n{numbered_source[:12000]}"
            )
        elif scope == "selection":
            context.append(f"Selected source code:\n{selected_code[:8000]}")
            if file_path:
                context.append(f"Selected file: {file_path}")
        else:
            findings = await self.retriever.search(
                "complex functions error handling duplication maintainability "
                "test coverage module responsibilities",
                top_k=6,
                retrieval_k=12,
            )
            context.append(
                "Targeted hybrid retrieval evidence: "
                + repr([
                    {
                        "file_path": item.filename,
                        "start_line": item.start_line,
                        "end_line": item.end_line,
                        "score": item.hybrid_score,
                        "code": item.code[:1400],
                    }
                    for item in findings
                ])
            )
            context.append(f"Project structure: {self.repository.structure()}")
        if len("\n".join(context)) < 100:
            raise AnalysisError("Not enough source context to make recommendations.")
        analysis = await self.llm.generate_analysis(
            "Suggest only evidence-based code improvements. For every suggestion "
            "name concrete source evidence and a file/line only when supplied. "
            "Distinguish objective defects from maintainability tradeoffs. If no "
            "clear issue is supported, say so instead of inventing findings. "
            "Do not modify code.",
            "\n\n".join(context)[:22000],
            model=self.model,
        )
        return {"scope": scope, "file_path": file_path, "suggestions": analysis}

    async def _graph_neighbors(
        self,
        locations: list[tuple[str | None, int, str]],
    ) -> list[dict[str, Any]]:
        if not locations or not self.repository.neo4j_password:
            return []
        driver = AsyncGraphDatabase.driver(
            self.repository.neo4j_uri,
            auth=(
                self.repository.neo4j_user,
                self.repository.neo4j_password,
            ),
        )
        try:
            paths = list(dict.fromkeys(path for path, _, _ in locations if path))
            result = await driver.execute_query(
                """
                MATCH (n {repository: $repository})
                WHERE n.file_path IN $paths
                OPTIONAL MATCH (n)-[r:RELATES_TO]-(m {repository: $repository})
                RETURN n.name AS name, n.file_path AS file_path,
                       n.start_line AS line, r.relation AS relation,
                       m.name AS related_name, m.file_path AS related_file_path,
                       m.start_line AS related_line
                LIMIT 100
                """,
                repository=self.repository.repository_key,
                paths=paths,
                database_=self.repository.neo4j_database,
            )
            return [record.data() for record in result.records]
        except Exception as exc:
            logger.exception("Stack trace graph context lookup failed")
            raise AnalysisError("Could not retrieve stack-frame relationships.") from exc
        finally:
            await driver.close()
