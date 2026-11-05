from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.context.builder import ContextResult
from src.generation import llm as llm_module
from src.generation.llm import LLMGenerationError, LLMGenerator
from src.generation.providers import PROVIDERS, PROVIDERS_BY_ID


def _context() -> ContextResult:
    return ContextResult(
        query="Explain the implementation",
        context="A verified source excerpt.",
        chunks=[],
        estimated_tokens=10,
    )


def test_cloudflare_requires_account_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cloudflare = PROVIDERS_BY_ID["cloudflare-llama"]
    monkeypatch.setenv("CLOUDFLARE_API_KEY", "cloudflare-test-token")
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)

    assert cloudflare.credentials() is None

    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account-123")
    assert cloudflare.credentials() == (
        "cloudflare-test-token",
        "https://api.cloudflare.com/client/v4/accounts/account-123/ai/v1",
    )


def test_selected_model_is_tried_before_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "google-test-key")
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    for provider in PROVIDERS:
        if provider.api_key_env not in {"GOOGLE_API_KEY", "GROQ_API_KEY"}:
            monkeypatch.delenv(provider.api_key_env, raising=False)
        if provider.account_id_env:
            monkeypatch.delenv(provider.account_id_env, raising=False)

    clients = {
        "google-test-key": SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(
                        return_value=SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    message=SimpleNamespace(content="Gemini answer")
                                )
                            ]
                        )
                    )
                )
            )
        ),
        "groq-test-key": SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(side_effect=RuntimeError("busy"))
                )
            )
        ),
    }
    monkeypatch.setattr(
        llm_module,
        "AsyncOpenAI",
        lambda api_key, **kwargs: clients[api_key],
    )

    generator = LLMGenerator()
    answer = asyncio.run(generator.generate(_context(), model="groq-qwen"))

    assert answer == "Gemini answer"
    assert clients["groq-test-key"].chat.completions.create.await_count == 1
    assert clients["google-test-key"].chat.completions.create.await_count == 1


def test_generation_falls_back_in_order_and_reports_total_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-test-key")
    for provider in PROVIDERS:
        if provider.api_key_env not in {"GOOGLE_API_KEY", "GROQ_API_KEY"}:
            monkeypatch.delenv(provider.api_key_env, raising=False)
        if provider.account_id_env:
            monkeypatch.delenv(provider.account_id_env, raising=False)

    attempted: list[str] = []

    def create_client(api_key: str, **kwargs: object) -> SimpleNamespace:
        def fail(**request: object) -> None:
            attempted.append(str(request["model"]))
            raise RuntimeError("provider unavailable")

        return SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(side_effect=fail))
            )
        )

    monkeypatch.setattr(llm_module, "AsyncOpenAI", create_client)
    generator = LLMGenerator()

    with pytest.raises(LLMGenerationError, match="All configured LLM providers failed"):
        asyncio.run(generator.generate(_context(), model="groq-qwen"))

    assert attempted == ["qwen/qwen3-32b", "gemini-3.1-flash-lite"]
