from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from openai import AsyncOpenAI
from openai import APIConnectionError, APIStatusError

from src.context.builder import ContextResult, estimate_tokens
from src.generation.modes import GenerationMode, get_mode_instruction
from src.generation.providers import (
    DEFAULT_MODEL,
    PROVIDERS_BY_ID,
    ModelProvider,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_OUTPUT_TOKENS = 4096
DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 0.95

SYSTEM_PROMPT = """
You are RACA, a repository-aware coding assistant.

Your task is to answer software-development questions using the
repository context supplied with the user's query.

The repository context is the primary source of truth for
repository-specific questions.

Follow these rules:

1. Use the supplied repository context when answering questions
   about the repository.

2. Do not invent files, functions, classes, variables, APIs,
   configuration values, or implementation details that are not
   supported by the supplied repository context.

3. If the repository context is insufficient to answer a
   repository-specific question, clearly say that the available
   context is insufficient.

4. Distinguish between:
   - facts that are present in the repository,
   - reasonable explanations of the existing code,
   - and suggestions for modifying or improving the code.

5. When explaining code, refer to the relevant file names and
   line ranges from the supplied context when useful.

6. When the user asks for a code change, provide a practical
   implementation and explain where it should be applied.

7. Preserve the existing architecture and technologies unless
   the user explicitly asks for a redesign.

8. Do not claim that you inspected repository files that are not
   present in the supplied context.

9. Be technically precise and concise, but provide enough
   explanation for the user to understand the solution.

10. Treat the user's actual question as the task to solve.

11. Use standard Markdown when formatting your response.
    Use fenced code blocks with triple backticks and an optional
    language identifier such as ```python.

12. When the user refers to something discussed earlier in the
    conversation, use the previous conversation messages supplied
    in the conversation history.
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
        self._clients: dict[str, AsyncOpenAI] = {}

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

        response = await self._generate_response(
            self._build_messages(context_result, history, mode),
            model or self.model,
        )
        for offset in range(0, len(response), 128):
            yield response[offset : offset + 128]

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
                content = response.choices[0].message.content
                if not content or not content.strip():
                    raise ValueError("Provider returned an empty response.")
                return content.strip()
            except Exception as exc:
                reason = self._failure_reason(exc)
                failures.append(f"{provider.label}: {reason}")
                logger.warning(
                    "LLM provider %s failed (%s); trying the next configured provider.",
                    provider.id,
                    reason,
                )

        raise LLMGenerationError(
            "All configured LLM providers failed. " + "; ".join(failures)
        )

    def _client_for(self, provider: ModelProvider) -> AsyncOpenAI:
        client = self._clients.get(provider.id)
        if client is not None:
            return client

        credentials = provider.credentials()
        if credentials is None:
            raise ValueError(f"{provider.label} is not configured.")
        api_key, base_url = credentials
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=0,
            timeout=45.0,
        )
        self._clients[provider.id] = client
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
        if isinstance(exc, APIStatusError):
            return f"API returned HTTP {exc.status_code}"
        if isinstance(exc, APIConnectionError):
            return "connection failed"
        if isinstance(exc, ValueError):
            return str(exc)
        return type(exc).__name__

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
