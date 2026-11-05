from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from fastapi.middleware.cors import CORSMiddleware

from src.generation.modes import GenerationMode

from src.pipeline import (
    PipelineError,
    RACAPipeline,
)
from src.ingestion.github import GitHubRepositoryError

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
)

from src.workspace import (
    WorkspaceError,
    WorkspaceFileError,
    WorkspaceNotReadyError,
    WorkspacePathError,
)

from src.assistant import (
    AssistantError,
    AssistantNotReadyError,
)
from src.analysis.investigation import InvestigationService
from src.analysis.navigation import CodeNavigationService
from src.analysis.repository import AnalysisError, RepositoryAnalysisService
from src.generation.llm import LLMGenerationError
from src.generation.providers import (
    DEFAULT_MODEL,
    configured_providers,
    model_options,
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


class WorkspaceFileSaveRequest(BaseModel):
    content: str
    repository_key: str


class AssistantRequest(BaseModel):
    query: str
    file_path: str | None = None
    cursor_line: int | None = None
    cursor_column: int | None = None
    selected_code: str | None = None
    mode: GenerationMode = GenerationMode.EXPLAIN
    model: str = DEFAULT_MODEL


class AnalysisQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class BugInvestigationRequest(BaseModel):
    description: str = Field(min_length=1, max_length=4000)
    file_path: str | None = Field(default=None, max_length=1000)
    selected_code: str | None = Field(default=None, max_length=8000)


class StackTraceRequest(BaseModel):
    stack_trace: str = Field(min_length=1, max_length=40000)


class ExecutionFlowRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=200)


class ImprovementsRequest(BaseModel):
    scope: str
    file_path: str | None = Field(default=None, max_length=1000)
    selected_code: str | None = Field(default=None, max_length=8000)

    
pipeline = RACAPipeline()


def _repository_analysis() -> RepositoryAnalysisService:
    repository_key = pipeline.current_repository_key
    if repository_key is None:
        raise HTTPException(
            status_code=409,
            detail="No repository is active.",
        )
    return RepositoryAnalysisService(
        pipeline.workspace,
        repository_key,
        neo4j_uri=pipeline.neo4j_uri,
        neo4j_user=pipeline.neo4j_user,
        neo4j_password=pipeline.neo4j_password,
        neo4j_database=pipeline.neo4j_database,
        repository_name=pipeline.current_repository,
    )


def _navigation_service() -> CodeNavigationService:
    if pipeline.current_repository is None:
        raise HTTPException(
            status_code=409,
            detail="No repository is active.",
        )
    return CodeNavigationService(pipeline.workspace)


def _investigation_service(model: str) -> InvestigationService:
    repository = _repository_analysis()
    navigation = _navigation_service()
    assistant = pipeline.assistant
    return InvestigationService(
        repository,
        navigation,
        assistant.retriever,
        assistant.llm,
        model,
    )


