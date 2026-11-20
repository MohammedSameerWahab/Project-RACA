from __future__ import annotations

import os
import re
from dataclasses import dataclass

import asyncpg


TABLE_NAME = "raca_code_embeddings"


@dataclass
class KeywordSearchResult:
    """A single keyword search result."""

    repository: str
    filename: str
    language: str
    code: str
    score: float
    start_line: int
    end_line: int


class KeywordRetriever:
    """Retrieve repository code using PostgreSQL full-text search."""

    def __init__(
        self,
        database_url: str | None = None,
        table_name: str = TABLE_NAME,
    ) -> None:
        self.database_url = (
            database_url
            or os.environ["POSTGRES_URL"]
        )
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", table_name):
            raise ValueError("Invalid PostgreSQL table name.")
        self.table_name = table_name

    @staticmethod
    def _search_query(query: str) -> str:
        terms = re.findall(r"[a-zA-Z0-9_]+", query)
        if not terms:
            raise ValueError("Search query must contain searchable terms.")
        return " OR ".join(terms)

    async def search(
        self,
        query: str,
        top_k: int = 3,
    ) -> list[KeywordSearchResult]:
        """
        Search repository code using keyword matching.

        Args:
            query: Natural-language query whose searchable terms are OR-matched.
            top_k: Maximum number of results.

        Returns:
            Ranked keyword search results.
        """

        if not query.strip():
            raise ValueError(
                "Search query cannot be empty."
            )

        if top_k <= 0:
            raise ValueError(
                "top_k must be greater than zero."
            )

        search_query = self._search_query(query)
        pool = await asyncpg.create_pool(
            self.database_url
        )

        try:
            async with pool.acquire() as connection:
                rows = await connection.fetch(
                    f"""
                    SELECT
                        repository,
                        filename,
                        language,
                        code,
                        ts_rank(
                            to_tsvector(
                                'english',
                                code
                            ),
                            websearch_to_tsquery(
                                'english',
                                $1
                            )
                        ) AS score,
                        start_line,
                        end_line
                    FROM "{self.table_name}"
                    WHERE to_tsvector(
                        'english',
                        code
                    ) @@ websearch_to_tsquery(
                        'english',
                        $1
                    )
                    ORDER BY score DESC
                    LIMIT $2
                    """,
                    search_query,
                    top_k,
                )
        finally:
            await pool.close()

        return [
            KeywordSearchResult(
                repository=row["repository"],
                filename=row["filename"],
                language=row["language"],
                code=row["code"],
                score=float(row["score"]),
                start_line=row["start_line"],
                end_line=row["end_line"],
            )
            for row in rows
        ]