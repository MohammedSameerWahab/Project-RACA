from __future__ import annotations

import asyncio
import os

from neo4j import AsyncGraphDatabase


async def main() -> None:
    uri = os.environ.get("NEO4J_URI", "neo4j://127.0.0.1:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "raca-graph")

    repository = "flask"
    terms = ["flask", "application"]

    driver = AsyncGraphDatabase.driver(
        uri,
        auth=(user, password),
    )

    try:
        result = await driver.execute_query(
            """
            MATCH (n)
            WHERE n.repository = $repository
              AND any(
                  term IN $terms
                  WHERE toLower(n.name) CONTAINS term
                     OR toLower(n.file_path) CONTAINS term
              )
            RETURN
                n.id AS id,
                n.repository AS repository,
                n.kind AS kind,
                n.name AS name,
                n.file_path AS file_path,
                n.start_line AS start_line,
                n.end_line AS end_line
            LIMIT 20
            """,
            repository=repository,
            terms=terms,
            database_=database,
        )

        print(f"Repository: {repository}")
        print(f"Search terms: {terms}")
        print(f"Matches: {len(result.records)}")
        print()

        for record in result.records:
            print(record.data())

    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())