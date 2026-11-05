from __future__ import annotations

import os
import re
from dataclasses import dataclass

import asyncpg
from neo4j import AsyncGraphDatabase


# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

POSTGRES_URL = os.environ.get(
    "POSTGRES_URL",
    "postgresql://postgres:postgres@localhost:5432/raca",
)

NEO4J_URI = os.environ.get(
    "NEO4J_URI",
    "bolt://127.0.0.1:7687",
)

NEO4J_USER = os.environ.get(
    "NEO4J_USER",
    "neo4j",
)

NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

NEO4J_DATABASE = os.environ.get(
    "NEO4J_DATABASE",
    "raca-graph",
)

RACA_REPOSITORY_PATH = os.environ.get(
    "RACA_REPOSITORY_PATH",
    r"C:\Projects\Project RACA",
)


# -------------------------------------------------------------------
# Result model
# -------------------------------------------------------------------

@dataclass
class GraphSearchResult:
    """
    A repository chunk retrieved through graph relationships.

    The core fields intentionally match the semantic and keyword
    retrieval result contracts so Phase 7 can combine them.
    """

    repository: str
    filename: str
    language: str
    code: str
    score: float
    start_line: int
    end_line: int

    # Graph-specific information.
    graph_kind: str
    graph_node: str
    relation: str


# -------------------------------------------------------------------
# Query helpers
# -------------------------------------------------------------------

def extract_query_terms(query: str) -> list[str]:
    """
    Extract useful terms from a natural-language query.

    The first graph implementation intentionally uses simple lexical
    anchors rather than introducing another embedding/search system.
    """

    terms = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", query.lower())

    # Remove extremely common natural-language words.
    stop_words = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "where",
        "what",
        "which",
        "how",
        "does",
        "do",
        "in",
        "of",
        "to",
        "for",
        "from",
        "and",
        "or",
        "with",
        "on",
        "at",
        "this",
        "that",
        "it",
        "show",
        "find",
        "explain",
        "code",
        "function",
        "class",
        "file",
    }

    return list(
        dict.fromkeys(
            term
            for term in terms
            if term not in stop_words and len(term) >= 2
        )
    )


# -------------------------------------------------------------------
# Neo4j retrieval
# -------------------------------------------------------------------

async def find_graph_nodes(
    driver,
    repository: str,
    terms: list[str],
) -> list[dict]:
    """
    Find graph nodes whose names or file paths contain query terms.

    The query also returns immediate incoming/outgoing relationships
    so that graph structure can expand the initial matches.
    """

    if not terms:
        return []

    cypher = """
    MATCH (n)
    WHERE n.repository = $repository
      AND any(
          term IN $terms
          WHERE toLower(coalesce(n.name, '')) CONTAINS term
             OR toLower(coalesce(n.file_path, '')) CONTAINS term
      )

    OPTIONAL MATCH (n)-[r]-(related)

    RETURN
        n.repository AS repository,
        n.id AS node_id,
        n.kind AS node_kind,
        n.name AS node_name,
        n.file_path AS file_path,
        n.start_line AS start_line,
        n.end_line AS end_line,
        type(r) AS relation,
        related.repository AS related_repository,
        related.id AS related_id,
        related.kind AS related_kind,
        related.name AS related_name,
        related.file_path AS related_file_path,
        related.start_line AS related_start_line,
        related.end_line AS related_end_line
    """

    result = await driver.execute_query(
        cypher,
        repository=repository,
        terms=terms,
        database_=NEO4J_DATABASE,
    )

    return [record.data() for record in result.records]


# -------------------------------------------------------------------
# PostgreSQL chunk retrieval
# -------------------------------------------------------------------

