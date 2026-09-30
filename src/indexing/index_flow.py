from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, AsyncIterator

import asyncpg
import cocoindex as coco
from numpy.typing import NDArray

from cocoindex.connectors import localfs, postgres
from cocoindex.ops.sentence_transformers import SentenceTransformerEmbedder
from cocoindex.ops.text import RecursiveSplitter, detect_code_language
from cocoindex.resources.chunk import Chunk
from cocoindex.resources.file import FileLike, PatternFilePathMatcher
from cocoindex.resources.id import IdGenerator

from src.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    COCOINDEX_DB_PATH,
    EMBEDDING_MODEL,
    MIN_CHUNK_SIZE,
)


# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

DATABASE_URL = os.environ["POSTGRES_URL"]
REPOSITORY_PATH = os.environ["RACA_REPOSITORY_PATH"]

REPOSITORY_DIR = Path(REPOSITORY_PATH).resolve()
REPOSITORY_NAME = REPOSITORY_DIR.name

TABLE_NAME = "raca_code_embeddings"


# -------------------------------------------------------------------
# Shared CocoIndex resources
# -------------------------------------------------------------------

PG_DB = coco.ContextKey[asyncpg.Pool](
    "raca_postgres_db"
)

EMBEDDER = coco.ContextKey[SentenceTransformerEmbedder](
    "raca_embedder",
    detect_change=True,
)


_splitter = RecursiveSplitter()


# -------------------------------------------------------------------
# Data model
# -------------------------------------------------------------------

@dataclass
class CodeEmbedding:
    """One searchable code chunk."""

    id: int
    repository: str
    filename: str
    language: str
    code: str
    embedding: Annotated[NDArray, EMBEDDER]
    start_line: int
    end_line: int


# -------------------------------------------------------------------
# CocoIndex lifecycle
# -------------------------------------------------------------------

@coco.lifespan
async def coco_lifespan(
    builder: coco.EnvironmentBuilder,
) -> AsyncIterator[None]:
    """
    Initialize resources shared by the indexing pipeline.
    """

    # CocoIndex's own internal state database.
    builder.settings.db_path = COCOINDEX_DB_PATH

    # PostgreSQL connection pool.
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        builder.provide(PG_DB, pool)

        # Embedding model.
        builder.provide(
            EMBEDDER,
            SentenceTransformerEmbedder(
                EMBEDDING_MODEL
            ),
        )

        yield


# -------------------------------------------------------------------
# Process one file
# -------------------------------------------------------------------

@coco.fn(memo=True)
async def process_file(
    file: FileLike,
    table: postgres.TableTarget[CodeEmbedding],
) -> None:
    """
    Read one repository file, detect its language,
    split it into syntax-aware chunks, and process them.
    """

    text = await file.read_text()

    language = detect_code_language(
        filename=str(file.file_path.path.name)
    )

    chunks = _splitter.split(
        text,
        chunk_size=CHUNK_SIZE,
        min_chunk_size=MIN_CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        language=language,
    )

    id_generator = IdGenerator()

    await coco.map(
        process_chunk,
        chunks,
        file.file_path.path,
        language,
        id_generator,
        table,
    )


# -------------------------------------------------------------------
# Process one chunk
# -------------------------------------------------------------------

@coco.fn
async def process_chunk(
    chunk: Chunk,
    filename: Path,
    language: str,
    id_generator: IdGenerator,
    table: postgres.TableTarget[CodeEmbedding],
) -> None:
    """
    Generate an embedding for one code chunk
    and declare the resulting database row.
    """

    embedding = await coco.use_context(
        EMBEDDER
    ).embed(chunk.text)

    relative_path = filename.relative_to(
        REPOSITORY_DIR
    )

    table.declare_row(
        row=CodeEmbedding(
            id=await id_generator.next_id(
                chunk.text
            ),
            repository=REPOSITORY_NAME,
            filename=str(relative_path),
            language=language or "unknown",
            code=chunk.text,
            embedding=embedding,
            start_line=chunk.start.line,
            end_line=chunk.end.line,
        )
    )


# -------------------------------------------------------------------
# Main indexing pipeline
# -------------------------------------------------------------------

@coco.fn
async def app_main(
    sourcedir: Path,
) -> None:
    """
    Build the semantic code index.
    """

    target_table = await postgres.mount_table_target(
        PG_DB,
        table_name=TABLE_NAME,
        table_schema=await postgres.TableSchema.from_class(
            CodeEmbedding,
            primary_key=["id"],
        ),
    )

    # PostgreSQL / pgvector cosine similarity index.
    target_table.declare_vector_index(
        column="embedding",
        metric="cosine",
        method="hnsw",
        m=16,
        ef_construction=64,
    )
    #FTS indexing
    target_table.declare_sql_command_attachment(
        name="code_fts_idx",
        setup_sql=(
            'CREATE INDEX IF NOT EXISTS "raca_code_fts_idx" '
            'ON "raca_code_embeddings" '
            "USING gin (to_tsvector('english', code))"
        ),
        teardown_sql=(
            'DROP INDEX IF EXISTS "raca_code_fts_idx"'
        ),
    )

    # Repository files to index.
    files = localfs.walk_dir(
        sourcedir,
        recursive=True,
        path_matcher=PatternFilePathMatcher(
            included_patterns=[
                "**/*.py",
                "**/*.js",
                "**/*.jsx",
                "**/*.ts",
                "**/*.tsx",
                "**/*.java",
                "**/*.c",
                "**/*.h",
                "**/*.cpp",
                "**/*.hpp",
                "**/*.rs",
                "**/*.go",
                "**/*.cs",
                "**/*.rb",
                "**/*.php",
                "**/*.swift",
                "**/*.kt",
                "**/*.kts",
                "**/*.scala",
                "**/*.sh",
                "**/*.sql",
                "**/*.html",
                "**/*.css",
                "**/*.scss",
                "**/*.json",
                "**/*.yaml",
                "**/*.yml",
                "**/*.toml",
                "**/*.md",
                "**/*.mdx",
            ],
            excluded_patterns=[
                "**/.git/**",
                "**/.venv/**",
                "**/venv/**",
                "**/__pycache__/**",
                "**/node_modules/**",
                "**/dist/**",
                "**/build/**",
                "**/target/**",
            ],
        ),
        live=True,
    )

    await coco.mount_each(
        process_file,
        files.items(),
        target_table,
    )


# -------------------------------------------------------------------
# CocoIndex application
# -------------------------------------------------------------------

app = coco.App(
    coco.AppConfig(
        name="RACA_CodeIndex"
    ),
    app_main,
    sourcedir=REPOSITORY_DIR,
)