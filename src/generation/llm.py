from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import inspect
from typing import AsyncIterator

import httpx
from openai import APIConnectionError, APIStatusError, AsyncOpenAI

from src.context.builder import ContextResult, estimate_tokens
from src.generation.modes import GenerationMode, get_mode_instruction
from src.generation.providers import (
    DEFAULT_MODEL,
    PROVIDERS_BY_ID,
    ModelProvider,
    configured_providers,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_OUTPUT_TOKENS = 8192
DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 0.95
DEFAULT_TIMEOUT = httpx.Timeout(45.0, connect=10.0)
LOCAL_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=180.0,
    write=30.0,
    pool=10.0,
)

SYSTEM_PROMPT = """
You are RACA, a repository-aware coding assistant. Solve the user's query using the supplied repository context as your primary source of truth and conversation history for prior references.

Rules:
1. Ground repository answers strictly in the supplied context. Never invent files, functions, classes, variables, APIs, configs, or implementation details, and never claim to inspect unprovided files.
2. If context is insufficient, state so clearly.
3. Clearly distinguish repository facts, code explanations, and modification suggestions.
4. Cite relevant file names and line ranges from context when helpful.
5. For code changes, provide practical implementations, specify where to apply them, and preserve existing architecture/technologies unless a redesign is requested.
6. Be technically precise, concise, and clear.
7. Format responses in standard Markdown using language-tagged fenced code blocks (e.g., ```python).
""".strip()

class LLMGenerationError(RuntimeError):
    """Raised when all configured LLM providers fail to generate a response."""


