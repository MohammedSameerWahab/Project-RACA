from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_LLM_MODEL = "qwen2.5-coder:7b"

SYSTEM_PROMPT = """You are RACA, a repository-aware coding assistant.

Answer the user's question using the repository context provided below.

Rules:
1. Base repository-specific claims on the supplied context.
2. Do not invent files, functions, classes, relationships, or behavior that are not supported by the context.
3. When the context is insufficient, say what information is missing instead of guessing.
4. When referring to repository code, include the relevant file path and line range when available.
5. Explain code clearly and concisely.
6. You may use general programming knowledge to explain concepts, but distinguish it from facts established by the repository context.
7. Do not claim that you inspected the repository directly. You only have the context supplied to you.

Repository context:
"""


@dataclass
class LLMResponse:
    model: str
    response: str


class OllamaLLM:
    """Minimal local Ollama client for Project RACA."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        self.model = (
            model
            or os.environ.get("RACA_LLM_MODEL")
            or DEFAULT_LLM_MODEL
        )
        self.base_url = (
            base_url
            or os.environ.get("RACA_LLM_URL")
            or DEFAULT_OLLAMA_URL
        ).rstrip("/")
        self.timeout = timeout

    async def generate(
        self,
        query: str,
        context: str,
    ) -> LLMResponse:
        if not query.strip():
            raise ValueError("Generation query cannot be empty.")

        if not context.strip():
            raise ValueError("Generation context cannot be empty.")

        payload = {
            "model": self.model,
            "prompt": self._build_prompt(query, context),
            "stream": False,
        }

        response_text = await asyncio.to_thread(
            self._request,
            payload,
        )

        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama returned invalid JSON.") from exc

        response = data.get("response")

        if not isinstance(response, str) or not response.strip():
            raise RuntimeError("Ollama returned no generated response.")

        return LLMResponse(
            model=self.model,
            response=response.strip(),
        )

    @staticmethod
    def _build_prompt(query: str, context: str) -> str:
        return (
            f"{SYSTEM_PROMPT}\n"
            f"{context}\n\n"
            "User question:\n"
            f"{query}\n\n"
            "Answer:"
        )

    def _request(self, payload: dict) -> str:
        url = f"{self.base_url}/api/generate"
        body = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
            ) as response:
                return response.read().decode("utf-8")

        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode(
                "utf-8",
                errors="replace",
            )
            raise RuntimeError(
                f"Ollama HTTP error {exc.code}: {error_body}"
            ) from exc

        except urllib.error.URLError as exc:
            raise RuntimeError(
                "Could not connect to Ollama at "
                f"{self.base_url}. Make sure Ollama is running."
            ) from exc


async def main() -> None:
    query = input("Enter generation query: ").strip()

    from context.builder import ContextBuilder
    from retrieval.hybrid import HybridRetriever

    retriever = HybridRetriever()
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

    if not context_result.chunks:
        print("\nNo repository context was retrieved.")
        return

    llm = OllamaLLM()

    print("\nGenerating response...")
    result = await llm.generate(
        query=query,
        context=context_result.context,
    )

    print("\n" + "=" * 90)
    print("RACA RESPONSE")
    print("=" * 90)
    print(f"Model: {result.model}")
    print("-" * 90)
    print(result.response)
    print("=" * 90)


if __name__ == "__main__":
    asyncio.run(main())
