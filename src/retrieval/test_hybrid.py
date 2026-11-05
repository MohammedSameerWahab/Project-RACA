from __future__ import annotations

import asyncio

from src.retrieval.hybrid import HybridRetriever


async def main() -> None:
    query = input(
        "Enter hybrid search query: "
    ).strip()

    retriever = HybridRetriever()

    results = await retriever.search(
        query,
        top_k=10,
        retrieval_k=20,
    )

    if not results:
        print("\nNo hybrid results found.")
        return

    print(
        f"\nFound {len(results)} hybrid results:\n"
    )

    for index, result in enumerate(
        results,
        start=1,
    ):
        print("=" * 80)

        print(
            f"Result {index}"
        )

        print(
            f"Hybrid score:   "
            f"{result.hybrid_score:.4f}"
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

        print("-" * 80)
        print(result.code)


def format_score(
    score: float | None,
) -> str:
    if score is None:
        return "-"

    return f"{score:.4f}"


if __name__ == "__main__":
    asyncio.run(main())