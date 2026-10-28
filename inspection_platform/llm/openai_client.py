"""OpenAI 兼容云端 API 客户端配置（硅基流动）。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from inspection_platform.envutil import env_first

DEFAULT_SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_SILICONFLOW_EMBED_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_SILICONFLOW_EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_SILICONFLOW_CHAT_MODEL = "deepseek-ai/DeepSeek-V4-Flash"


def _project_key(*names: str) -> str:
    from inspection_platform.env_bootstrap import project_env_value

    for name in names:
        val = (project_env_value(name) or "").strip()
        if val:
            return val
    return ""


def is_openai_api_configured() -> bool:
    return bool(
        _project_key("SILICONFLOW_API_KEY", "SIA_OPENAI_API_KEY")
        or env_first("SILICONFLOW_API_KEY", "SIA_OPENAI_API_KEY")
    )


def openai_chat_api_key() -> str:
    """Chat 专用 Key；优先项目 ``.env`` 的 ``SILICONFLOW_API_KEY``。"""
    key = _project_key("SILICONFLOW_API_KEY", "SIA_OPENAI_API_KEY")
    if not key:
        key = env_first("SILICONFLOW_API_KEY", "SIA_OPENAI_API_KEY")
    if not key:
        raise ValueError("未配置 Chat API Key；请在项目 .env 设置 SILICONFLOW_API_KEY（sk- 格式）")
    return key


def openai_api_key() -> str:
    return openai_chat_api_key()


def openai_embed_api_key() -> str:
    """Embedding 专用 Key；优先 ``SILICONFLOW_EMBED_API_KEY``，可与 Chat 共用 ``SILICONFLOW_API_KEY``。"""
    key = _project_key(
        "SILICONFLOW_EMBED_API_KEY",
        "SIA_OPENAI_EMBED_API_KEY",
        "SILICONFLOW_API_KEY",
        "SIA_OPENAI_API_KEY",
    )
    if not key:
        key = env_first(
            "SILICONFLOW_EMBED_API_KEY",
            "SIA_OPENAI_EMBED_API_KEY",
            "SILICONFLOW_API_KEY",
            "SIA_OPENAI_API_KEY",
        )
    if not key:
        raise ValueError(
            "未配置 Embedding API Key；请在项目 .env 设置 SILICONFLOW_EMBED_API_KEY（sk- 格式）"
        )
    return key


def openai_base_url() -> str:
    raw = (
        _project_key("SILICONFLOW_CHAT_BASE_URL", "SIA_OPENAI_BASE_URL")
        or env_first("SILICONFLOW_CHAT_BASE_URL", "SIA_OPENAI_BASE_URL")
        or DEFAULT_SILICONFLOW_BASE_URL
    ).strip().rstrip("/")
    return raw


def openai_embed_base_url() -> str:
    raw = (
        _project_key("SILICONFLOW_EMBED_BASE_URL", "SIA_OPENAI_EMBED_BASE_URL")
        or env_first("SILICONFLOW_EMBED_BASE_URL", "SIA_OPENAI_EMBED_BASE_URL")
        or DEFAULT_SILICONFLOW_EMBED_BASE_URL
    ).strip().rstrip("/")
    if raw.endswith("/api"):
        raw = f"{raw}/v1"
    return raw


def openai_chat_model(explicit: str | None = None) -> str:
    return (
        (explicit or "").strip()
        or _project_key("SIA_CHAT_MODEL", "SIA_INSPECTION_WORK_CHAT_MODEL")
        or env_first("SIA_CHAT_MODEL", "SIA_INSPECTION_WORK_CHAT_MODEL")
        or DEFAULT_SILICONFLOW_CHAT_MODEL
    )


def openai_embed_model(explicit: str | None = None) -> str:
    return (
        (explicit or "").strip()
        or _project_key(
            "SILICONFLOW_EMBED_MODEL",
            "inspection_platform_EMBEDDING_MODEL",
            "SIA_EMBEDDING_MODEL",
        )
        or env_first(
            "SILICONFLOW_EMBED_MODEL",
            "inspection_platform_EMBEDDING_MODEL",
            "SIA_EMBEDDING_MODEL",
        )
        or DEFAULT_SILICONFLOW_EMBED_MODEL
    ).strip()


def invalidate_openai_clients() -> None:
    """环境变量补全或热重载后清空 OpenAI 客户端缓存。"""
    global _embed_client_cache
    get_async_openai_client.cache_clear()
    _embed_client_cache = None


def openai_timeout_sec(*names: str, default: float = 180.0) -> float:
    keys = list(names) + [
        "SIA_OPENAI_TIMEOUT_SEC",
        "SILICONFLOW_CHAT_TIMEOUT_SEC",
        "SILICONFLOW_EMBED_TIMEOUT_SEC",
    ]
    for name in keys:
        raw = env_first(name)
        if raw:
            return max(5.0, float(raw))
    return default


@lru_cache(maxsize=1)
def get_async_openai_client() -> Any:
    from openai import AsyncOpenAI

    from inspection_platform.env_bootstrap import sync_platform_siliconflow_credentials

    sync_platform_siliconflow_credentials()
    return AsyncOpenAI(
        api_key=openai_chat_api_key(),
        base_url=openai_base_url(),
        timeout=openai_timeout_sec(default=180.0),
        max_retries=2,
    )


_embed_client_cache: tuple[str, str, Any] | None = None


def get_async_openai_embed_client() -> Any:
    """按项目 ``.env`` 凭证创建 Embedding 客户端（与 Chat 解耦）。"""
    global _embed_client_cache
    from openai import AsyncOpenAI

    from inspection_platform.env_bootstrap import sync_platform_siliconflow_credentials

    sync_platform_siliconflow_credentials()
    key = openai_embed_api_key()
    base = openai_embed_base_url()
    if _embed_client_cache is not None:
        cached_key, cached_base, client = _embed_client_cache
        if cached_key == key and cached_base == base:
            return client

    client = AsyncOpenAI(
        api_key=key,
        base_url=base,
        timeout=openai_timeout_sec(
            "SILICONFLOW_EMBED_TIMEOUT_SEC",
            default=120.0,
        ),
        max_retries=0,
    )
    _embed_client_cache = (key, base, client)
    return client