class LLMGenerator:
    """Generate repository-grounded answers across OpenAI-compatible providers."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        top_p: float = DEFAULT_TOP_P,
    ) -> None:
        if model not in PROVIDERS_BY_ID:
            raise ValueError(f"Unknown LLM model selection: {model!r}.")
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be greater than zero.")
        if temperature < 0.0:
            raise ValueError("temperature must be greater than or equal to zero.")
        if not 0.0 < top_p <= 1.0:
            raise ValueError(
                "top_p must be greater than zero and less than or equal to one."
            )

        self.model = model
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.top_p = top_p
        # Keyed by (base_url, api_key) so models sharing a provider endpoint
        # reuse the same warm HTTP connection pool.
        self._clients: dict[tuple[str, str], AsyncOpenAI] = {}

    def warmup(self) -> None:
        """Pre-initialize HTTP clients for all configured providers."""
        for provider in configured_providers():
            self._client_for(provider)

    async def generate(
        self,
        context_result: ContextResult,
        history: list[dict[str, str]] | None = None,
        mode: GenerationMode = GenerationMode.EXPLAIN,
        model: str | None = None,
    ) -> str:
        if not context_result.query.strip():
            raise ValueError("ContextResult query cannot be empty.")

        messages = self._build_messages(context_result, history, mode)
        return await self._generate_response(messages, model or self.model)

    async def generate_analysis(
        self,
        query: str,
        verified_context: str,
        mode: GenerationMode = GenerationMode.EXPLAIN,
        model: str | None = None,
    ) -> str:
        if not query.strip():
            raise ValueError("Analysis query cannot be empty.")
        if not verified_context.strip():
            raise ValueError("Verified repository context cannot be empty.")

        return await self.generate(
            ContextResult(
                query=query,
                context=verified_context,
                chunks=[],
                estimated_tokens=estimate_tokens(verified_context),
            ),
            mode=mode,
            model=model,
        )

    async def stream_generate(
        self,
        context_result: ContextResult,
        history: list[dict[str, str]] | None = None,
        mode: GenerationMode = GenerationMode.EXPLAIN,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        if not context_result.query.strip():
            raise ValueError("ContextResult query cannot be empty.")

        messages = self._build_messages(context_result, history, mode)
        async for chunk in self._stream_response(messages, model or self.model):
            yield chunk

    async def stream_analysis(
        self,
        query: str,
        verified_context: str,
        mode: GenerationMode = GenerationMode.EXPLAIN,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        if not query.strip():
            raise ValueError("Analysis query cannot be empty.")
        if not verified_context.strip():
            raise ValueError("Verified repository context cannot be empty.")

        async for chunk in self.stream_generate(
            ContextResult(
                query=query,
                context=verified_context,
                chunks=[],
                estimated_tokens=estimate_tokens(verified_context),
            ),
            mode=mode,
            model=model,
        ):
            yield chunk

    async def _generate_response(
        self,
        messages: list[dict[str, str]],
        preferred_model: str,
    ) -> str:
        if preferred_model not in PROVIDERS_BY_ID:
            raise ValueError(f"Unknown LLM model selection: {preferred_model!r}.")

        providers = self._fallback_order(preferred_model)
        if not providers:
            raise LLMGenerationError(
                "No LLM providers are configured. Add provider API keys to .env."
            )

        failures: list[str] = []
        for provider in providers:
            try:
                client = self._client_for(provider)
                response = await client.chat.completions.create(
                    model=provider.model,
                    messages=messages,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    max_tokens=self.max_output_tokens,
                    stream=False,
                )
                if not response.choices:
                    raise ValueError("Provider returned no completion choices.")
                content = response.choices[0].message.content
                if not content or not content.strip():
                    raise ValueError("Provider returned an empty response.")
                logger.info(
                    "Generated response with model %s (%s).",
                    provider.id,
                    provider.model,
                )
                return content.strip()
            except Exception as exc:
                reason = self._failure_reason(exc)
                failures.append(f"{provider.label}: {reason}")
                logger.warning(
                    "LLM model %s (%s) failed with %s; trying the next "
                    "configured model.",
                    provider.id,
                    provider.model,
                    reason,
                )

        raise LLMGenerationError(
            "All configured LLM providers failed. " + "; ".join(failures)
        )



    async def _stream_response(
        self,
        messages: list[dict[str, str]],
        preferred_model: str,) -> AsyncIterator[str]:
        if preferred_model not in PROVIDERS_BY_ID:
            raise ValueError(f"Unknown LLM model selection: {preferred_model!r}.")

        providers = self._fallback_order(preferred_model)
        if not providers:
            raise LLMGenerationError(
                "No LLM providers are configured. Add provider API keys to .env."
            )

        failures: list[str] = []
        for provider in providers:
            yielded_any = False
            try:
                client = self._client_for(provider)
                stream = await client.chat.completions.create(
                    model=provider.model,
                    messages=messages,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    max_tokens=self.max_output_tokens,
                    stream=True,
                )
                try:
                    async for chunk in stream:
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        if delta is None or not delta.content:
                            continue

                        text = delta.content
                        if not yielded_any:
                            # Strip leading whitespace on initial chunk without dropping the yield flag
                            text = text.lstrip()
                            yielded_any = True
                            logger.info(
                                "Streaming response with model %s (%s).",
                                provider.id,
                                provider.model,
                            )
                            if not text:
                                continue
                        yield text
                finally:
                    # Prioritize asynchronous cleanup (.aclose) over synchronous (.close)
                    if hasattr(stream, "aclose"):
                        await stream.aclose()
                    elif hasattr(stream, "close"):
                        res = stream.close()
                        if inspect.isawaitable(res):
                            await res

                if not yielded_any:
                    raise ValueError("Provider returned an empty response.")
                return
            except Exception as exc:
                reason = self._failure_reason(exc)
                if yielded_any:
                    logger.error(
                        "LLM model %s (%s) stream interrupted after partial "
                        "output: %s",
                        provider.id,
                        provider.model,
                        reason,
                    )
                    raise LLMGenerationError(
                        f"{provider.label} stream interrupted: {reason}"
                    ) from exc

                failures.append(f"{provider.label}: {reason}")
                logger.warning(
                    "LLM model %s (%s) failed with %s; trying the next "
                    "configured model.",
                    provider.id,
                    provider.model,
                    reason,
                )

        raise LLMGenerationError(
            "All configured LLM providers failed. " + "; ".join(failures)
        )

    def _client_for(self, provider: ModelProvider) -> AsyncOpenAI:
            credentials = provider.credentials()
            if credentials is None:
                raise ValueError(f"{provider.label} is not configured.")
            api_key, base_url = credentials
            cache_key = (base_url, api_key)

            client = self._clients.get(cache_key)
            if client is not None:
                return client

            is_local = provider.id == "local-qwen2.5-coder-3b"
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                max_retries=0,
                timeout=LOCAL_TIMEOUT if is_local else DEFAULT_TIMEOUT,
                default_headers=(
                    {"ngrok-skip-browser-warning": "true"} if is_local else None
                ),
            )
            self._clients[cache_key] = client
            return client

    @staticmethod
    def _fallback_order(preferred_model: str) -> tuple[ModelProvider, ...]:
        providers = tuple(PROVIDERS_BY_ID.values())
        start = next(
            index
            for index, provider in enumerate(providers)
            if provider.id == preferred_model
        )
        ordered = providers[start:] + providers[:start]
        return tuple(
            provider for provider in ordered if provider.is_configured()
        )

    @staticmethod
    def _failure_reason(exc: Exception) -> str:
        detail = str(exc).strip()
        cause = f" ({type(exc.__cause__).__name__}: {exc.__cause__})" if exc.__cause__ else ""
        if isinstance(exc, APIStatusError):
            error = f"{type(exc).__name__} (HTTP {exc.status_code})"
        else:
            error = type(exc).__name__
        if detail:
            return f"{error}: {detail}{cause}"
        if isinstance(exc, APIConnectionError):
            return f"{error}: provider connection failed{cause}."
        if isinstance(exc, ValueError):
            return f"{error}: invalid provider response."
        return f"{error}: no additional error detail."

    @staticmethod
    def _build_messages(
        context_result: ContextResult,
        history: list[dict[str, str]] | None = None,
        mode: GenerationMode = GenerationMode.EXPLAIN,
    ) -> list[dict[str, str]]:
        mode_instruction = get_mode_instruction(mode)
        user_message = (
            f"RESPONSE MODE:\n"
            f"{mode.value}\n\n"
            f"MODE INSTRUCTIONS:\n"
            f"{mode_instruction}\n\n"
            f"REPOSITORY CONTEXT:\n"
            f"{context_result.context}\n\n"
            "Answer the following user query using the repository "
            "context above:\n\n"
            f"{context_result.query}"
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return messages

    async def close(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()

    async def __aenter__(self) -> "LLMGenerator":
        return self

    async def __aexit__(
        self,
        _exc_type,
        _exc_value,
        _traceback,
    ) -> None:
        await self.close()