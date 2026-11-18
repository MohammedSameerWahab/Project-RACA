from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.context.builder import ContextResult
from src.generation import llm as llm_module
from src.generation.llm import LLMGenerationError, LLMGenerator
from src.generation.providers import (
    DEFAULT_MODEL,
    PROVIDERS,
    PROVIDERS_BY_ID,
    model_options,
)

EXPECTED_MODELS = [
    "qwen2.5-coder:3b",
    "gemini-3.8-flash",
    "qwen/qwen3.8-27b",
    "gemma-4-31b-it",
    "openai/gpt-oss-120b",
    "@cf/qwen/qwen2.5-coder-32b-instruct",
    "gemini-4-argon",
    "qwen/qwen3-32b",
    "gemma-4-26b-a4b-it",
    "@cf/qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
    "llama-3.3-70b-versatile",
    "@cf/qwen/qwen3-30b-a3b-fp8",
    "deepseek-ai/deepseek-v4.1-flash",
    "nvidia/nemotron-3.5-super-vl-120b-a12b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
]


def test_model_catalog_matches_requested_fallback_ladder() -> None:
    assert [provider.model for provider in PROVIDERS] == EXPECTED_MODELS
    assert [option["id"] for option in model_options()] == [
        provider.id for provider in PROVIDERS
    ]
    assert DEFAULT_MODEL == PROVIDERS[0].id


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
    cloudflare = PROVIDERS_BY_ID["cloudflare-qwen2.5-coder-32b"]
    monkeypatch.setenv("CLOUDFLARE_API_KEY", "cloudflare-test-token")
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)

    assert cloudflare.credentials() is None

    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account-123")
    assert cloudflare.credentials() == (
        "cloudflare-test-token",
        "https://api.cloudflare.com/client/v4/accounts/account-123/ai/v1",
    )


def test_nvidia_accepts_legacy_api_key_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nvidia = PROVIDERS_BY_ID["nvidia-deepseek-v4.1-flash"]
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("NVIDEA_API_KEY", "nvidia-test-key")

    assert nvidia.credentials() == (
        "nvidia-test-key",
        "https://integrate.api.nvidia.com/v1",
    )


def test_local_provider_uses_longer_read_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "ollama")
    monkeypatch.setattr(
        llm_module,
        "AsyncOpenAI",
        lambda api_key, **kwargs: captured.update(kwargs) or object(),
    )

    generator = LLMGenerator()
    generator._client_for(PROVIDERS_BY_ID["local-qwen2.5-coder-3b"])

    timeout = captured["timeout"]
    assert isinstance(timeout, llm_module.httpx.Timeout)
    assert timeout.read == 180.0
    assert timeout.connect == 10.0


def test_selected_model_is_tried_before_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=llm_module.__name__)
    monkeypatch.setenv("GOOGLE_API_KEY", "google-test-key")
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    for provider in PROVIDERS:
        if provider.api_key_env not in {"GOOGLE_API_KEY", "GROQ_API_KEY"}:
            monkeypatch.delenv(provider.api_key_env, raising=False)
        if provider.alternate_api_key_env:
            monkeypatch.delenv(provider.alternate_api_key_env, raising=False)
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
    answer = asyncio.run(generator.generate(_context(), model="groq-qwen3-32b"))

    assert answer == "Gemini answer"
    assert clients["groq-test-key"].chat.completions.create.await_count == 1
    assert clients["google-test-key"].chat.completions.create.await_count == 1
    assert "RuntimeError: busy" in caplog.text
    assert "Generated response with model gemma-4-26b-a4b-it" in caplog.text


def test_generation_falls_back_in_order_and_reports_total_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-test-key")
    for provider in PROVIDERS:
        if provider.api_key_env not in {"GOOGLE_API_KEY", "GROQ_API_KEY"}:
            monkeypatch.delenv(provider.api_key_env, raising=False)
        if provider.alternate_api_key_env:
            monkeypatch.delenv(provider.alternate_api_key_env, raising=False)
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
        asyncio.run(generator.generate(_context(), model="groq-qwen3-32b"))

    assert attempted == [
        provider.model
        for provider in generator._fallback_order("groq-qwen3-32b")
    ]
