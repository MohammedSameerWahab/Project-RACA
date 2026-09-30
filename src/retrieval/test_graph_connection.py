from __future__ import annotations

import asyncio
import os

from neo4j import AsyncGraphDatabase


async def main() -> None:
    uri = os.environ.get(
        "NEO4J_URI",
        "neo4j://127.0.0.1:7687",
    )

    user = os.environ.get(
        "NEO4J_USER",
        "neo4j",
    )

    password = os.environ["NEO4J_PASSWORD"]

    database = os.environ.get(
        "NEO4J_DATABASE",
        "raca_graph",
    )

    driver = AsyncGraphDatabase.driver(
        uri,
        auth=(user, password),
    )

    try:
        result = await driver.execute_query(
            """
            MATCH (n)
            RETURN
                count(n) AS count,
                collect(DISTINCT n.repository) AS repositories,
                collect(DISTINCT n.kind) AS kinds
            """,
            database_=database,
        )

        print("Neo4j database:", database)
        print(result.records[0].data())

        print("\nNodes containing 'route':")

        result = await driver.execute_query(
            """
            MATCH (n)
            WHERE toLower(n.name) CONTAINS "route"
            RETURN
                n.id AS id,
                n.repository AS repository,
                n.kind AS kind,
                n.name AS name,
                n.file_path AS file_path
            LIMIT 10
            """,
            database_=database,
        )

        for record in result.records:
            print(record.data())

    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())