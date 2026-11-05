from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.retrieval.hybrid import HybridSearchResult


DEFAULT_MAX_CONTEXT_TOKENS = 4000
DEFAULT_MAX_CHUNK_TOKENS = 1000
CHARS_PER_TOKEN = 4


@dataclass
class ContextChunk:
    """A chunk selected for the final LLM context."""

    repository: str
    filename: str
    language: str
    start_line: int
    end_line: int
    code: str
    hybrid_score: float
    graph_kind: str | None = None
    graph_node: str | None = None
    relation: str | None = None

    @property
    def estimated_tokens(self) -> int:
        return estimate_tokens(self.code)


@dataclass
class ContextResult:
    """The final context prepared for the generation layer."""

    query: str
    context: str
    chunks: list[ContextChunk]
    estimated_tokens: int


def estimate_tokens(text: str) -> int:
    """Estimate token count without adding a tokenizer dependency."""
    if not text:
        return 0

    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


def normalize_filename(filename: str) -> str:
    """Normalize Windows paths so equivalent paths compare equally."""
    return filename.replace("\\", "/").strip()


def make_chunk_key(result: HybridSearchResult) -> tuple:
    """Create a stable identity for a retrieved code chunk."""
    return (
        result.repository,
        normalize_filename(result.filename),
        result.start_line,
        result.end_line,
    )


def mergeable(a: ContextChunk, b: ContextChunk) -> bool:
    """
    Return True when two chunks belong to the same file and overlap/touch.

    We deliberately do not merge chunks separated by a gap. That prevents
    unrelated parts of a file from being pulled into one context block.
    """
    return (
        a.repository == b.repository
        and normalize_filename(a.filename) == normalize_filename(b.filename)
        and b.start_line <= a.end_line + 1
    )


def merge_chunks(chunks: list[ContextChunk]) -> list[ContextChunk]:
    """
    Merge overlapping or directly adjacent chunks from the same file.

    The merged chunk keeps the highest hybrid score and combines graph
    metadata when possible.
    """
    if not chunks:
        return []

    ordered = sorted(
        chunks,
        key=lambda chunk: (
            chunk.repository,
            normalize_filename(chunk.filename),
            chunk.start_line,
            chunk.end_line,
        ),
    )

    merged: list[ContextChunk] = []

    for chunk in ordered:
        if not merged or not mergeable(merged[-1], chunk):
            merged.append(
                ContextChunk(
                    repository=chunk.repository,
                    filename=chunk.filename,
                    language=chunk.language,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    code=chunk.code,
                    hybrid_score=chunk.hybrid_score,
                    graph_kind=chunk.graph_kind,
                    graph_node=chunk.graph_node,
                    relation=chunk.relation,
                )
            )
            continue

        previous = merged[-1]

        # Merge line ranges without duplicating the overlapping lines.
        overlap_lines = max(
            0,
            previous.end_line - chunk.start_line + 1,
        )

        chunk_lines = chunk.code.splitlines()

        if chunk.end_line > previous.end_line:
            if overlap_lines < len(chunk_lines):
                non_overlapping = chunk_lines[overlap_lines:]
                if non_overlapping:
                    previous.code = (
                        previous.code.rstrip()
                        + "\n"
                        + "\n".join(non_overlapping).lstrip()
                    )

            previous.end_line = chunk.end_line

        previous.hybrid_score = max(
            previous.hybrid_score,
            chunk.hybrid_score,
        )

        if previous.graph_kind is None:
            previous.graph_kind = chunk.graph_kind

        if previous.graph_node is None:
            previous.graph_node = chunk.graph_node

        if previous.relation is None:
            previous.relation = chunk.relation

    return merged


