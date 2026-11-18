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
    alternate_api_key_env: str | None = None

    def credentials(self) -> tuple[str, str] | None:
        api_key = os.getenv(self.api_key_env, "").strip()
        if not api_key and self.alternate_api_key_env:
            api_key = os.getenv(self.alternate_api_key_env, "").strip()
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


GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
CLOUDFLARE_BASE_URL = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
)
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
LOCAL_BASE_URL = os.getenv(
    "LOCAL_LLM_BASE_URL", "http://localhost:11434/v1"
).strip()

PROVIDERS = (
    ModelProvider(
        id="local-qwen2.5-coder-3b",
        label="Qwen 2.5 Coder 3B Local",
        model=os.getenv("LOCAL_LLM_MODEL", "qwen2.5-coder:3b").strip(),
        api_key_env="LOCAL_LLM_API_KEY",
        base_url=LOCAL_BASE_URL,
    ),
    ModelProvider(
        id="gemini-4-hydrogen",
        label="Google · Gemini 4 Hydrogen",
        model="gemini-4-hydrogen",
        api_key_env="GOOGLE_API_KEY",
        base_url=GOOGLE_BASE_URL,
    ),
    ModelProvider(
        id="groq-qwen3.8-27b",
        label="Groq · Qwen 3.8 27B",
        model="qwen/qwen3.8-27b",
        api_key_env="GROQ_API_KEY",
        base_url=GROQ_BASE_URL,
    ),
    ModelProvider(
        id="gemma-4-31b-it",
        label="Google · Gemma 4 31B IT",
        model="gemma-4-31b-it",
        api_key_env="GOOGLE_API_KEY",
        base_url=GOOGLE_BASE_URL,
    ),
    ModelProvider(
        id="groq-gpt-oss-120b",
        label="Groq · GPT-OSS 120B",
        model="openai/gpt-oss-120b",
        api_key_env="GROQ_API_KEY",
        base_url=GROQ_BASE_URL,
    ),
    ModelProvider(
        id="cloudflare-qwen2.5-coder-32b",
        label="Cloudflare · Qwen 2.5 Coder 32B Instruct",
        model="@cf/qwen/qwen2.5-coder-32b-instruct",
        api_key_env="CLOUDFLARE_API_KEY",
        base_url=CLOUDFLARE_BASE_URL,
        account_id_env="CLOUDFLARE_ACCOUNT_ID",
    ),
    ModelProvider(
        id="gemini-4-argon",
        label="Google · Gemini 4 Argon",
        model="gemini-4-argon",
        api_key_env="GOOGLE_API_KEY",
        base_url=GOOGLE_BASE_URL,
    ),
    ModelProvider(
        id="groq-qwen3-32b",
        label="Groq · Qwen 3 32B",
        model="qwen/qwen3-32b",
        api_key_env="GROQ_API_KEY",
        base_url=GROQ_BASE_URL,
    ),
    ModelProvider(
        id="gemma-4-26b-a4b-it",
        label="Google · Gemma 4 26B A4B IT",
        model="gemma-4-26b-a4b-it",
        api_key_env="GOOGLE_API_KEY",
        base_url=GOOGLE_BASE_URL,
    ),
    ModelProvider(
        id="cloudflare-qwen3.8-27b",
        label="Cloudflare · Qwen 3.8 27B",
        model="@cf/qwen/qwen3.8-27b",
        api_key_env="CLOUDFLARE_API_KEY",
        base_url=CLOUDFLARE_BASE_URL,
        account_id_env="CLOUDFLARE_ACCOUNT_ID",
    ),
    ModelProvider(
        id="groq-gpt-oss-20b",
        label="Groq · GPT-OSS 20B",
        model="openai/gpt-oss-20b",
        api_key_env="GROQ_API_KEY",
        base_url=GROQ_BASE_URL,
    ),
    ModelProvider(
        id="cloudflare-deepseek-r1-distill-qwen-32b",
        label="Cloudflare · DeepSeek R1 Distill Qwen 32B",
        model="@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
        api_key_env="CLOUDFLARE_API_KEY",
        base_url=CLOUDFLARE_BASE_URL,
        account_id_env="CLOUDFLARE_ACCOUNT_ID",
    ),
    ModelProvider(
        id="groq-llama-3.3-70b-versatile",
        label="Groq · Llama 3.3 70B Versatile",
        model="llama-3.3-70b-versatile",
        api_key_env="GROQ_API_KEY",
        base_url=GROQ_BASE_URL,
    ),
    ModelProvider(
        id="cloudflare-qwen3-30b-a3b-fp8",
        label="Cloudflare · Qwen 3 30B A3B FP8",
        model="@cf/qwen/qwen3-30b-a3b-fp8",
        api_key_env="CLOUDFLARE_API_KEY",
        base_url=CLOUDFLARE_BASE_URL,
        account_id_env="CLOUDFLARE_ACCOUNT_ID",
    ),
    ModelProvider(
        id="nvidia-deepseek-v4.1-flash",
        label="NVIDIA NIM · DeepSeek V4.1 Flash",
        model="deepseek-ai/deepseek-v4.1-flash",
        api_key_env="NVIDIA_API_KEY",
        alternate_api_key_env="NVIDEA_API_KEY",
        base_url=NVIDIA_BASE_URL,
    ),
    ModelProvider(
        id="nvidia-nemotron-3.5-super-vl-120b-a12b",
        label="NVIDIA NIM · Nemotron 3.5 Super VL 120B A12B",
        model="nvidia/nemotron-3.5-super-vl-120b-a12b",
        api_key_env="NVIDIA_API_KEY",
        alternate_api_key_env="NVIDEA_API_KEY",
        base_url=NVIDIA_BASE_URL,
    ),
    ModelProvider(
        id="nvidia-nemotron-3.5-lightning-30b-a3b",
        label="NVIDIA NIM · Nemotron 3.5 Lightning 30B A3B",
        model="nvidia/nemotron-3.5-lightning-30b-a3b",
        api_key_env="NVIDIA_API_KEY",
        alternate_api_key_env="NVIDEA_API_KEY",
        base_url=NVIDIA_BASE_URL,
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
