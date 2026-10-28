"""Agent 模块 - 推理链路统一出口（框架层）

- BaseAgent   : 公共基类，工具解析与观察格式化
- SimpleAgent : 轻量级 chat + 工具调用
- ReActAgent  : 标准 ReAct（Thought-Action-Observation）循环

Usage:
    from SIA_agent.agent import SimpleAgent, ReActAgent

    agent = SimpleAgent(model_manager=..., tool_registry=..., context_manager=...)
    for event in agent.stream(session_id="s1", user_input="你好"):
        print(event)
"""

from .base_agent import BaseAgent
from .main_agent import SimpleAgent
from .react_agent import ReActAgent

__all__ = ["BaseAgent", "SimpleAgent", "ReActAgent"]

