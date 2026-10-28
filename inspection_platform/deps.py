"""进程内单例：装配 Agent 运行时（ModelManager、ToolRegistry、ReActAgent）。"""

from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import agent_base

from agent_base.agent.react_agent import ReActAgent
from agent_base.context.manager import ContextManager
from agent_base.model_manager.manager import ModelManager
from agent_base.model_manager.secrets import SecretResolver
from agent_base.prompts import load_prompt
from agent_base.tools.registry import ToolRegistry

_stack: dict[str, Any] | None = None

_DEMO_REACT_MAX_STEPS: int | None = None

_MAIN_STREAM_AGENT: dict[str, Any] = {
    "id": "react_main",
    "label": "主智能体",
    "role": "对话助手",
}


def _models_json_path() -> Path:
    return Path(agent_base.__file__).resolve().parent / "model_manager" / "models.json"


def get_stack() -> dict[str, Any]:
    global _stack
    if _stack is None:
        from inspection_platform.env_bootstrap import apply_project_dotenv, bootstrap_platform_env, sync_platform_siliconflow_credentials

        apply_project_dotenv(override=True)
        bootstrap_platform_env()
        _ensure_platform_embedding_env()
        sync_platform_siliconflow_credentials()
        mm = ModelManager.from_file(
            _models_json_path(),
            secret_resolver=SecretResolver(),
        )
        reg = ToolRegistry()
        ctx = ContextManager()
        _stack = {
            "model_manager": mm,
            "tool_registry": reg,
            "context_manager": ctx,
        }
        try:
            from inspection_platform.inspection_work.tool import BuildInspectionWorksTool

            reg.register(BuildInspectionWorksTool())
        except ValueError:
            pass
    return _stack


def get_model_manager() -> ModelManager:
    return get_stack()["model_manager"]


def warmup_embedding_model() -> None:
    """启动时预热 embedding（vLLM 或 SentenceTransformer），避免首次入库长时间无响应。"""
    import logging

    from inspection_platform.embedding.backend import (
        embedding_dimension,
        embedding_device_label,
        resolve_embedding_backend,
        warmup,
    )

    logger = logging.getLogger(__name__)
    try:
        warmup()
        dim = embedding_dimension()
        logger.info(
            "embedding 预热完成 backend=%s device=%s dim=%s",
            resolve_embedding_backend(),
            embedding_device_label(),
            dim,
        )
    except Exception as exc:
        logger.warning("embedding 预热失败（首次入库会较慢）: %s", exc)


_PLATFORM_DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"


def _ensure_platform_embedding_env() -> None:
    """保证平台 RAG（知识库 + 规范）走硅基流动 Embedding。"""
    from inspection_platform.llm.openai_client import (
        DEFAULT_SILICONFLOW_EMBED_BASE_URL,
        DEFAULT_SILICONFLOW_EMBED_MODEL,
    )

    if not os.environ.get("SIA_EMBEDDING_BACKEND", "").strip():
        os.environ["SIA_EMBEDDING_BACKEND"] = "openai"
    if not os.environ.get("SILICONFLOW_EMBED_BASE_URL", "").strip():
        os.environ["SILICONFLOW_EMBED_BASE_URL"] = DEFAULT_SILICONFLOW_EMBED_BASE_URL
    if not os.environ.get("SILICONFLOW_EMBED_MODEL", "").strip():
        os.environ["SILICONFLOW_EMBED_MODEL"] = DEFAULT_SILICONFLOW_EMBED_MODEL
    if not os.environ.get("inspection_platform_EMBEDDING_MODEL", "").strip():
        os.environ["inspection_platform_EMBEDDING_MODEL"] = DEFAULT_SILICONFLOW_EMBED_MODEL


