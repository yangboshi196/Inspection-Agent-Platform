"""
统一异常类型。

- AgentError：主异常类，所有层统一使用
- LLMError / ToolError：继承自 AgentError，兼容旧代码
- from_codes() 工厂函数：从 ErrorCode 创建异常
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Literal

from .codes import ErrorCode, get_error_meta, is_retryable


@dataclass(frozen=True)
class AgentError(Exception):
    """
    统一异常类型。

    设计原则：
    - frozen=True：可哈希，可安全用于缓存 key、跨线程传递
    - 字段与 SSE 错误格式一致：code / message / retryable / details
    - 兼容旧代码：LLMError / ToolError 继承自此类
    """

    code: ErrorCode
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None

    # ---- 兼容旧 LLMError 字段 ----
    provider: str | None = None
    request_id: str | None = None

    def __str__(self) -> str:
        suffix = ""
        if self.provider:
            suffix += f" provider={self.provider}"
        if self.request_id:
            suffix += f" request_id={self.request_id}"
        return f"AgentError({self.code}){suffix}: {self.message}"

    def to_sse_payload(self) -> dict[str, Any]:
        """生成 SSE 错误 payload。"""
        payload = {
            "type": "error",
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.provider:
            payload["provider"] = self.provider
        if self.request_id:
            payload["request_id"] = self.request_id
        if self.details:
            payload["details"] = self.details
        return payload

    def to_dict(self) -> dict[str, Any]:
        """转为普通字典（用于序列化）。"""
        d = asdict(self)
        # 保持与旧 ToolError 字段兼容
        d["ok"] = False
        return d


# ---- 兼容别名 ----
LLMError = AgentError  # 旧代码兼容


def ToolError(
    code: str | ErrorCode,
    message: str,
    request_id: str | None = None,
    tool_name: str = "",
    retryable: bool = False,
    raw: Any | None = None,
) -> AgentError:
    """
    工厂函数：创建兼容旧 ToolError 签名的 AgentError。

    用法（向后兼容）::
        raise ToolError("TOOL_TIMEOUT", "执行超时", tool_name="image_recognize")
    """
    # 兼容旧字符串码
    if isinstance(code, str):
        code = code  # type: ignore[assignment]
    details = {"tool_name": tool_name}
    if raw is not None:
        details["raw"] = raw
    return AgentError(
        code=code,  # type: ignore[arg-type]
        message=message,
        retryable=retryable,
        request_id=request_id,
        details=details,
    )


# ---- 工厂函数 ----

def from_code(
    code: ErrorCode,
    message: str | None = None,
    **kwargs: Any,
) -> AgentError:
    """
    从 ErrorCode 创建 AgentError，自动填充 retryable 等元数据。

    用法::
        raise from_code("LLM_TIMEOUT", "Qwen 服务响应超时")
        raise from_code("TOOL_NOT_FOUND", tool_name="xxx")
    """
    meta = get_error_meta(code)
    msg = message or meta.message_template
    return AgentError(
        code=code,
        message=msg,
        retryable=meta.retryable,
        **kwargs,
    )


# ---- 便捷构造器（按层） ----

def llm_error(
    sub_code: Literal[
        "AUTH_FAILED", "RATE_LIMITED", "TIMEOUT", "NETWORK_ERROR",
        "MODEL_UNAVAILABLE", "INPUT_TOO_LARGE", "BAD_REQUEST",
        "EMPTY_RESPONSE", "STREAM_STALLED",
    ],
    message: str | None = None,
    **kwargs: Any,
) -> AgentError:
    code: ErrorCode = f"LLM_{sub_code}"  # type: ignore[assignment]
    return from_code(code, message, **kwargs)


def tool_error(
    sub_code: Literal[
        "NOT_FOUND", "INVALID_ARGUMENT", "TIMEOUT",
        "UPSTREAM_ERROR", "PERMISSION_DENIED",
    ],
    message: str | None = None,
    **kwargs: Any,
) -> AgentError:
    code: ErrorCode = f"TOOL_{sub_code}"  # type: ignore[assignment]
    return from_code(code, message, **kwargs)


def agent_error(
    sub_code: Literal[
        "MAX_STEPS_EXCEEDED", "CONTEXT_OVERFLOW", "TOOL_LOOP",
    ],
    message: str | None = None,
    **kwargs: Any,
) -> AgentError:
    code: ErrorCode = f"AGENT_{sub_code}"  # type: ignore[assignment]
    return from_code(code, message, **kwargs)

