"""
SIA_agent.tools.registry - 工具注册表

内存中的工具注册中心，提供：
- 按名称注册 / 查询 / 列举工具
- 同步超时调用（`invoke`）
- 生成 OpenAI Chat Completions 兼容的 `tools` 数组

设计要点：
- 线程安全（`invoke` 使用 `ThreadPoolExecutor` 单线程执行）
- 超时控制：按工具 `spec.timeout_ms` 执行
- 工具名全局唯一，同名重复注册抛出 `ValueError`

使用示例::

    from SIA_agent.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(my_tool)
    result = registry.invoke("my_tool", {"query": "hello"})
"""

from __future__ import annotations

import concurrent.futures
import contextvars
from typing import Any

from .base import Tool
from .schema import tool_parameters_from_input_schema
from .types import ToolError, ToolResult


class ToolRegistry:
    """内存中的工具注册表：按名称注册、查询、列出 schema，并带超时地执行 `invoke`。"""

    def __init__(self) -> None:
        """初始化工具注册表。

        创建一个空的内存工具注册表，内部使用字典存储工具实例。

        Returns:
            None
        """
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册工具；同名重复注册会抛出 `ValueError`。"""
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"tool '{name}' already registered")
        self._tools[name] = tool

    def get(self, name: str) -> Tool | None:
        """按名称获取工具实例；不存在则返回 `None`。"""
        return self._tools.get(name)

    def list_specs(self) -> list[dict[str, Any]]:
        """内部/调试用的简化规格（name + description + category + input_schema）。"""
        specs = []
        for t in self._tools.values():
            specs.append(
                {
                    "name": t.spec.name,
                    "description": t.spec.description,
                    "category": t.spec.category,
                    "display_name": t.spec.display_name,
                    "ui_agent_label": t.spec.ui_agent_label,
                    "ui_agent_hint": t.spec.ui_agent_hint,
                    "input_schema": t.spec.input_schema,
                }
            )
        return specs

    def list_openai_tools(self) -> list[dict[str, Any]]:
        """OpenAI Chat Completions 兼容的 `tools` 数组项（`type` + `function` + `parameters`）。

        `function.description` 会注入 [分类: 通用工具/算法工具] 前缀，便于模型区分工具来源。
        """
        out: list[dict[str, Any]] = []
        for t in self._tools.values():
            params = tool_parameters_from_input_schema(t.spec.input_schema)
            cat_label = "算法工具" if t.spec.category == "algorithm" else "通用工具"
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.spec.name,
                        "description": f"[{cat_label}] {t.spec.description}",
                        "parameters": params,
                    },
                }
            )
        return out

    def invoke(self, name: str, arguments: dict[str, Any], *, request_id: str | None = None) -> ToolResult:
        """同步调用工具并在 `timeout_ms` 内返回结果；未找到工具或超时则返回失败 `ToolResult`。"""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(
                ok=False,
                tool_name=name,
                request_id=request_id,
                error=ToolError(
                    code="NOT_FOUND",
                    message=f"tool '{name}' not found",
                    request_id=request_id,
                    tool_name=name,
                    retryable=False,
                ),
            )

        timeout_s = max(0.001, tool.spec.timeout_ms / 1000.0)
        ctx = contextvars.copy_context()

        def _invoke() -> ToolResult:
            return tool.invoke(arguments, request_id=request_id)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(ctx.run, _invoke)
            try:
                return fut.result(timeout=timeout_s)
            except concurrent.futures.TimeoutError:
                return ToolResult(
                    ok=False,
                    tool_name=tool.spec.name,
                    request_id=request_id,
                    error=ToolError(
                        code="TIMEOUT",
                        message="tool execution timeout",
                        request_id=request_id,
                        tool_name=tool.spec.name,
                        retryable=bool(tool.spec.idempotent),
                    ),
                )
            except Exception as e:  # noqa: BLE001
                return ToolResult(
                    ok=False,
                    tool_name=tool.spec.name,
                    request_id=request_id,
                    error=ToolError(
                        code="UNKNOWN",
                        message=str(e),
                        request_id=request_id,
                        tool_name=tool.spec.name,
                        retryable=False,
                    ),
                )

