from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from src.retrieval.graph import graph_search
from retrieval.keyword import KeywordRetriever
from retrieval.semantic import SemanticRetriever


# -------------------------------------------------------------------
# Hybrid configuration
# -------------------------------------------------------------------

DEFAULT_SEMANTIC_WEIGHT = 0.40
DEFAULT_KEYWORD_WEIGHT = 0.30
DEFAULT_GRAPH_WEIGHT = 0.30


# -------------------------------------------------------------------
# Result model
# -------------------------------------------------------------------

@dataclass
class HybridSearchResult:
    """A single result returned by the hybrid retriever."""

    repository: str
    filename: str
    language: str
    code: str

    start_line: int
    end_line: int

    hybrid_score: float

    semantic_score: float | None = None
    keyword_score: float | None = None
    graph_score: float | None = None

    graph_kind: str | None = None
    graph_node: str | None = None
    relation: str | None = None


# -------------------------------------------------------------------
# Score normalization
# -------------------------------------------------------------------

def normalize_scores(
    results: list[Any],
) -> dict[tuple, float]:
    """
    Normalize retrieval scores to the range [0, 1].

    The returned dictionary maps a chunk identity to its normalized
    score.

    If all results have the same score, every result receives 1.0.
    """

    if not results:
        return {}

    scores = [
        float(result.score)
        for result in results
    ]

    minimum = min(scores)
    maximum = max(scores)

    normalized: dict[tuple, float] = {}

    for result in results:
        key = make_chunk_key(result)

        if maximum == minimum:
            normalized_score = 1.0
        else:
            normalized_score = (
                float(result.score) - minimum
            ) / (maximum - minimum)

        normalized[key] = normalized_score

    return normalized


# -------------------------------------------------------------------
# Chunk identity
# -------------------------------------------------------------------

def make_chunk_key(result: Any) -> tuple:
    """
    Create a stable identity for a retrieved code chunk.

    Repository + filename + line range are used so the same chunk
    returned by multiple retrieval strategies is merged.
    """

    filename = str(result.filename).replace("\\", "/")

    return (
        str(result.repository),
        filename,
        int(result.start_line),
        int(result.end_line),
    )


# -------------------------------------------------------------------
# Hybrid retrieval
# -------------------------------------------------------------------