async def fetch_chunks_for_nodes(
    pool: asyncpg.Pool,
    records: list[dict],
    fallback_repository: str,
    table_name: str = "raca_code_embeddings",
) -> list[GraphSearchResult]:
    """
    Retrieve actual code chunks corresponding to graph nodes and their
    connected neighbors.
    """

    results: list[GraphSearchResult] = []
    seen_chunks: set[str] = set()

    # Deduplicate graph targets (matched nodes + related nodes)
    entities_to_query: list[dict] = []
    seen_entity_keys: set[tuple] = set()

    for rec in records:
        # 1. Direct matched node
        node_repo = rec.get("repository") or fallback_repository
        fp = rec.get("file_path")

        if fp:
            key = (
                node_repo,
                fp,
                rec.get("start_line"),
                rec.get("end_line"),
                "MATCH",
                rec.get("node_name"),
            )

            if key not in seen_entity_keys:
                seen_entity_keys.add(key)
                entities_to_query.append(
                    {
                        "repository": node_repo,
                        "file_path": fp,
                        "start_line": rec.get("start_line"),
                        "end_line": rec.get("end_line"),
                        "node_kind": rec.get("node_kind", "unknown"),
                        "node_name": rec.get("node_name", ""),
                        "relation": "MATCH",
                    }
                )

        # 2. Connected graph entity (graph expansion)
        rel_fp = rec.get("related_file_path")
        rel_repo = rec.get("related_repository") or fallback_repository

        if rel_fp:
            rel_key = (
                rel_repo,
                rel_fp,
                rec.get("related_start_line"),
                rec.get("related_end_line"),
                rec.get("relation"),
                rec.get("related_name"),
            )

            if rel_key not in seen_entity_keys:
                seen_entity_keys.add(rel_key)
                entities_to_query.append(
                    {
                        "repository": rel_repo,
                        "file_path": rel_fp,
                        "start_line": rec.get("related_start_line"),
                        "end_line": rec.get("related_end_line"),
                        "node_kind": rec.get("related_kind", "unknown"),
                        "node_name": rec.get("related_name", ""),
                        "relation": rec.get("relation") or "RELATED",
                    }
                )

    for entity in entities_to_query:
        file_path = entity["file_path"]
        start_line = entity.get("start_line")
        end_line = entity.get("end_line")
        repo_name = entity["repository"]

        if start_line is None or start_line <= 0:
            start_line = 1

        if end_line is None or end_line <= 0:
            end_line = 10**9

        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", table_name):
            raise ValueError("Invalid PostgreSQL table name.")

        rows = await pool.fetch(
            f"""
            SELECT
                id,
                repository,
                filename,
                language,
                code,
                start_line,
                end_line
            FROM "{table_name}"
            WHERE repository = $1
              AND REPLACE(filename, chr(92), '/') = REPLACE($2, chr(92), '/')
              AND start_line <= $4
              AND end_line >= $3
            ORDER BY
                ABS(start_line - $3),
                start_line
            LIMIT 5
            """,
            repo_name,
            file_path,
            start_line,
            end_line,
        )

        for row in rows:
            chunk_id = str(row["id"])

            if chunk_id in seen_chunks:
                continue

            seen_chunks.add(chunk_id)

            results.append(
                GraphSearchResult(
                    repository=row["repository"],
                    filename=row["filename"],
                    language=row["language"],
                    code=row["code"],
                    score=1.0,
                    start_line=row["start_line"],
                    end_line=row["end_line"],
                    graph_kind=entity["node_kind"],
                    graph_node=entity["node_name"],
                    relation=entity["relation"],
                )
            )

    return results

# -------------------------------------------------------------------
# Ranking
# -------------------------------------------------------------------

def rank_results(
    results: list[GraphSearchResult],
    query_terms: list[str],
    top_k: int,
) -> list[GraphSearchResult]:
    """Give graph results a simple deterministic score."""

    scored: list[tuple[float, GraphSearchResult]] = []

    for result in results:
        node_text = (
            f"{result.graph_node} "
            f"{result.filename} "
            f"{result.code}"
        ).lower()

        matches = sum(
            1
            for term in query_terms
            if term in node_text
        )

        score = 1.0 + (0.25 * matches)

        if result.relation != "MATCH":
            score += 0.25

        scored.append((score, result))

    scored.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    final_results: list[GraphSearchResult] = []

    for score, result in scored[:top_k]:
        result.score = score
        final_results.append(result)

    return final_results


# -------------------------------------------------------------------
# Public graph search function
# -------------------------------------------------------------------

async def graph_search(
    query: str,
    top_k: int = 10,
    repository_key: str | None = None,
    table_name: str = "raca_code_embeddings",
    database_url: str | None = None,
) -> list[GraphSearchResult]:
    """Perform graph-based repository retrieval."""

    if not query.strip():
        return []

    if top_k <= 0:
        return []

    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", table_name):
        raise ValueError("Invalid PostgreSQL table name.")

    repository = repository_key or os.environ.get(
        "RACA_REPOSITORY_KEY",
        os.path.basename(os.path.normpath(RACA_REPOSITORY_PATH)),
    )

    query_terms = extract_query_terms(query)




    if not query_terms:
        return []

    driver = AsyncGraphDatabase.driver(
        NEO4J_URI,
        auth=(
            NEO4J_USER,
            NEO4J_PASSWORD,
        ),
    )

    pool = await asyncpg.create_pool(database_url or POSTGRES_URL)

    try:
        graph_records = await find_graph_nodes(
            driver,
            repository,
            query_terms,
        )
        # print(f"DEBUG: Neo4j returned {len(graph_records)} records.")
        if graph_records:
            print(f"DEBUG: First Neo4j record file_path: {graph_records[0].get('file_path')}")

        results = await fetch_chunks_for_nodes(
            pool,
            graph_records,
            fallback_repository=repository,
            table_name=table_name,
        )
        # print(f"DEBUG: PostgreSQL returned {len(results)} chunks.")
        # print(
        #     "DEBUG graph retrieval: "
        #     f"{len(graph_records)} Neo4j relationship records -> "
        #     f"{len(results)} unique PostgreSQL chunks -> "
        #     f"{min(len(results), top_k)} final results"
        # )

        return rank_results(
            results,
            query_terms,
            top_k,
        )

    finally:
        await pool.close()
        await driver.close()


# -------------------------------------------------------------------
# Manual testing
# -------------------------------------------------------------------

async def main() -> None:
    query = input(
        "Enter graph search query: "
    ).strip()

    results = await graph_search(
        query,
        top_k=10,
    )

    if not results:
        print("\nNo graph results found.")
        return

    print(
        f"\nFound {len(results)} graph results:\n"
    )

    for index, result in enumerate(
        results,
        start=1,
    ):
        print("=" * 80)
        print(f"Result {index}")
        print(f"Score:        {result.score:.2f}")
        print(f"File:         {result.filename}")
        print(
            f"Lines:        "
            f"{result.start_line}-{result.end_line}"
        )
        print(f"Graph kind:   {result.graph_kind}")
        print(f"Graph node:   {result.graph_node}")
        print(f"Relationship: {result.relation}")
        print("-" * 80)
        print(result.code)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())