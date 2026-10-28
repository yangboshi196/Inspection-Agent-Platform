"""
SSE 错误格式化工具。

统一所有 SSE 错误响应格式，确保前端解析一致性。
"""
from __future__ import annotations

import json
from typing import Any

from .exceptions import AgentError


# ---- 统一 SSE 错误格式 ----

SSE_ERROR_FIELDS = frozenset(["type", "code", "message", "retryable", "details", "request_id"])


def format_error_sse(error: AgentError | Exception) -> str:
    """
    将异常格式化为 SSE data 行。

    统一格式：{"type":"error","code":"...","message":"...","retryable":bool,...}

    - AgentError：使用 to_sse_payload()
    - 其他 Exception：code="INTERNAL_ERROR"，message=str(e)
    """
    if isinstance(error, AgentError):
        payload = error.to_sse_payload()
    else:
        payload = {
            "type": "error",
            "code": "INTERNAL_ERROR",
            "message": str(error),
            "retryable": False,
        }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def format_error_dict(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    从参数构建 SSE 错误字典。

    用途：在不想抛异常的场景下直接构建错误 payload。
    """
    payload: dict[str, Any] = {
        "type": "error",
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if request_id:
        payload["request_id"] = request_id
    if details:
        payload["details"] = details
    return payload


def parse_error_sse(data: str) -> dict[str, Any] | None:
    """
    解析 SSE data 行中的错误 payload。

    若解析失败或不是 error 类型，返回 None。
    """
    text = data.strip()
    if text.startswith("data:"):
        text = text[5:].strip()
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict) or obj.get("type") != "error":
        return None
    return obj


def is_error_payload(obj: dict[str, Any]) -> bool:
    """判断是否为错误类型 payload。"""
    return obj.get("type") == "error"


def error_message_of(obj: dict[str, Any]) -> str:
    """从 SSE payload 中提取错误消息（兜底）。"""
    return obj.get("message") or obj.get("error") or "unknown error"
