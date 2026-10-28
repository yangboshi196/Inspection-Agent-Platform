"""OpenAI 兼容 Chat Completions（AsyncOpenAI）。"""

from __future__ import annotations

import time
from typing import Any

from agent_base.llm.errors import LLMError, redact_secrets
from agent_base.llm.impl.openai_compat import _to_openai_messages
from agent_base.llm.types import ChatRequest, ChatResponse

from .async_runtime import run_async
from .openai_client import get_async_openai_client, openai_chat_model


def _chat_response_from_openai(data: Any, *, model: str, latency_ms: int) -> ChatResponse:
    content = ""
    if getattr(data, "choices", None):
        msg = data.choices[0].message
        piece = getattr(msg, "content", None)
        content = piece if isinstance(piece, str) else (str(piece) if piece is not None else "")
    raw = data.model_dump() if hasattr(data, "model_dump") else data
    return ChatResponse(
        content=content,
        raw=raw,
        usage={"provider": "openai_compat", "model": model, "latency_ms": latency_ms},
    )


async def call_chat_async(
    request: ChatRequest,
    *,
    model_name: str | None = None,
) -> ChatResponse:
    request_id = str((request.metadata or {}).get("request_id") or "")
    model = openai_chat_model(model_name)
    client = get_async_openai_client()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": _to_openai_messages(request.messages, provider="siliconflow"),
    }
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.top_p is not None:
        kwargs["top_p"] = request.top_p
    if request.max_output_tokens is not None:
        kwargs["max_tokens"] = request.max_output_tokens
    if request.tools is not None:
        kwargs["tools"] = request.tools
    if request.tool_choice is not None:
        kwargs["tool_choice"] = request.tool_choice

    t0 = time.perf_counter()
    try:
        resp = await client.chat.completions.create(**kwargs)
    except Exception as e:
        msg = redact_secrets(str(e), [])
        code = "AUTH_FAILED" if "401" in msg or "403" in msg else "BAD_REQUEST"
        raise LLMError(
            code=code,
            message=msg,
            retryable="429" in msg or "timeout" in msg.lower(),
            provider="openai_compat",
            request_id=request_id,
            raw={"error": msg},
        ) from e

    latency_ms = int((time.perf_counter() - t0) * 1000)
    return _chat_response_from_openai(resp, model=model, latency_ms=latency_ms)


def call_chat(request: ChatRequest, *, model_name: str | None = None) -> ChatResponse:
    return run_async(call_chat_async(request, model_name=model_name))
