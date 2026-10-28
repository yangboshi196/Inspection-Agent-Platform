"""
SIA_agent.tools.types - 工具层数据结构

定义工具执行结果与错误类型：
- ToolError：工具调用失败时的结构化错误（含错误码、消息、是否可重试）
- ToolResult：工具执行结果（ok=True 成功 / ok=False 失败）
- ToolErrorCode：工具层错误码枚举

错误码说明：
- INVALID_ARGUMENT：参数校验失败
- TIMEOUT：工具执行超时
- NOT_FOUND：工具不存在
- PERMISSION_DENIED：无权限
- UPSTREAM_ERROR：上游服务异常
- UNKNOWN：其他未知错误
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


ToolErrorCode = Literal[
    "INVALID_ARGUMENT",
    "TIMEOUT",
    "NOT_FOUND",
    "PERMISSION_DENIED",
    "UPSTREAM_ERROR",
    "UNKNOWN",
]


@dataclass(frozen=True)
class ToolError:
    code: ToolErrorCode
    message: str
    request_id: str | None
    tool_name: str
    retryable: bool = False
    raw: Any | None = None


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    tool_name: str
    request_id: str | None
    data: Any | None = None
    error: ToolError | None = None

