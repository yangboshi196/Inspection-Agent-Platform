"""Prompts 模块 - 提示词文件统一加载入口

职责：从 SIA_agent/prompts/ 目录按相对路径加载文案模板。

核心接口：
- load_prompt(path)      : 加载纯文本模板
- load_prompt_fmt(path)  : 加载并格式化（支持 {占位符}）
- load_prompt_json(path) : 加载 JSON 对象（如标签字典）

路径规范：相对 SIA_agent/prompts/ 的 POSIX 风格子路径。
示例：load_prompt("agent/react_agent_default.txt")

Usage:
    from SIA_agent.prompts import load_prompt, load_prompt_fmt

    system_prompt = load_prompt("agent/react_agent_default.txt")
    obs_text = load_prompt_fmt("agent/tool_observation.txt", tool_name="calc", result="5")
"""

from .loader import load_prompt, load_prompt_fmt, load_prompt_json

__all__ = ["load_prompt", "load_prompt_fmt", "load_prompt_json"]