class ContextBuilder:
    """
    Build a compact, structured context from hybrid retrieval results.

    Responsibilities:
        - remove duplicate chunks
        - keep results in hybrid relevance order
        - merge overlapping/adjacent chunks from the same file
        - preserve graph metadata
        - limit individual chunk size
        - enforce the final context token budget
        - produce LLM-ready formatted text
    """

    def __init__(
        self,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS,
    ) -> None:
        if max_context_tokens <= 0:
            raise ValueError(
                "max_context_tokens must be greater than zero."
            )

        if max_chunk_tokens <= 0:
            raise ValueError(
                "max_chunk_tokens must be greater than zero."
            )

        if max_chunk_tokens > max_context_tokens:
            raise ValueError(
                "max_chunk_tokens cannot exceed max_context_tokens."
            )

        self.max_context_tokens = max_context_tokens
        self.max_chunk_tokens = max_chunk_tokens

    def build(
        self,
        query: str,
        results: Iterable[HybridSearchResult],
    ) -> ContextResult:
        """
        Build the final context for a user query.

        Results are expected to already be ranked by HybridRetriever.
        """
        if not query.strip():
            raise ValueError("Context query cannot be empty.")

        unique: dict[tuple, HybridSearchResult] = {}

        for result in results:
            key = make_chunk_key(result)

            # Keep the highest-scoring version if duplicate results are
            # supplied by the retrieval layer.
            existing = unique.get(key)
            if existing is None or result.hybrid_score > existing.hybrid_score:
                unique[key] = result

        selected = [
            self._to_context_chunk(result)
            for result in unique.values()
        ]

        # HybridRetriever already ranks by relevance. Preserve that ranking
        # while preparing the context.
        selected.sort(
            key=lambda chunk: chunk.hybrid_score,
            reverse=True,
        )

        selected = [
            self._limit_chunk_size(chunk)
            for chunk in selected
        ]

        selected = merge_chunks(selected)

        # Merging changes the order, so restore relevance ordering.
        selected.sort(
            key=lambda chunk: chunk.hybrid_score,
            reverse=True,
        )

        selected = self._apply_context_budget(selected)

        context = self._format_context(query, selected)

        return ContextResult(
            query=query,
            context=context,
            chunks=selected,
            estimated_tokens=estimate_tokens(context),
        )

    def _to_context_chunk(
        self,
        result: HybridSearchResult,
    ) -> ContextChunk:
        return ContextChunk(
            repository=result.repository,
            filename=normalize_filename(result.filename),
            language=result.language,
            start_line=result.start_line,
            end_line=result.end_line,
            code=result.code,
            hybrid_score=result.hybrid_score,
            graph_kind=result.graph_kind,
            graph_node=result.graph_node,
            relation=result.relation,
        )

    def _limit_chunk_size(
        self,
        chunk: ContextChunk,
    ) -> ContextChunk:
        max_characters = self.max_chunk_tokens * CHARS_PER_TOKEN

        if len(chunk.code) <= max_characters:
            return chunk

        truncated = chunk.code[:max_characters]

        # Prefer a complete line over cutting code in the middle.
        last_newline = truncated.rfind("\n")
        if last_newline > max_characters // 2:
            truncated = truncated[:last_newline]

        chunk.code = truncated.rstrip() + "\n# ... context truncated ..."
        return chunk

    def _apply_context_budget(
        self,
        chunks: list[ContextChunk],
    ) -> list[ContextChunk]:
        selected: list[ContextChunk] = []
        used_tokens = estimate_tokens(self._context_header())

        for chunk in chunks:
            block = self._format_chunk(chunk)
            block_tokens = estimate_tokens(block)

            if used_tokens + block_tokens > self.max_context_tokens:
                continue

            selected.append(chunk)
            used_tokens += block_tokens

        return selected

    @staticmethod
    def _context_header() -> str:
        return (
            "Repository context retrieved for the user query.\n"
            "Use the following repository evidence when answering.\n"
        )

    def _format_context(
        self,
        query: str,
        chunks: list[ContextChunk],
    ) -> str:
        sections = [
            "Repository context retrieved for the user query.",
            f"User query: {query}",
            "",
        ]

        if not chunks:
            sections.append("No repository context was selected.")
            return "\n".join(sections)

        for index, chunk in enumerate(chunks, start=1):
            sections.append(
                self._format_chunk(
                    chunk,
                    index=index,
                )
            )

        return "\n".join(sections)

    @staticmethod
    def _format_chunk(
        chunk: ContextChunk,
        index: int | None = None,
    ) -> str:
        label = f"Context {index}" if index is not None else "Context"

        lines = [
            f"### {label}",
            f"Repository: {chunk.repository}",
            f"File: {normalize_filename(chunk.filename)}",
            f"Lines: {chunk.start_line}-{chunk.end_line}",
            f"Language: {chunk.language}",
            f"Hybrid score: {chunk.hybrid_score:.4f}",
        ]

        if chunk.graph_kind is not None:
            lines.append(f"Graph kind: {chunk.graph_kind}")

        if chunk.graph_node is not None:
            lines.append(f"Graph node: {chunk.graph_node}")

        if chunk.relation is not None:
            lines.append(f"Relationship: {chunk.relation}")

        lines.extend(
            [
                "",
                "```",
                chunk.code.rstrip(),
                "```",
                "",
            ]
        )

        return "\n".join(lines)


async def main() -> None:
    from src.retrieval.hybrid import HybridRetriever

    query = input("Enter context query: ").strip()

    retriever = HybridRetriever()

    # Retrieve more candidates than the final context needs. The context
    # builder performs the final selection under its token budget.
    results = await retriever.search(
        query,
        top_k=10,
        retrieval_k=20,
    )

    builder = ContextBuilder(
        max_context_tokens=4000,
        max_chunk_tokens=1000,
    )

    context_result = builder.build(
        query=query,
        results=results,
    )

    print("\n" + "=" * 90)
    print("FINAL CONTEXT")
    print("=" * 90)
    print(context_result.context)
    print("=" * 90)
    print(
        f"Selected chunks: {len(context_result.chunks)}"
    )
    print(
        f"Estimated tokens: {context_result.estimated_tokens}"
    )


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
