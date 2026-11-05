from __future__ import annotations

import os
from collections.abc import AsyncIterator

from dotenv import load_dotenv
from groq import AsyncGroq
from groq import APIConnectionError
from groq import APIStatusError
from groq import RateLimitError

from context.builder import ContextResult

from generation.modes import (
    GenerationMode,
    get_mode_instruction,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "qwen/qwen3.8-27b"
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_MAX_OUTPUT_TOKENS = 4096
DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 0.95


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LLMGenerationError(RuntimeError):
    """Raised when the LLM generation stage fails."""


# ---------------------------------------------------------------------------
# LLM generator
# ---------------------------------------------------------------------------


class LLMGenerator:
    """
    Generate answers from repository-aware context using Groq.

    The same AsyncGroq client is reused for the lifetime of this object.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        reasoning_effort: str = DEFAULT_REASONING_EFFORT,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        top_p: float = DEFAULT_TOP_P,
    ) -> None:
        load_dotenv()

        api_key = os.getenv("GROQ_API_KEY")

        if not api_key:
            raise ValueError(
                "GROQ_API_KEY environment variable is not set. "
                "Add it to your .env file."
            )

        if not model.strip():
            raise ValueError("model cannot be empty.")

        if max_output_tokens <= 0:
            raise ValueError(
                "max_output_tokens must be greater than zero."
            )

        if temperature < 0.0:
            raise ValueError(
                "temperature must be greater than or equal to zero."
            )

        if not 0.0 < top_p <= 1.0:
            raise ValueError(
                "top_p must be greater than zero and less than or equal to one."
            )

        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.top_p = top_p

        self.client = AsyncGroq(
            api_key=api_key,
        )

    # -----------------------------------------------------------------------
    # Normal generation
    # -----------------------------------------------------------------------

    async def generate(
        self,
        context_result: ContextResult,
        history: list[dict[str, str]] | None = None,
        mode: GenerationMode = GenerationMode.EXPLAIN,
    ) -> str:
        """
        Generate a complete response.

        `history` contains previous user/assistant messages from the
        current application session.
        """

        if not context_result.query.strip():
            raise ValueError(
                "ContextResult query cannot be empty."
            )

        messages = self._build_messages(
            context_result,
            history,
            mode,
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                reasoning_effort=self.reasoning_effort,
                reasoning_format="hidden",
                temperature=self.temperature,
                top_p=self.top_p,
                max_completion_tokens=self.max_output_tokens,
                stream=False,
            )

        except RateLimitError as exc:
            raise LLMGenerationError(
                "Groq API rate limit reached. "
                "Please wait and try again."
            ) from exc

        except APIConnectionError as exc:
            raise LLMGenerationError(
                "Could not connect to the Groq API. "
                "Check your internet connection and try again."
            ) from exc

        except APIStatusError as exc:
            raise LLMGenerationError(
                f"Groq API returned an error "
                f"(status {exc.status_code})."
            ) from exc

        except Exception as exc:
            raise LLMGenerationError(
                f"Unexpected LLM generation error: {exc}"
            ) from exc

        content = response.choices[0].message.content

        if not content:
            raise LLMGenerationError(
                "The Groq API returned an empty response."
            )

        return content.strip()

    # -----------------------------------------------------------------------
    # Streaming generation
    # -----------------------------------------------------------------------

    async def stream_generate(
        self,
        context_result: ContextResult,
        history: list[dict[str, str]] | None = None,
        mode: GenerationMode = GenerationMode.EXPLAIN,
    ) -> AsyncIterator[str]:
        """
        Stream generated response chunks from Groq.
        """

        if not context_result.query.strip():
            raise ValueError(
                "ContextResult query cannot be empty."
            )

        messages = self._build_messages(
            context_result,
            history,
            mode,
        )

        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                reasoning_effort=self.reasoning_effort,
                reasoning_format="hidden",
                temperature=self.temperature,
                top_p=self.top_p,
                max_completion_tokens=self.max_output_tokens,
                stream=True,
            )

            async for chunk in stream:
                if not chunk.choices:
                    continue

                content = chunk.choices[0].delta.content

                if content:
                    yield content

        except RateLimitError as exc:
            raise LLMGenerationError(
                "Groq API rate limit reached. "
                "Please wait and try again."
            ) from exc

        except APIConnectionError as exc:
            raise LLMGenerationError(
                "Could not connect to the Groq API. "
                "Check your internet connection and try again."
            ) from exc

        except APIStatusError as exc:
            raise LLMGenerationError(
                f"Groq API returned an error "
                f"(status {exc.status_code})."
            ) from exc

        except Exception as exc:
            raise LLMGenerationError(
                f"Unexpected streaming error: {exc}"
            ) from exc

    # -----------------------------------------------------------------------
    # Message construction
    # -----------------------------------------------------------------------

    @staticmethod
    def _build_messages(
        context_result: ContextResult,
        history: list[dict[str, str]] | None = None,
        mode: GenerationMode = GenerationMode.EXPLAIN,
    ) -> list[dict[str, str]]:
        """
        Build the message sequence sent to the LLM.
        """

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
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            }
        ]

        if history:
            messages.extend(history)

        messages.append(
            {
                "role": "user",
                "content": user_message,
            }
        )

        return messages
    # -----------------------------------------------------------------------
    # Resource cleanup
    # -----------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying Groq HTTP client."""

        await self.client.close()

    async def __aenter__(self) -> "LLMGenerator":
        return self

    async def __aexit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        await self.close()