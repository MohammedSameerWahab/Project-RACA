from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class ModelProvider:
    id: str
    label: str
    model: str
    api_key_env: str
    base_url: str
    account_id_env: str | None = None

    def credentials(self) -> tuple[str, str] | None:
        api_key = os.getenv(self.api_key_env, "").strip()
        if not api_key:
            return None

        base_url = self.base_url
        if self.account_id_env:
            account_id = os.getenv(self.account_id_env, "").strip()
            if not account_id:
                return None
            base_url = base_url.format(account_id=account_id)

        return api_key, base_url

    def is_configured(self) -> bool:
        return self.credentials() is not None


PROVIDERS = (
    ModelProvider(
        id="groq-qwen",
        label="Groq · Qwen 3 32B",
        model="qwen/qwen3-32b",
        api_key_env="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
    ),
    ModelProvider(
        id="gemini-flash",
        label="Google · Gemini 3.1 Flash-Lite",
        model="gemini-3.1-flash-lite",
        api_key_env="GOOGLE_API_KEY",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    ),
    ModelProvider(
        id="nvidia-llama",
        label="NVIDIA · Llama 3.3 70B",
        model="meta/llama-3.3-70b-instruct",
        api_key_env="NVIDEA_API_KEY",
        base_url="https://integrate.api.nvidia.com/v1",
    ),
    ModelProvider(
        id="glm-flash",
        label="Z.AI · GLM-4.5-Flash",
        model="glm-4.5-flash",
        api_key_env="GLM_API_KEY",
        base_url="https://api.z.ai/api/paas/v4",
    ),
    ModelProvider(
        id="cloudflare-llama",
        label="Cloudflare · Llama 3.1 8B",
        model="@cf/meta/llama-3.1-8b-instruct",
        api_key_env="CLOUDFLARE_API_KEY",
        base_url=(
            "https://api.cloudflare.com/client/v4/accounts/"
            "{account_id}/ai/v1"
        ),
        account_id_env="CLOUDFLARE_ACCOUNT_ID",
    ),
)

DEFAULT_MODEL = PROVIDERS[0].id
PROVIDERS_BY_ID = {provider.id: provider for provider in PROVIDERS}


def configured_providers() -> tuple[ModelProvider, ...]:
    return tuple(provider for provider in PROVIDERS if provider.is_configured())


def model_options() -> list[dict[str, str | bool]]:
    return [
        {
            "id": provider.id,
            "label": provider.label,
            "configured": provider.is_configured(),
        }
        for provider in PROVIDERS
    ]
