"""Hermes 与 inspection_platform 向量化 / 对话调用桥接。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from agent_base.llm.errors import LLMError
from agent_base.llm.types import ChatRequest, ChatResponse


def ensure_hermes_path() -> Path | None:
    """将 vendored Hermes 根目录加入 ``sys.path``（与 ``app.main`` 挂载逻辑一致）。"""
    platform_root = Path(__file__).resolve().parent
    vendored_root = platform_root / "hermes_agent"
    configured = os.environ.get("SIA_HERMES_AGENT_ROOT", "").strip()
    candidates: list[Path] = []
    if vendored_root.is_dir():
        candidates.append(vendored_root)
    if configured:
        candidates.append(Path(configured))
    hermes_root = next((p for p in candidates if p.is_dir()), None)
    if hermes_root is not None and str(hermes_root) not in sys.path:
        sys.path.insert(0, str(hermes_root))
    return hermes_root


def _platform_embedding_model_name() -> str | None:
    from inspection_platform.envutil import env_first

    v = env_first("inspection_platform_EMBEDDING_MODEL")
    return v or None


def _embedding_model_slug(model_name: str | None) -> str:
    explicit = (model_name or "").strip() or (_platform_embedding_model_name() or "").strip()
    if explicit:
        return explicit
    ensure_hermes_path()
    from agent.auxiliary_client import _read_main_model

    return (_read_main_model() or "").strip()


def hermes_embed_texts(
    texts: list[str],
    *,
    metadata: dict[str, Any] | None = None,
    model_name: str | None = None,
) -> list[list[float]]:
    """经 Hermes ``resolve_provider_client`` 调用 OpenAI 兼容 embeddings API。"""
    if not texts:
        return []
    ensure_hermes_path()
    from agent.auxiliary_client import (
        _read_main_provider,
        resolve_provider_client,
    )

    slug = _embedding_model_slug(model_name)
    provider = (_read_main_provider() or "auto").strip().lower() or "auto"
    client, final_model = resolve_provider_client(provider, model=slug or None)
    if client is None:
        raise ValueError(
            "Hermes 未配置可用的 embedding 提供商；请运行 hermes setup 或配置 ~/.hermes/config.yaml"
        )
    model = (final_model or slug or "").strip()
    if not model:
        raise ValueError("未配置 embedding 模型名（config.yaml model 或 inspection_platform_EMBEDDING_MODEL）")

    _ = metadata
    try:
        resp = client.embeddings.create(model=model, input=texts)
    except Exception as e:
        raise ValueError(f"embedding 调用失败：{e}") from e

    rows = sorted(resp.data, key=lambda item: getattr(item, "index", 0))
    out: list[list[float]] = []
    for item in rows:
        vec = getattr(item, "embedding", None)
        if vec is None:
            raise ValueError("embedding response contains null vector")
        out.append(list(map(float, vec)))
    if len(out) != len(texts):
        raise ValueError("embedding 返回向量数与输入不一致")
    return out


def _chat_messages_for_hermes(request: ChatRequest) -> list[dict[str, str]]:
    return [{"role": m.role, "content": m.content} for m in request.messages]


def hermes_call_chat(request: ChatRequest, *, model_name: str | None = None) -> ChatResponse:
    """将 ``ChatRequest`` 转为 Hermes ``call_llm`` 并包装为 ``ChatResponse``。"""
    ensure_hermes_path()
    from agent.auxiliary_client import call_llm, _read_main_model, _read_main_provider

    provider = (_read_main_provider() or "").strip().lower()
    model = (model_name or _read_main_model() or "").strip() or None

    kwargs: dict[str, Any] = {"messages": _chat_messages_for_hermes(request)}
    if provider and provider not in {"auto", "main", ""}:
        kwargs["provider"] = provider
    if model:
        kwargs["model"] = model
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.max_output_tokens is not None:
        kwargs["max_tokens"] = request.max_output_tokens

    try:
        response = call_llm(**kwargs)
    except RuntimeError as e:
        raise LLMError(code="MODEL_UNAVAILABLE", message=str(e), retryable=False) from e
    except Exception as e:
        raise LLMError(code="UNKNOWN", message=str(e), retryable=False) from e

    content = ""
    if hasattr(response, "choices") and response.choices:
        msg = response.choices[0].message
        piece = getattr(msg, "content", None)
        content = piece if isinstance(piece, str) else (str(piece) if piece is not None else "")
    elif isinstance(response, str):
        content = response

    return ChatResponse(content=content, raw=response)