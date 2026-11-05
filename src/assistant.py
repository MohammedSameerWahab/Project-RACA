from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from src.context.builder import (
    ContextBuilder,
    ContextResult,
    estimate_tokens,
)
from generation.llm import LLMGenerator
from retrieval.hybrid import HybridRetriever
from workspace import RepositoryWorkspace

from generation.modes import GenerationMode

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AssistantError(RuntimeError):
    """Base assistant error."""


class AssistantNotReadyError(AssistantError):
    """Raised when no repository is active."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CursorContext:
    file_path: str
    line: int
    column: int
    selected_code: str | None
    surrounding_code: str


@dataclass(frozen=True)
class AssistantResult:
    response: str
    model: str
    repository: str
    context_chunks: int
    context_tokens: int
    file_path: str | None
    cursor_line: int | None
    cursor_column: int | None


# ---------------------------------------------------------------------------
# Assistant
# ---------------------------------------------------------------------------


class RepositoryAssistant:
    """
    Coordinates:

        cursor context
              ↓
        hybrid retrieval
              ↓
        context builder
              ↓
        conversation history
              ↓
        LLM generation
    """

    MAX_HISTORY_MESSAGES = 10

    def __init__(
        self,
        workspace: RepositoryWorkspace,
    ) -> None:
        self.workspace = workspace

        self.retriever = HybridRetriever()

        self.context_builder = ContextBuilder(
            max_context_tokens=4000,
            max_chunk_tokens=1000,
        )

        # Created once and reused for the application session.
        self.llm = LLMGenerator()

        # Only final user/assistant messages are stored here.
        self.history: list[dict[str, str]] = []

    # -----------------------------------------------------------------------
    # Normal assistant request
    # -----------------------------------------------------------------------

    async def ask(
        self,
        query: str,
        file_path: str | None = None,
        cursor_line: int | None = None,
        cursor_column: int | None = None,
        selected_code: str | None = None,
        mode: GenerationMode = GenerationMode.EXPLAIN,
    ) -> AssistantResult:
        context_result, cursor_context = await self._prepare_context(
            query=query,
            file_path=file_path,
            cursor_line=cursor_line,
            cursor_column=cursor_column,
            selected_code=selected_code,
        )

        history_for_request = list(self.history)

        response = await self.llm.generate(
            context_result,
            history=history_for_request,
            mode=mode,
        )

        self._append_history(
            user_message=query,
            assistant_message=response,
        )

        repository = self.workspace.repository_path.name

        return AssistantResult(
            response=response,
            model=self.llm.model,
            repository=repository,
            context_chunks=len(context_result.chunks),
            context_tokens=context_result.estimated_tokens,
            file_path=(
                cursor_context.file_path
                if cursor_context
                else None
            ),
            cursor_line=(
                cursor_context.line
                if cursor_context
                else None
            ),
            cursor_column=(
                cursor_context.column
                if cursor_context
                else None
            ),
        )

    # -----------------------------------------------------------------------
    # Streaming assistant request
    # -----------------------------------------------------------------------

    async def stream_ask(
        self,
        query: str,
        file_path: str | None = None,
        cursor_line: int | None = None,
        cursor_column: int | None = None,
        selected_code: str | None = None,
        mode: GenerationMode = GenerationMode.EXPLAIN,
    ) -> AsyncIterator[str]:

        context_result, _ = await self._prepare_context(
            query=query,
            file_path=file_path,
            cursor_line=cursor_line,
            cursor_column=cursor_column,
            selected_code=selected_code,
        )

        history_for_request = list(self.history)

        full_response: list[str] = []

        async for chunk in self.llm.stream_generate(
            context_result,
            history=history_for_request,
            mode=mode,
        ):
            full_response.append(chunk)
            yield chunk

        complete_response = "".join(full_response).strip()

        if complete_response:
            self._append_history(
                user_message=query,
                assistant_message=complete_response,
            )

    # -----------------------------------------------------------------------
    # Context preparation
    # -----------------------------------------------------------------------

    async def _prepare_context(
        self,
        query: str,
        file_path: str | None,
        cursor_line: int | None,
        cursor_column: int | None,
        selected_code: str | None,
    ) -> tuple[ContextResult, CursorContext | None]:

        if not query.strip():
            raise ValueError(
                "Assistant query cannot be empty."
            )

        if self.workspace.repository_path is None:
            raise AssistantNotReadyError(
                "No repository is currently active."
            )

        cursor_context = self._build_cursor_context(
            file_path=file_path,
            cursor_line=cursor_line,
            cursor_column=cursor_column,
            selected_code=selected_code,
        )

        retrieval_query = self._build_retrieval_query(
            query=query,
            cursor_context=cursor_context,
        )

        results = await self.retriever.search(
            retrieval_query,
            top_k=10,
            retrieval_k=20,
        )

        context_result = self.context_builder.build(
            query=query,
            results=results,
        )

        context_result = self._add_cursor_context(
            context_result,
            cursor_context,
        )

        return context_result, cursor_context

    # -----------------------------------------------------------------------
    # Cursor context
    # -----------------------------------------------------------------------

    def _build_cursor_context(
        self,
        file_path: str | None,
        cursor_line: int | None,
        cursor_column: int | None,
        selected_code: str | None,
    ) -> CursorContext | None:

        if not file_path:
            return None

        line = cursor_line or 1
        column = cursor_column or 1

        if line < 1:
            raise ValueError(
                "Cursor line must be greater than or equal to 1."
            )

        if column < 1:
            raise ValueError(
                "Cursor column must be greater than or equal to 1."
            )

        file = self.workspace.read_file(file_path)

        lines = file.content.splitlines()

        if not lines:
            surrounding_code = ""
        else:
            cursor_index = min(
                line - 1,
                len(lines) - 1,
            )

            start = max(
                0,
                cursor_index - 20,
            )

            end = min(
                len(lines),
                cursor_index + 21,
            )

            surrounding: list[str] = []

            for index in range(start, end):
                marker = (
                    ">> "
                    if index == cursor_index
                    else "   "
                )

                surrounding.append(
                    f"{marker}{index + 1:>5}: {lines[index]}"
                )

            surrounding_code = "\n".join(
                surrounding
            )

        return CursorContext(
            file_path=file_path,
            line=line,
            column=column,
            selected_code=selected_code or None,
            surrounding_code=surrounding_code,
        )

    # -----------------------------------------------------------------------
    # Retrieval query
    # -----------------------------------------------------------------------

    @staticmethod
    def _build_retrieval_query(
        query: str,
        cursor_context: CursorContext | None,
    ) -> str:

        parts = [query.strip()]

        if cursor_context:
            parts.append(
                f"Current file: {cursor_context.file_path}"
            )

            parts.append(
                f"Current cursor position: "
                f"line {cursor_context.line}, "
                f"column {cursor_context.column}"
            )

            if cursor_context.selected_code:
                parts.append(
                    "Selected code:\n"
                    f"{cursor_context.selected_code}"
                )

        return "\n\n".join(parts)

    # -----------------------------------------------------------------------
    # Add cursor context to final LLM context
    # -----------------------------------------------------------------------

    @staticmethod
    def _add_cursor_context(
        context_result: ContextResult,
        cursor_context: CursorContext | None,
    ) -> ContextResult:

        if cursor_context is None:
            return context_result

        sections = [
            "CURRENT EDITOR CONTEXT",
            f"File: {cursor_context.file_path}",
            (
                f"Cursor: line {cursor_context.line}, "
                f"column {cursor_context.column}"
            ),
            "",
            cursor_context.surrounding_code,
        ]

        if cursor_context.selected_code:
            sections.extend(
                [
                    "",
                    "SELECTED CODE",
                    cursor_context.selected_code,
                ]
            )

        editor_context = "\n".join(sections)

        combined_context = (
            editor_context
            + "\n\n"
            + context_result.context
        )

        return ContextResult(
            query=context_result.query,
            context=combined_context,
            chunks=context_result.chunks,
            estimated_tokens=estimate_tokens(
                combined_context
            ),
        )

    # -----------------------------------------------------------------------
    # History
    # -----------------------------------------------------------------------

    def _append_history(
        self,
        user_message: str,
        assistant_message: str,
    ) -> None:

        self.history.append(
            {
                "role": "user",
                "content": user_message,
            }
        )

        self.history.append(
            {
                "role": "assistant",
                "content": assistant_message,
            }
        )

        if len(self.history) > self.MAX_HISTORY_MESSAGES:
            self.history = self.history[
                -self.MAX_HISTORY_MESSAGES:
            ]

    def clear_history(self) -> None:
        """Clear conversation history."""

        self.history.clear()