def platform_embedding_model_name() -> str:
    """平台知识库 / 规范管理 / 检索共用的 embedding 模型名。"""
    from inspection_platform.envutil import env_first

    return (
        env_first(
            "SIA_EMBEDDING_MODEL",
            "SILICONFLOW_EMBED_MODEL",
            "inspection_platform_EMBEDDING_MODEL",
        )
        or _PLATFORM_DEFAULT_EMBEDDING_MODEL
    )


def platform_embed_texts(
    texts: list[str],
    *,
    model_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[list[float]]:
    """平台 RAG 向量化：默认硅基流动 AsyncOpenAI。"""
    from inspection_platform.embedding.backend import embed_texts
    from inspection_platform.env_bootstrap import sync_platform_siliconflow_credentials

    sync_platform_siliconflow_credentials()
    resolved = (model_name or "").strip() or platform_embedding_model_name()
    return embed_texts(texts, metadata=metadata, model_name=resolved)


async def platform_embed_texts_async(
    texts: list[str],
    *,
    model_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[list[float]]:
    from inspection_platform.embedding.backend import embed_texts_async

    resolved = (model_name or "").strip() or platform_embedding_model_name()
    return await embed_texts_async(texts, metadata=metadata, model_name=resolved)


def platform_chat_model_name() -> str:
    """平台 LLM 默认模型（SiliconFlow OpenAI 兼容）。"""
    from inspection_platform.envutil import env_first

    return env_first("SIA_CHAT_MODEL") or "deepseek-ai/DeepSeek-V4-Flash"


def platform_call_chat(request, *, model_name: str | None = None):
    """平台侧 LLM 对话：优先 OpenAI 兼容云端 API，否则 ModelManager。"""
    from inspection_platform.llm.openai_client import is_openai_api_configured

    resolved = model_name or platform_chat_model_name()
    if is_openai_api_configured():
        from inspection_platform.llm.chat import call_chat

        return call_chat(request, model_name=resolved)
    mm = get_model_manager()
    return mm.call_chat(request, model_name=resolved)


async def platform_call_chat_async(request, *, model_name: str | None = None):
    """平台侧 LLM 异步对话：优先 OpenAI 兼容云端 API。"""
    from inspection_platform.llm.openai_client import is_openai_api_configured

    resolved = model_name or platform_chat_model_name()
    if is_openai_api_configured():
        from inspection_platform.llm.chat import call_chat_async

        return await call_chat_async(request, model_name=resolved)
    mm = get_model_manager()
    return await asyncio.to_thread(mm.call_chat, request, model_name=resolved)


@lru_cache
def get_specification_service():
    """规范管理 / 巡检规范向量检索共用的 SpecificationService（与知识库同源 embed_texts）。"""
    from inspection_platform.specification.service import SpecificationService

    return SpecificationService(
        get_model_manager(),
        embedding_model_name=platform_embedding_model_name(),
    )


@lru_cache
def get_knowledge_ingest_service():
    """知识库向量化入库服务（与规范管理共用 embedding 模型配置）。"""
    from inspection_platform.knowledge.ingest_service import KnowledgeIngestService

    return KnowledgeIngestService(
        get_model_manager(),
        embedding_model_name=platform_embedding_model_name(),
    )


def get_agent() -> ReActAgent:
    s = get_stack()
    cached = s.get("_agent")
    stale_max = not isinstance(cached, ReActAgent) or (
        getattr(cached, "_max_steps", object()) != _DEMO_REACT_MAX_STEPS
    )
    if stale_max or "_agent" not in s:
        s["_agent"] = ReActAgent(
            model_manager=s["model_manager"],
            tool_registry=s["tool_registry"],
            context_manager=s["context_manager"],
            system_prompt=load_prompt("agent/react_agent_default.txt"),
            max_steps=_DEMO_REACT_MAX_STEPS,
            window_last_n=40,
            tool_stream_card=None,
            tool_start_card=None,
            stream_reasoning_agent=dict(_MAIN_STREAM_AGENT),
        )
    return s["_agent"]
