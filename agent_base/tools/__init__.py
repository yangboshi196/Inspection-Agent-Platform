"""工具层：注册表、规格与执行结果类型（框架核心，不含业务 ToolRepository）。"""

from .base import Tool, ToolCategory, ToolSpec
from .registry import ToolRegistry
from .schema import tool_parameters_from_input_schema
from .types import ToolError, ToolResult

__all__ = [
    "Tool",
    "ToolSpec",
    "ToolCategory",
    "ToolRegistry",
    "ToolError",
    "ToolResult",
    "tool_parameters_from_input_schema",
]
