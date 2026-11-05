from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from fastapi.middleware.cors import CORSMiddleware

from src.generation.modes import GenerationMode

from src.pipeline import (
    PipelineError,
    RACAPipeline,
)

from fastapi import (
    FastAPI,
    HTTPException,
)

from workspace import (
    WorkspaceError,
    WorkspaceFileError,
    WorkspaceNotReadyError,
    WorkspacePathError,
)

from assistant import (
    AssistantError,
    AssistantNotReadyError,
)

from dotenv import load_dotenv

load_dotenv()

class RepositoryIngestRequest(BaseModel):
    github_url: str

class WorkspaceEntryResponse(BaseModel):
    name: str
    path: str
    type: str
    children: list["WorkspaceEntryResponse"] | None = None


class WorkspaceFileResponse(BaseModel):
    path: str
    name: str
    extension: str
    size: int
    content: str

class AssistantRequest(BaseModel):
    query: str
    file_path: str | None = None
    cursor_line: int | None = None
    cursor_column: int | None = None
    selected_code: str | None = None
    mode: GenerationMode = GenerationMode.EXPLAIN

    
pipeline = RACAPipeline()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await pipeline.restore_existing_repository()
    except PipelineError as exc:
        print(f"Repository restoration skipped: {exc}")

    yield



def _workspace_entry_to_dict(
    entry,
) -> dict:
    return {
        "name": entry.name,
        "path": entry.path,
        "type": entry.type,
        "children": (
            [
                _workspace_entry_to_dict(
                    child
                )
                for child in (
                    entry.children or []
                )
            ]
            if entry.children is not None
            else None
        ),
    }

app = FastAPI(
    title="Project RACA",
    description=(
        "Repository-Aware AI Coding Assistant"
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get(
    "/api/workspace/tree",
    response_model=WorkspaceEntryResponse,
)
async def workspace_tree() -> dict:
    """
    Return the complete file/folder tree of the active repository.
    """

    try:
        tree = pipeline.workspace.get_tree()

    except WorkspaceNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except WorkspaceError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    return {
        "name": tree.name,
        "path": tree.path,
        "type": tree.type,
        "children": (
            [
                _workspace_entry_to_dict(
                    child
                )
                for child in (
                    tree.children or []
                )
            ]
            if tree.children is not None
            else None
        ),
    }

@app.get(
    "/api/workspace/file/{file_path:path}",
    response_model=WorkspaceFileResponse,
)
async def workspace_file(
    file_path: str,
) -> WorkspaceFileResponse:
    """
    Return the contents and metadata of one repository file.
    """

    try:
        file = pipeline.workspace.read_file(
            file_path
        )

    except WorkspaceNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except WorkspacePathError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except WorkspaceFileError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    return WorkspaceFileResponse(
        path=file.path,
        name=file.name,
        extension=file.extension,
        size=file.size,
        content=file.content,
    )

@app.get("/health")
async def health() -> dict[str, str]:
    """Basic backend health check."""

    return {
        "status": "ok",
        "service": "raca-backend",
    }


@app.get("/api/repository/status")
async def repository_status() -> dict[str, object]:
    """
    Return the repository currently active in this application process.
    """

    return {
        "repository": pipeline.current_repository,
        "ready": (
            pipeline.current_repository
            is not None
        ),
    }


@app.post("/api/repository/ingest")
async def ingest_repository(
    request: RepositoryIngestRequest,
) -> dict[str, object]:
    """
    Ingest a GitHub repository and build its searchable data.
    """

    try:
        result = await pipeline.ingest_repository(
            request.github_url
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except PipelineError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    return {
        "status": "ready",
        "repository": result.repository,
        "local_path": str(
            result.local_path
        ),
        "postgres_indexed": (
            result.postgres_indexed
        ),
        "neo4j_indexed": (
            result.neo4j_indexed
        ),
    }


@app.delete("/api/repository/clear")
async def clear_repository_workspace() -> dict[str, object]:
    """
    Clear all current RACA repository data while preserving the
    PostgreSQL and Neo4j infrastructure.
    """

    try:
        result = await pipeline.clear_workspace()

    except PipelineError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    return {
        "status": "cleared",
        "postgres_rows_deleted": (
            result.postgres_deleted
        ),
        "neo4j_nodes_deleted": (
            result.neo4j_deleted
        ),
        "local_repositories_deleted": (
            result.repositories_deleted
        ),
        "cocoindex_state_files_deleted": (
            result.state_files_deleted
        ),
    }

@app.post("/api/assistant/ask")
async def assistant_ask(
    request: AssistantRequest,
) -> dict[str, str]:

    try:
        result = await pipeline.assistant.ask(
            query=request.query,
            file_path=request.file_path,
            cursor_line=request.cursor_line,
            cursor_column=request.cursor_column,
            selected_code=request.selected_code,
            mode=request.mode,
        )

    except AssistantNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except AssistantError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    return {
        "response": result.response,
    }

@app.post("/api/assistant/ask/stream")
async def assistant_ask_stream(
    request: AssistantRequest,
) -> StreamingResponse:

    async def generate():
        async for chunk in pipeline.assistant.stream_ask(
            query=request.query,
            file_path=request.file_path,
            cursor_line=request.cursor_line,
            cursor_column=request.cursor_column,
            selected_code=request.selected_code,
            mode=request.mode,
        ):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )