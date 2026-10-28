"""
SIA_agent.tools.base - 工具抽象基座

提供工具系统的核心抽象：
- ToolSpec：工具元数据（名称、描述、分类、输入/输出 schema、超时、幂等性）
- Tool：所有可注册工具的抽象基类，子类实现 `invoke` 完成具体逻辑

工具分类（category 字段）：
- "general"：通用工具（ToolRepository），如计算器、图像识别、语音转写
- "algorithm"：业务算法工具（AlgorithmRepository），如安全监测、图像分析

使用示例::

    from SIA_agent.tools.base import Tool, ToolSpec, ToolCategory

    class MyTool(Tool):
        def __init__(self) -> None:
            super().__init__(ToolSpec(
                name="my_tool",
                description="我的自定义工具",
                category="general",
                input_schema={"query": "string"},
                timeout_ms=30000,
            ))

        def invoke(self, arguments: dict[str, Any], *, request_id: str | None = None):
            query = arguments.get("query")
            return ToolResult(ok=True, tool_name=self.spec.name,
                              request_id=request_id, data={"result": query})
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Literal

from .types import ToolResult

ToolCategory = Literal["general", "algorithm"]


@dataclass(frozen=True)
class ToolSpec:
    """工具元数据：名称、描述、分类、可选输入/输出 schema、超时与幂等性标记。

    display_name：可选，面向 UI / SSE 的短标签；未设置时由调用方回退为通用文案。
    ui_agent_label / ui_agent_hint：可选，SSE 上标识「子能力智能体」名称与一行说明。
    category：工具分类，"general"（通用工具）或 "algorithm"（算法工具）；Agent 可据此区分工具来源。
    """

    name: str
    description: str
    category: ToolCategory = "general"
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    timeout_ms: int = 30000
    side_effect: bool | None = None
    idempotent: bool | None = None
    display_name: str | None = None
    ui_agent_label: str | None = None
    ui_agent_hint: str | None = None


class Tool(abc.ABC):
    """所有可注册工具的抽象基类：子类实现 `invoke` 完成具体逻辑。"""

    def __init__(self, spec: ToolSpec) -> None:
        """初始化工具实例。

        Args:
            spec: 工具规格，包含名称、描述、分类、输入输出schema等元数据。

        Returns:
            None
        """
        self.spec = spec

    @abc.abstractmethod
    def invoke(self, arguments: dict[str, Any], *, request_id: str | None = None) -> ToolResult:
        """执行工具的核心逻辑。

        Args:
            arguments: 从模型 tool_calls 解析后的参数字典，由 ToolRegistry 按 spec.input_schema 校验后传入。
            request_id: 可选的请求追踪ID，用于日志关联。

        Returns:
            ToolResult: 执行结果，包含 ok 状态、工具名、请求ID、可选数据或错误信息。

        Raises:
            NotImplementedError: 抽象方法，子类必须实现。
        """
        raise NotImplementedError

