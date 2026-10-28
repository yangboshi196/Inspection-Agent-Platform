"""
SIA_agent - Agent 框架（LLM、记忆、提示词、RAG、工具调用）

对外常用入口：
- SimpleAgent / ReActAgent : Agent 实现
- ToolRegistry             : 工具注册表
- ModelManager             : 多模型调度
- HybridMemoryContextManager / ContextManager : 上下文与混合记忆
"""

from .agent.main_agent import SimpleAgent
from .agent.react_agent import ReActAgent
from .context import (
    ContextManager,
    ContextManagerBase,
    HybridMemoryConfig,
    HybridMemoryContextManager,
    format_memory_for_prompt,
)
from .model_manager.manager import ModelManager
from .tools.registry import ToolRegistry

__all__ = [
    "SimpleAgent",
    "ReActAgent",
    "ModelManager",
    "ToolRegistry",
    "ContextManager",
    "ContextManagerBase",
    "HybridMemoryConfig",
    "HybridMemoryContextManager",
    "format_memory_for_prompt",
]