class HybridRetriever:
    """
    Combine semantic, keyword, and graph retrieval.

    Each retrieval strategy remains independently implemented.
    This class is responsible only for orchestration, normalization,
    deduplication, and score fusion.
    """

    def __init__(
        self,
        database_url: str | None = None,
        semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT,
        keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
        graph_weight: float = DEFAULT_GRAPH_WEIGHT,
    ) -> None:

        total_weight = (
            semantic_weight
            + keyword_weight
            + graph_weight
        )

        if total_weight <= 0:
            raise ValueError(
                "At least one retrieval weight must be greater than zero."
            )

        self.semantic_weight = (
            semantic_weight / total_weight
        )

        self.keyword_weight = (
            keyword_weight / total_weight
        )

        self.graph_weight = (
            graph_weight / total_weight
        )

        self.semantic_retriever = SemanticRetriever(
            database_url=database_url
        )

        self.keyword_retriever = KeywordRetriever(
            database_url=database_url
        )

    # ----------------------------------------------------------------
    # Search
    # ----------------------------------------------------------------

    async def search(
        self,
        query: str,
        top_k: int = 10,
        retrieval_k: int | None = None,
    ) -> list[HybridSearchResult]:
        """
        Perform hybrid repository retrieval.

        Args:
            query:
                Natural-language repository query.

            top_k:
                Number of final hybrid results.

            retrieval_k:
                Number of results requested from each individual
                retriever before fusion.

                If omitted, top_k is used.

        Returns:
            Final ranked hybrid results.
        """

        if not query.strip():
            raise ValueError(
                "Search query cannot be empty."
            )

        if top_k <= 0:
            raise ValueError(
                "top_k must be greater than zero."
            )

        if retrieval_k is None:
            retrieval_k = top_k

        if retrieval_k <= 0:
            raise ValueError(
                "retrieval_k must be greater than zero."
            )

        # ------------------------------------------------------------
        # Run the three retrieval strategies independently.
        # ------------------------------------------------------------

        (
            semantic_results,
            keyword_results,
            graph_results,
        ) = await asyncio.gather(
            self.semantic_retriever.search(
                query,
                top_k=retrieval_k,
            ),
            self.keyword_retriever.search(
                query,
                top_k=retrieval_k,
            ),
            graph_search(
                query,
                top_k=retrieval_k,
            ),
        )

        # ------------------------------------------------------------
        # Normalize each retrieval strategy independently.
        # ------------------------------------------------------------

        semantic_scores = normalize_scores(
            semantic_results
        )

        keyword_scores = normalize_scores(
            keyword_results
        )

        graph_scores = normalize_scores(
            graph_results
        )

        # ------------------------------------------------------------
        # Merge all retrieved chunks.
        # ------------------------------------------------------------

        merged: dict[tuple, HybridSearchResult] = {}

        # ------------------------------------------------------------
        # Semantic results
        # ------------------------------------------------------------

        for result in semantic_results:

            key = make_chunk_key(result)

            merged[key] = HybridSearchResult(
                repository=result.repository,
                filename=result.filename,
                language=result.language,
                code=result.code,
                start_line=result.start_line,
                end_line=result.end_line,
                hybrid_score=0.0,
                semantic_score=semantic_scores[key],
            )

        # ------------------------------------------------------------
        # Keyword results
        # ------------------------------------------------------------

        for result in keyword_results:

            key = make_chunk_key(result)

            if key not in merged:
                merged[key] = HybridSearchResult(
                    repository=result.repository,
                    filename=result.filename,
                    language=result.language,
                    code=result.code,
                    start_line=result.start_line,
                    end_line=result.end_line,
                    hybrid_score=0.0,
                )

            merged[key].keyword_score = keyword_scores[key]

        # ------------------------------------------------------------
        # Graph results
        # ------------------------------------------------------------

        for result in graph_results:

            key = make_chunk_key(result)

            if key not in merged:
                merged[key] = HybridSearchResult(
                    repository=result.repository,
                    filename=result.filename,
                    language=result.language,
                    code=result.code,
                    start_line=result.start_line,
                    end_line=result.end_line,
                    hybrid_score=0.0,
                )

            merged[key].graph_score = graph_scores[key]

            # Preserve graph-specific information.
            merged[key].graph_kind = result.graph_kind
            merged[key].graph_node = result.graph_node
            merged[key].relation = result.relation

        # ------------------------------------------------------------
        # Calculate final hybrid score.
        # ------------------------------------------------------------

        for result in merged.values():

            semantic_score = (
                result.semantic_score
                if result.semantic_score is not None
                else 0.0
            )

            keyword_score = (
                result.keyword_score
                if result.keyword_score is not None
                else 0.0
            )

            graph_score = (
                result.graph_score
                if result.graph_score is not None
                else 0.0
            )

            result.hybrid_score = (
                self.semantic_weight * semantic_score
                + self.keyword_weight * keyword_score
                + self.graph_weight * graph_score
            )

        # ------------------------------------------------------------
        # Final ranking.
        # ------------------------------------------------------------

        ranked_results = sorted(
            merged.values(),
            key=lambda result: result.hybrid_score,
            reverse=True,
        )

        return ranked_results[:top_k]


# -------------------------------------------------------------------
# Manual testing
# -------------------------------------------------------------------

async def main() -> None:
    """Run a simple manual hybrid retrieval test."""

    query = input(
        "Enter hybrid search query: "
    ).strip()

    retriever = HybridRetriever()

    results = await retriever.search(
        query,
        top_k=10,
    )

    if not results:
        print("\nNo hybrid results found.")
        return

    print(
        f"\nFound {len(results)} hybrid results:\n"
    )

    print("=" * 90)

    for index, result in enumerate(
        results,
        start=1,
    ):
        print(
            f"Result {index}"
        )

        print(
            f"Hybrid score:   {result.hybrid_score:.4f}"
        )

        print(
            f"Semantic score: "
            f"{format_score(result.semantic_score)}"
        )

        print(
            f"Keyword score:  "
            f"{format_score(result.keyword_score)}"
        )

        print(
            f"Graph score:    "
            f"{format_score(result.graph_score)}"
        )

        print(
            f"File:           {result.filename}"
        )

        print(
            f"Lines:          "
            f"{result.start_line}-{result.end_line}"
        )

        if result.graph_node:
            print(
                f"Graph node:     {result.graph_node}"
            )

        if result.relation:
            print(
                f"Relationship:   {result.relation}"
            )

        print("-" * 90)

        print(result.code)

        print("=" * 90)


def format_score(
    score: float | None,
) -> str:
    """Format an optional retrieval score for display."""

    if score is None:
        return "-"

    return f"{score:.4f}"


if __name__ == "__main__":
    asyncio.run(main())