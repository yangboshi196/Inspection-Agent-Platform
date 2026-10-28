"""
ModelManager 模块 - 模型配置类型定义。

定义各类型模型的配置结构（ChatModelConfig / EmbeddingConfig / VisualConfig / VoiceConfig），
以及完整的模型配置集合 ModelConfigSet。
"""


from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal


SourceType = Literal["local", "api"]


@dataclass(frozen=True)
class ModelSource:
    type: SourceType
    url: str
    key_ref: str | None = None


@dataclass(frozen=True)
class ModelSpec:
    name: str
    source: ModelSource
    tags: list[str]
    provider: str
    impl: str  # openai_compat | http_api（可扩展）
    timeout_ms: int = 60000
    connect_timeout_ms: int = 5000
    max_retries: int = 1
    retry_backoff_ms: int = 200
    concurrency_limit: int = 0


def _require(obj: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in obj or obj[key] in (None, ""):
        raise ValueError(f"{ctx}: missing required field '{key}'")
    return obj[key]


def parse_model_spec(data: dict[str, Any], ctx: str) -> ModelSpec:
    """
    将单条模型 JSON 对象解析为 `ModelSpec`；`ctx` 为错误信息前缀（如 `siliconflow.chat[0]`）。

    强校验必填字段与 `api/local` 下 `key_ref` 规则，不合法时抛出 `ValueError`。
    """
    name = str(_require(data, "name", ctx))
    source = data.get("source")
    if isinstance(source, str):
        # 兼容文档写法：source: local/api
        source_obj = {"type": source, **(data.get(source) or {})}
    elif isinstance(source, dict):
        source_obj = source
    else:
        raise ValueError(f"{ctx}: invalid field 'source'")

    source_type = str(_require(source_obj, "type", ctx))
    if source_type not in ("local", "api"):
        raise ValueError(f"{ctx}: source.type must be 'local'|'api'")
    url = str(_require(source_obj, "url", ctx))
    url_ref = source_obj.get("url_ref")
    if url_ref and str(url_ref).startswith("env:"):
        env_key = str(url_ref).split("env:", 1)[1].strip()
        env_url = os.environ.get(env_key)
        if env_url:
            url = str(env_url).strip().rstrip("/")
    key_ref = source_obj.get("key_ref")
    if source_type == "api":
        if key_ref in (None, ""):
            raise ValueError(f"{ctx}: source.type=api requires non-empty 'key_ref'")
    else:
        # local：允许显式写 null；不允许空字符串（避免误配置）
        if key_ref == "":
            raise ValueError(f"{ctx}: source.type=local must omit 'key_ref' or set it to null, not empty string")
        if key_ref is not None:
            key_ref = str(key_ref)

    _require(data, "provider", ctx)
    provider = str(data.get("provider"))

    _require(data, "impl", ctx)
    impl = str(data.get("impl"))

    timeout_ms = int(_require(data, "timeout_ms", ctx))
    connect_timeout_ms = int(_require(data, "connect_timeout_ms", ctx))
    max_retries = int(_require(data, "max_retries", ctx))
    retry_backoff_ms = int(_require(data, "retry_backoff_ms", ctx))
    concurrency_limit = int(_require(data, "concurrency_limit", ctx))
    if concurrency_limit < 0:
        raise ValueError(f"{ctx}: concurrency_limit must be >= 0")

    _require(data, "tags", ctx)
    tags = list(data.get("tags") or [])
    if not tags:
        raise ValueError(f"{ctx}: tags must be a non-empty array")

    return ModelSpec(
        name=name,
        source=ModelSource(type=source_type, url=url, key_ref=key_ref),
        timeout_ms=timeout_ms,
        connect_timeout_ms=connect_timeout_ms,
        max_retries=max_retries,
        retry_backoff_ms=retry_backoff_ms,
        concurrency_limit=concurrency_limit,
        tags=tags,
        provider=provider,
        impl=impl,
    )

