from __future__ import annotations

import asyncio

from src.context.builder import ContextBuilder
from src.generation.llm import LLMGenerator
from src.retrieval.hybrid import HybridRetriever


async def main() -> None:
    query = input(
        "Enter your coding question: "
    ).strip()

    if not query:
        print("Query cannot be empty.")
        return

    # ---------------------------------------------------------------
    # Phase 7: Hybrid retrieval
    # ---------------------------------------------------------------

    print("\n[Phase 7] Running hybrid retrieval...")

    retriever = HybridRetriever()

    results = await retriever.search(
        query,
        top_k=10,
        retrieval_k=20,
    )

    if not results:
        print("No hybrid results found.")
        return

    print(
        f"Retrieved {len(results)} hybrid results."
    )

    # ---------------------------------------------------------------
    # Phase 8: Context building
    # ---------------------------------------------------------------

    print("\n[Phase 8] Building context...")

    builder = ContextBuilder(
        max_context_tokens=4000,
        max_chunk_tokens=1000,
    )

    context_result = builder.build(
        query=query,
        results=results,
    )

    print(
        f"Selected chunks: "
        f"{len(context_result.chunks)}"
    )

    print(
        f"Estimated tokens: "
        f"{context_result.estimated_tokens}"
    )

    # ---------------------------------------------------------------
    # Phase 9: LLM generation
    # ---------------------------------------------------------------

    print("\n[Phase 9] Generating answer...")

    async with LLMGenerator() as generator:
        answer = await generator.generate(
            context_result
        )

    print("\n" + "=" * 90)
    print("RACA ANSWER")
    print("=" * 90)
    print(answer)
    print("=" * 90)


if __name__ == "__main__":
    asyncio.run(main())