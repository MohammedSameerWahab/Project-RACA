import asyncio

from retrieval.keyword import KeywordRetriever


async def main() -> None:
    retriever = KeywordRetriever()

    query = input(
        "Enter keyword search query: "
    ).strip()

    results = await retriever.search(
        query,
        top_k=5,
    )

    print()
    print("=" * 80)
    print("KEYWORD SEARCH RESULTS")
    print("=" * 80)

    if not results:
        print("No matching results found.")
        return

    for index, result in enumerate(
        results,
        start=1,
    ):
        print()
        print(
            f"{index}. "
            f"[score={result.score:.4f}] "
            f"{result.filename}"
        )

        print(
            f"   Language: {result.language}"
        )

        print(
            f"   Lines: "
            f"{result.start_line}-{result.end_line}"
        )

        print()
        print(result.code)

        print("-" * 80)


if __name__ == "__main__":
    asyncio.run(main())