"""
统一错误码定义。

覆盖 LLM 层、工具层、Agent 层、API 层的所有错误场景。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ---- 错误分类 ----

ErrorCategory = Literal["LLM", "TOOL", "AGENT", "API", "CONTEXT", "INTERNAL"]


# ---- 统一错误码 ----
# 格式：[分类_子码]，分类用于快速定位，子码用于精确判断。
ErrorCode = Literal[
    # ---- LLM 层 (1xx) ----
    "LLM_AUTH_FAILED",          # 鉴权失败 / key 无效
    "LLM_RATE_LIMITED",         # 限流
    "LLM_TIMEOUT",              # 请求超时
    "LLM_NETWORK_ERROR",        # 网络不通
    "LLM_MODEL_UNAVAILABLE",    # 模型不可用或不支持
    "LLM_INPUT_TOO_LARGE",      # 输入超限
    "LLM_BAD_REQUEST",          # 请求格式错误（400）
    "LLM_EMPTY_RESPONSE",       # 模型返回为空
    "LLM_STREAM_STALLED",       # 流式首包超时
    # ---- 工具层 (2xx) ----
    "TOOL_NOT_FOUND",           # 工具不存在
    "TOOL_INVALID_ARGUMENT",    # 参数校验失败
    "TOOL_TIMEOUT",            # 执行超时
    "TOOL_UPSTREAM_ERROR",      # 工具内部调用失败
    "TOOL_PERMISSION_DENIED",   # 权限不足
    # ---- Agent 层 (3xx) ----
    "AGENT_MAX_STEPS_EXCEEDED", # 超过最大推理步数
    "AGENT_CONTEXT_OVERFLOW",   # 上下文溢出
    "AGENT_TOOL_LOOP",          # 检测到工具循环调用
    # ---- API 层 (4xx) ----
    "API_BAD_REQUEST",          # 请求格式错误（400）
    "API_NOT_FOUND",            # 资源不存在（404）
    "API_UNAUTHORIZED",         # 未认证（401）
    "API_SESSION_NOT_FOUND",    # 会话不存在
    "API_PROMPT_NOT_FOUND",     # 提示词文件不存在
    # ---- Context 层 (5xx) ----
    "CTX_SESSION_NOT_FOUND",    # 会话不存在
    "CTX_PERSISTENCE_ERROR",    # 持久化失败
    # ---- 内部错误 (9xx) ----
    "INTERNAL_ERROR",           # 未分类的内部错误
    "INTERNAL_UNIMPLEMENTED",   # 功能未实现
]


# ---- 错误码元数据（可查表用于日志/监控） ----

@dataclass
class _ErrorMeta:
    category: ErrorCategory
    retryable: bool
    http_status: int  # API 层参考，非 API 层不一定适用
    message_template: str


_ERROR_META: dict[ErrorCode, _ErrorMeta] = {
    # LLM
    "LLM_AUTH_FAILED":        _ErrorMeta("LLM", False, 401, "鉴权失败，请检查 API Key 配置"),
    "LLM_RATE_LIMITED":       _ErrorMeta("LLM", True,  429, "请求被限流，请稍后重试"),
    "LLM_TIMEOUT":            _ErrorMeta("LLM", True,  504, "LLM 请求超时"),
    "LLM_NETWORK_ERROR":      _ErrorMeta("LLM", True,  502, "无法连接到 LLM 服务"),
    "LLM_MODEL_UNAVAILABLE":  _ErrorMeta("LLM", False, 503, "模型不可用或不支持当前请求"),
    "LLM_INPUT_TOO_LARGE":    _ErrorMeta("LLM", False, 413, "输入超出模型上下文限制"),
    "LLM_BAD_REQUEST":        _ErrorMeta("LLM", False, 400, "LLM 请求格式错误"),
    "LLM_EMPTY_RESPONSE":     _ErrorMeta("LLM", False, 500, "模型返回为空"),
    "LLM_STREAM_STALLED":     _ErrorMeta("LLM", True,  504, "流式响应首包超时"),
    # Tool
    "TOOL_NOT_FOUND":         _ErrorMeta("TOOL", False, 404, "工具不存在"),
    "TOOL_INVALID_ARGUMENT":  _ErrorMeta("TOOL", False, 400, "工具参数校验失败"),
    "TOOL_TIMEOUT":           _ErrorMeta("TOOL", True,  504, "工具执行超时"),
    "TOOL_UPSTREAM_ERROR":    _ErrorMeta("TOOL", True,  502, "工具内部调用失败"),
    "TOOL_PERMISSION_DENIED": _ErrorMeta("TOOL", False, 403, "工具权限不足"),
    # Agent
    "AGENT_MAX_STEPS_EXCEEDED":  _ErrorMeta("AGENT", False, 400, "超过最大推理步数，请简化任务"),
    "AGENT_CONTEXT_OVERFLOW":    _ErrorMeta("AGENT", False, 400, "上下文超出限制"),
    "AGENT_TOOL_LOOP":           _ErrorMeta("AGENT", False, 400, "检测到工具循环调用"),
    # API
    "API_BAD_REQUEST":        _ErrorMeta("API",  False, 400, "请求格式错误"),
    "API_NOT_FOUND":          _ErrorMeta("API",  False, 404, "资源不存在"),
    "API_UNAUTHORIZED":       _ErrorMeta("API",  False, 401, "未认证"),
    "API_SESSION_NOT_FOUND":  _ErrorMeta("API",  False, 404, "会话不存在"),
    "API_PROMPT_NOT_FOUND":   _ErrorMeta("API",  False, 404, "提示词文件不存在"),
    # Context
    "CTX_SESSION_NOT_FOUND":  _ErrorMeta("CONTEXT", False, 404, "会话不存在"),
    "CTX_PERSISTENCE_ERROR":  _ErrorMeta("CONTEXT", True,  500, "上下文持久化失败"),
    # Internal
    "INTERNAL_ERROR":         _ErrorMeta("INTERNAL", False, 500, "内部错误"),
    "INTERNAL_UNIMPLEMENTED": _ErrorMeta("INTERNAL", False, 501, "功能未实现"),
}


def get_error_meta(code: ErrorCode) -> _ErrorMeta:
    """查询错误码元数据。"""
    return _ERROR_META.get(code, _ERROR_META["INTERNAL_ERROR"])


def is_retryable(code: ErrorCode) -> bool:
    return get_error_meta(code).retryable


def http_status_of(code: ErrorCode) -> int:
    return get_error_meta(code).http_status
