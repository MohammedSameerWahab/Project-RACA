from __future__ import annotations

import os
from dataclasses import dataclass

import asyncpg
from pgvector.asyncpg import register_vector
from cocoindex.ops.sentence_transformers import SentenceTransformerEmbedder

from config import EMBEDDING_MODEL


TABLE_NAME = "raca_code_embeddings"


@dataclass
class SemanticSearchResult:
    """A single semantic search result."""

    repository: str
    filename: str
    language: str
    code: str
    score: float
    start_line: int
    end_line: int


class SemanticRetriever:
    """Retrieve repository code using vector similarity."""

    def __init__(
        self,
        database_url: str | None = None,
    ) -> None:
        self.database_url = (
            database_url
            or os.environ["POSTGRES_URL"]
        )

        self.embedder = SentenceTransformerEmbedder(
            EMBEDDING_MODEL
        )

    async def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[SemanticSearchResult]:
        """
        Search the codebase using semantic similarity.

        Args:
            query: Natural-language search query.
            top_k: Number of results to return.

        Returns:
            Ranked semantic search results.
        """

        if not query.strip():
            raise ValueError(
                "Search query cannot be empty."
            )

        if top_k <= 0:
            raise ValueError(
                "top_k must be greater than zero."
            )

        query_embedding = await self.embedder.embed(
            query
        )

        async def init_connection(conn):
            await register_vector(conn)

        pool = await asyncpg.create_pool(
            self.database_url,
            init=init_connection
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
                        embedding <=> $1::vector AS distance,
                        start_line,
                        end_line
                    FROM "{TABLE_NAME}"
                    ORDER BY distance ASC
                    LIMIT $2
                    """,
                    query_embedding,
                    top_k,
                )
        finally:
            await pool.close()

        return [
            SemanticSearchResult(
                repository=row["repository"],
                filename=row["filename"],
                language=row["language"],
                code=row["code"],
                score=1.0 - float(row["distance"]),
                start_line=row["start_line"],
                end_line=row["end_line"],
            )
            for row in rows
        ]