async def _analysis_result(operation):
    try:
        return await operation
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (AnalysisError, LLMGenerationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except AssistantNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (WorkspacePathError, WorkspaceNotReadyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WorkspaceFileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await pipeline.restore_existing_repository()
    except PipelineError as exc:
        print(f"Repository restoration skipped: {exc}")

    try:
        yield
    finally:
        await pipeline.close()



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
    except LLMGenerationError as exc:
        raise HTTPException(
            status_code=502,
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


@app.put(
    "/api/workspace/file/{file_path:path}",
    response_model=WorkspaceFileResponse,
)
async def save_workspace_file(
    file_path: str,
    request: WorkspaceFileSaveRequest,
) -> WorkspaceFileResponse:
    try:
        file = await pipeline.save_file(
            file_path,
            request.content,
            request.repository_key,
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
        status_code = 413 if "too large" in str(exc).lower() else 404
        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        ) from exc
    except PipelineError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return WorkspaceFileResponse(
        path=file.path,
        name=file.name,
        extension=file.extension,
        size=file.size,
        content=file.content,
    )


@app.get("/api/index/status")
async def index_status() -> dict[str, str]:
    return pipeline.index_status()


@app.get("/health")
async def health() -> dict[str, str]:
    """Basic backend health check."""

    return {
        "status": "ok",
        "service": "raca-backend",
    }


@app.get("/api/llm/models")
async def llm_models() -> dict[str, object]:
    configured = configured_providers()
    default_model = configured[0].id if configured else DEFAULT_MODEL
    return {
        "models": model_options(),
        "default_model": default_model,
    }


@app.get("/api/repository/status")
async def repository_status() -> dict[str, object]:
    """
    Return the repository currently active in this application process.
    """

    return {
        "repository": pipeline.current_repository,
        "repository_key": pipeline.current_repository_key,
        "ready": (
            pipeline.current_repository
            is not None
        ),
    }


@app.get("/api/analysis/repository/profile")
async def repository_profile() -> dict[str, object]:
    try:
        return _repository_analysis().profile(pipeline.index_status())
    except AnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/analysis/repository/structure")
async def repository_structure() -> dict[str, object]:
    try:
        return _repository_analysis().structure()
    except AnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/analysis/repository/architecture")
async def repository_architecture(
    model: str = Header(default=DEFAULT_MODEL, alias="X-Raca-Model"),
) -> dict[str, object]:
    try:
        service = _investigation_service(model)
        return await _analysis_result(service.explain_architecture())
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/analysis/repository/relationships")
async def repository_relationships(
    request: AnalysisQueryRequest,
    model: str = Header(default=DEFAULT_MODEL, alias="X-Raca-Model"),
) -> dict[str, object]:
    try:
        service = _investigation_service(model)
        return await _analysis_result(
            service.explain_relationships(request.query)
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/navigation/implementation")
def locate_implementations(
    query: str = "",
    kind: str | None = None,
) -> dict[str, object]:
    try:
        results = _navigation_service().definitions(query, kind)
        return {"results": results, "count": len(results)}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/navigation/function")
def find_functions(query: str = "") -> dict[str, object]:
    try:
        service = _navigation_service()
        results = service.definitions(query)
        results = [
            item for item in results
            if item["type"] in {"function", "method"}
        ]
        return {
            "results": results,
            "count": len(results),
            "graph_coverage": "Python definitions are AST-indexed; other supported language definitions are matched from source declarations.",
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/navigation/usages")
async def find_usages(query: str = "") -> dict[str, object]:
    try:
        source_results = _navigation_service().usages(query)
        graph_results = await _repository_analysis().graph_usages(query)
        deduplicated = {
            (
                item.get("file_path"),
                item.get("line"),
                item.get("kind"),
                item.get("direction"),
            ): item
            for item in [*graph_results, *source_results]
        }
        results = list(deduplicated.values())
        results.sort(
            key=lambda item: (
                str(item.get("file_path", "")).lower(),
                int(item.get("line", 0) or 0),
            )
        )
        return {
            "results": results,
            "count": len(results),
            "coverage_note": (
                "Indexed Neo4j CALLS/IMPORTS edges are combined with AST and textual "
                "source references. Dynamic calls and generated code may not be found."
            ),
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/navigation/config")
def find_configuration_files() -> dict[str, object]:
    try:
        results = _navigation_service().configurations()
        return {"results": results, "count": len(results)}
    except HTTPException:
        raise


@app.post("/api/bugs/locations")
async def investigate_bug(
    request: BugInvestigationRequest,
    model: str = Header(default=DEFAULT_MODEL, alias="X-Raca-Model"),
) -> dict[str, object]:
    try:
        service = _investigation_service(model)
        return await _analysis_result(
            service.investigate_bug(
                request.description,
                request.file_path,
                request.selected_code,
            )
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/bugs/stacktrace")
async def explain_stack_trace(
    request: StackTraceRequest,
    model: str = Header(default=DEFAULT_MODEL, alias="X-Raca-Model"),
) -> dict[str, object]:
    try:
        service = _investigation_service(model)
        return await _analysis_result(
            service.explain_stack_trace(request.stack_trace)
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/bugs/execution-flow")
async def trace_execution_flow(
    request: ExecutionFlowRequest,
    model: str = Header(default=DEFAULT_MODEL, alias="X-Raca-Model"),
) -> dict[str, object]:
    try:
        service = _investigation_service(model)
        return await _analysis_result(
            service.execution_flow(request.symbol)
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/bugs/improvements")
async def suggest_improvements(
    request: ImprovementsRequest,
    model: str = Header(default=DEFAULT_MODEL, alias="X-Raca-Model"),
) -> dict[str, object]:
    try:
        service = _investigation_service(model)
        return await _analysis_result(
            service.suggest_improvements(
                request.scope,
                request.file_path,
                request.selected_code,
            )
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
    except GitHubRepositoryError as exc:
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
        "repository_key": result.repository_key,
        "local_path": str(
            result.local_path
        ),
        "postgres_indexed": (
            result.postgres_indexed
        ),
        "neo4j_indexed": (
            result.neo4j_indexed
        ),
        "cleanup_warning": result.cleanup_warning,
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
            model=request.model,
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

    except LLMGenerationError as exc:
        raise HTTPException(
            status_code=502,
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
    if not request.query.strip():
        raise HTTPException(
            status_code=400,
            detail="Assistant query cannot be empty.",
        )

    try:
        assistant = pipeline.assistant
    except AssistantNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    try:
        result = await assistant.ask(
            query=request.query,
            file_path=request.file_path,
            cursor_line=request.cursor_line,
            cursor_column=request.cursor_column,
            selected_code=request.selected_code,
            mode=request.mode,
            model=request.model,
        )
    except AssistantNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def generate():
        response = result.response
        for offset in range(0, len(response), 128):
            yield response[offset : offset + 128]

    return StreamingResponse(
        generate(),
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )