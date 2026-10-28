"""
SIA_agent.errors - 统一错误体系

使用示例::

    from SIA_agent.errors import AgentError, from_code, format_error_sse

    # 抛出
    raise from_code("LLM_TIMEOUT", "模型响应超时")

    # SSE 格式化
    try:
        ...
    except Exception as e:
        yield format_error_sse(e)
"""

from .codes import ErrorCode
from .exceptions import AgentError, LLMError, ToolError, from_code
from .sse import format_error_sse

__all__ = [
    "ErrorCode",
    "AgentError",
    "LLMError",
    "ToolError",
    "from_code",
    "format_error_sse",
]
