"""BaseAgent - 所有 Agent 的公共基座

本模块定义了所有 Agent 的公共基类 BaseAgent，集中管理：
- 工具描述格式化（_format_tools_for_prompt）
- 工具调用解析（_parse_tool_calls，支持 JSON/ReAct 文本/自然语言三种格式）
- 观察结果格式化（_format_observation）
- 工具合法性验证（_is_valid_tool）

子类只需继承并实现：
- _default_prompt_path()：返回默认 system prompt 资源路径
- stream()：流式处理接口（yield SSE 事件）
- build_turn_llm_messages()：构建 LLM 消息列表（可选）

工具调用统一格式（标准，优先使用）：
    {"tool_call": {"name": "工具名", "arguments": {"参数1": "值1"}}}

兼容旧格式：
    {"action": "工具名", "action_input": {"参数1": "值1"}}
    {"tool_name": "工具名", "arguments": {"参数1": "值1"}}

Example:
    class MyAgent(BaseAgent):
        def _default_prompt_path(self) -> str:
            return "agent/my_agent_default.txt"

        def stream(self, *, session_id: str, user_input: str, **kwargs):
            # 实现流式处理逻辑
            ...
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from ..context import ContextManagerBase
from ..model_manager.manager import ModelManager
from ..prompts import load_prompt
from ..tools.registry import ToolRegistry
from ..tools.schema import tool_parameters_from_input_schema
from ..tools.types import ToolResult


class BaseAgent:
    """
    Agent 基类：定义公共方法，子类实现各自的推理流程。

    公共方法：
    - _format_tools_for_prompt：将工具列表格式化为提示词
    - _parse_tool_calls：解析文本中的工具调用（JSON + 自然语言；后者见 _parse_tool_calls_natural_language）
    - _is_valid_tool：验证工具是否在可用列表
    - _format_observation：格式化工具执行结果

    子类需要实现：
    - stream：流式处理接口（yield SSE 事件）
    - build_turn_llm_messages：构建 LLM 消息列表（可选）
    """

    # 工具名解析正则（自然语言格式）
    PAT_PAT_ACTION = re.compile(
        r"(?:action|tool|调用|使用)\s*[:：]?\s*['\"]?([\w_]+)['\"]?",
        re.IGNORECASE,
    )
    PAT_ACTION_INPUT = re.compile(
        r"```(?:json)?\s*(\{[^`]+\})\s*```|`([^`]+)`|"
        r"(?:input|参数|参数输入)\s*[:：]?\s*(\{[^}\n]+\})",
        re.DOTALL,
    )

    def __init__(
        self,
        *,
        model_manager: ModelManager,
        tool_registry: ToolRegistry,
        context_manager: ContextManagerBase | None = None,
        system_prompt: str | None = None,
        max_steps: int | None = 8,
        window_last_n: int = 20,
        tool_stream_card: Callable[[str, ToolResult], dict[str, Any] | None] | None = None,
        tool_start_card: Callable[..., dict[str, Any] | None] | None = None,
        stream_reasoning_agent: dict[str, Any] | None = None,
    ) -> None:
        """初始化 Agent 实例。

        Args:
            model_manager: 模型管理器，负责 LLM 调用和模型选择。
            tool_registry: 工具注册表，提供可用工具的注册、查询和调用。
            context_manager: 可选的上下文管理器，用于会话历史管理和记忆检索。
            system_prompt: 可选的 System Prompt，如果为 None 则从默认路径加载。
            max_steps: 最大推理步数；默认 8。传 ``None`` 表示不设上限（可能长时间运行）。
            window_last_n: 上下文窗口中保留的最近消息数量，默认 20。
            tool_stream_card: 可选；工具结束后为 SSE 生成结构化 UI 载荷（如 kind 字段）。
            tool_start_card: 可选；(tool_name, arguments, *, tool_call_id, request_id) → tool_start 卡片。
            stream_reasoning_agent: 可选；写入 reasoning_start/end 的 agent（主智能体 UI）。

        Returns:
            None
        """
        self._model_manager = model_manager
        self._tool_registry = tool_registry
        self._context_manager = context_manager
        self._system_prompt = system_prompt or load_prompt(self._default_prompt_path())
        self._max_steps: int | None = None if max_steps is None else int(max_steps)
        self._window_last_n = int(window_last_n)
        self._tool_stream_card = tool_stream_card
        self._tool_start_card = tool_start_card
        self._stream_reasoning_agent = stream_reasoning_agent

    def _sse_tool_agent_meta(self, tool_name: str) -> dict[str, Any] | None:
        """供 SSE 展示：工具对应的子能力 / 逻辑智能体说明（来自 ToolSpec）。"""
        tool = self._tool_registry.get(tool_name)
        if tool is None:
            return None
        label = tool.spec.ui_agent_label
        if not isinstance(label, str) or not label.strip():
            return None
        out: dict[str, Any] = {"label": label.strip()}
        hint = tool.spec.ui_agent_hint
        if isinstance(hint, str) and hint.strip():
            out["hint"] = hint.strip()
        return out

    def _default_prompt_path(self) -> str:
        """子类覆盖：指定默认 system prompt 路径。"""
        raise NotImplementedError

    # ── 公共方法 ────────────────────────────────────────

    def _format_tools_for_prompt(self, tool_specs: list) -> str:
        """将工具规范列表格式化为供 LLM 阅读的文本描述。

        Args:
            tool_specs: 工具规范列表，每个元素为 dict，应包含 name/description/parameters 字段。

        Returns:
            格式化后的工具描述文本，每项以 "- **工具名**: 描述" 开头，
            参数则以 "  参数：" 子节列出。

        Example:
            >>> tools = [{"name": "calc", "description": "计算器", "parameters": {"properties": {"a": {"type": "int"}}}}]
            >>> agent._format_tools_for_prompt(tools)  # doctest: +SKIP
            '- **calc**: 计算器\\n  参数：\\n    - a: int （必填）'
        """
        if not tool_specs:
            return "（无可用工具）"

        lines = []
        for spec in tool_specs:
            if not isinstance(spec, dict):
                continue
            name = spec.get("name", "unknown")
            desc = spec.get("description", "无描述")
            params = spec.get("parameters") or tool_parameters_from_input_schema(spec.get("input_schema"))

            lines.append(f"- **{name}**: {desc}")
            if params:
                param_lines = []
                props = params.get("properties", {})
                required = params.get("required", [])
                for pname, pinfo in props.items():
                    ptype = pinfo.get("type", "any")
                    pdesc = pinfo.get("description", "")
                    req_mark = "（必填）" if pname in required else "（可选）"
                    param_lines.append(f"    - {pname}: {ptype} {req_mark} {pdesc}")
                if param_lines:
                    lines.append("  参数：")
                    lines.extend(param_lines)

        return "\n".join(lines)

    def _parse_tool_calls_from_json(self, text: str) -> list[dict[str, Any]]:
        """解析 JSON 形态的工具调用。

        区域类型：
        1. 代码块区域：```...``` 或 ```json...```
        2. ReAct 标准区域：Action: / Action Input: 等标记周围
        3. 专用标记区域：<tool_call>...</tool_call>
        4. 独立 JSON 对象：文本整体是一个有效的 JSON 对象

        这样可以兼容模型直接输出裸 JSON 的情况。
        """
        import logging
        _logger = logging.getLogger(__name__)
        calls: list[dict[str, Any]] = []

        # 1. 先尝试提取特定标记区域
        regions = self._extract_tool_call_regions(text)
        for region_text in regions:
            parsed = self._parse_json_in_region(region_text, len(calls))
            if parsed:
                _logger.info(f"[ToolCall] Found {len(parsed)} calls from marked region")
                calls.extend(parsed)

        # 2. 如果标记区域没有找到，尝试将整个文本作为独立 JSON 解析
        # 这处理模型直接输出 {"tool_name": "...", "arguments": {...}} 的情况
        if not calls:
            _logger.debug(f"[ToolCall] No calls from regions, trying direct JSON parse on text (len={len(text)})")
            parsed = self._parse_json_in_region(text.strip(), 0)
            if parsed:
                _logger.info(f"[ToolCall] Found {len(parsed)} calls from direct JSON parse")
                calls.extend(parsed)

        if not calls:
            _logger.warning(f"[ToolCall] No tool calls extracted from text (len={len(text)}): {text[:200]!r}")

        return calls

    def _extract_tool_call_regions(self, text: str) -> list[str]:
        """提取允许解析工具调用的区域。"""
        regions: list[str] = []

        # 1. 代码块区域：```...``` 或 ```json...```
        # 注意：去掉多余的空格匹配，确保能匹配换行后的内容
        code_block_pattern = re.compile(r"```(?:json)?\s*\n?([\s\S]*?)```", re.IGNORECASE)
        for match in code_block_pattern.finditer(text):
            block_content = match.group(1).strip()
            if block_content:
                regions.append(block_content)

        # 2. ReAct 标准区域：Action: ... 附近的内容
        # 提取 Action: 和 Action Input: 之间的内容
        react_pattern = re.compile(
            r"(?:^|\n)\s*(?:Action|action|调用)\s*[:：]\s*([^\n]+)"
            r"(?:\n\s*(?:Action\s*[Ii]nput|action_input|参数)\s*[:：]?\s*(.+))?",
            re.DOTALL | re.MULTILINE,
        )
        for match in react_pattern.finditer(text):
            action_part = match.group(1).strip()
            input_part = match.group(2).strip() if match.group(2) else ""
            combined = action_part + "\n" + input_part
            if combined.strip():
                regions.append(combined)

        # 3. 专用标记区域：<tool_call>...</tool_call>
        tool_call_tag_pattern = re.compile(
            r"<tool[_ ]?call[^>]*>([\s\S]*?)</tool[_ ]?call>",
            re.IGNORECASE,
        )
        for match in tool_call_tag_pattern.finditer(text):
            tag_content = match.group(1).strip()
            if tag_content:
                regions.append(tag_content)

        return regions

    def _parse_json_in_region(self, region_text: str, start_id: int) -> list[dict[str, Any]]:
        """在指定区域内解析 JSON 工具调用。"""
        import logging
        _logger = logging.getLogger(__name__)

        calls: list[dict[str, Any]] = []
        region_text = region_text.strip()

        # 预处理：处理双重 JSON 编码的情况（如 SSE 日志中的 \"{...}\"）
        normalized = self._normalize_json_like(region_text)
        if normalized.startswith('"') and normalized.endswith('"'):
            # 尝试去除外层引号（双重编码情况）
            try:
                outer = json.loads(normalized)
                if isinstance(outer, str):
                    normalized = outer
            except json.JSONDecodeError:
                pass

        # 尝试整体解析（如果区域本身就是一个完整 JSON）
        for attempt_text in [region_text, normalized]:
            try:
                obj = json.loads(attempt_text)
                if isinstance(obj, dict):
                    parsed = self._extract_tool_calls_from_object(obj, start_id)
                    if parsed:
                        _logger.info(f"[ToolCall] Region parsed as JSON, found {len(parsed)} calls")
                        return parsed
                if isinstance(obj, list):
                    acc: list[dict[str, Any]] = []
                    nid = start_id
                    for elem in obj:
                        if isinstance(elem, dict):
                            sub = self._extract_tool_calls_from_object(elem, nid)
                            acc.extend(sub)
                            nid += len(sub)
                    if acc:
                        _logger.info(f"[ToolCall] Region parsed as JSON array, found {len(acc)} calls")
                        return acc
            except json.JSONDecodeError:
                continue

        # 逐个解析区域内的 JSON 对象
        n = len(region_text)
        found = 0
        for j in range(n):
            if region_text[j] != "{":
                continue
            raw = self._slice_balanced_json_object(region_text, j)
            if not raw:
                continue
            for attempt_raw in [raw, self._normalize_json_like(raw)]:
                try:
                    obj = json.loads(attempt_raw)
                    if isinstance(obj, dict):
                        parsed = self._extract_tool_calls_from_object(obj, start_id + len(calls))
                        if parsed:
                            found += 1
                        calls.extend(parsed)
                        break  # 成功解析，跳过其他尝试
                    if isinstance(obj, list):
                        nid = start_id + len(calls)
                        for elem in obj:
                            if isinstance(elem, dict):
                                sub = self._extract_tool_calls_from_object(elem, nid)
                                if sub:
                                    found += 1
                                calls.extend(sub)
                                nid += len(sub)
                        if calls:
                            break
                except json.JSONDecodeError:
                    continue

        if found > 0:
            _logger.info(f"[ToolCall] Found {found} tool calls in region")
        return calls

    def _extract_tool_calls_from_object(
        self, obj: dict[str, Any], start_id: int
    ) -> list[dict[str, Any]]:
        """从单个 JSON 对象中提取工具调用信息。

        优先识别标准格式 ``{"tool_call": {"name": ..., "arguments": ...}}``，
        兼容旧格式 ``{"action": ..., "action_input": ...}`` 和
        ``{"tool_name": ..., "arguments": ...}``。

        Args:
            obj: 已解析的 JSON 对象。
            start_id: 工具调用 ID 的起始序号，用于生成唯一 ID。

        Returns:
            工具调用信息列表，每项含 name/arguments/id。
        """
        calls: list[dict[str, Any]] = []

        # 优先解析 tool_call 格式（标准格式）
        tool_call = obj.get("tool_call")
        if isinstance(tool_call, dict):
            name = tool_call.get("name")
            if isinstance(name, str) and name.strip():
                arguments = tool_call.get("arguments", {})
                if not isinstance(arguments, dict):
                    arguments = {}
                calls.append({
                    "name": name.strip(),
                    "arguments": arguments,
                    "id": f"{self._agent_prefix()}_{start_id}",
                })
            return calls

        # OpenAI Chat Completions 风格 tool_calls[]
        tc_list = obj.get("tool_calls")
        if isinstance(tc_list, list):
            out: list[dict[str, Any]] = []
            nid = start_id
            for item in tc_list:
                if not isinstance(item, dict):
                    continue
                fn = item.get("function")
                if isinstance(fn, dict):
                    n = fn.get("name")
                    raw_args = fn.get("arguments", "{}")
                    if isinstance(raw_args, str):
                        try:
                            arguments = json.loads(raw_args)
                        except json.JSONDecodeError:
                            arguments = {}
                    else:
                        arguments = raw_args if isinstance(raw_args, dict) else {}
                else:
                    n = item.get("name")
                    arguments = item.get("arguments", {})
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            arguments = {}
                    if not isinstance(arguments, dict):
                        arguments = {}
                if isinstance(n, str) and n.strip():
                    out.append({
                        "name": n.strip(),
                        "arguments": arguments,
                        "id": f"{self._agent_prefix()}_{nid}",
                    })
                    nid += 1
            if out:
                return out

        # 兼容旧格式（action/action_input 或 tool_name/arguments）
        action = obj.get("action") or obj.get("tool_name")
        if isinstance(action, str) and action.strip():
            action_input = obj.get("action_input") or obj.get("arguments", {})
            if not isinstance(action_input, dict):
                action_input = {}
            calls.append({
                "name": action.strip(),
                "arguments": action_input,
                "id": f"{self._agent_prefix()}_{start_id}",
            })
            return calls

        # 顶层 {"name": "...", "arguments": {...}}（部分模型直接输出）
        nm = obj.get("name")
        if isinstance(nm, str) and nm.strip():
            args = obj.get("arguments")
            if args is None:
                args = {}
            elif isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if isinstance(args, dict):
                calls.append({
                    "name": nm.strip(),
                    "arguments": args,
                    "id": f"{self._agent_prefix()}_{start_id}",
                })
                return calls

        return calls

    def _parse_tool_calls_natural_language(self, text: str) -> list[dict[str, Any]]:
        """JSON 未命中时的自然语言/松散格式；ReActAgent 覆盖为 Action:/Action Input: 等。"""
        calls: list[dict[str, Any]] = []
        for i, match in enumerate(self.PAT_PAT_ACTION.finditer(text)):
            tool_name = match.group(1).strip()
            if not tool_name:
                continue
            arguments: dict[str, Any] = {}
            input_match = self.PAT_ACTION_INPUT.search(text, match.end())
            if input_match:
                raw_arg = input_match.group(1) or input_match.group(2) or input_match.group(3)
                if raw_arg:
                    try:
                        arguments = json.loads(raw_arg.strip())
                    except json.JSONDecodeError:
                        arguments = self._parse_key_value_args(raw_arg)
            calls.append({
                "name": tool_name,
                "arguments": arguments,
                "id": f"{self._agent_prefix()}_nl_{i}",
            })
        return calls

    def _parse_tool_calls(self, text: str) -> list[dict[str, Any]]:
        """解析文本中的工具调用。

        优先尝试 JSON 格式解析（_parse_tool_calls_from_json），若失败则
        回退到自然语言解析（_parse_tool_calls_natural_language）。

        Args:
            text: LLM 输出的原始文本。

        Returns:
            工具调用列表，每项结构为 {"name": str, "arguments": dict, "id": str}。
            若未解析到任何工具调用，返回空列表。
        """
        calls = self._parse_tool_calls_from_json(text)
        if not calls:
            calls = self._parse_tool_calls_natural_language(text)
        return calls

    @staticmethod
    def _agent_prefix() -> str:
        """子类覆盖：返回工具调用 ID 前缀。"""
        return "agent"

    def _parse_key_value_args(self, text: str) -> dict[str, Any]:
        """解析 key=value 格式的参数。"""
        result = {}
        pattern = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s,\}]+))')
        for match in pattern.finditer(text):
            key = match.group(1)
            value = match.group(2) or match.group(3) or match.group(4)
            if value:
                result[key] = value
        return result

    @staticmethod
    def _slice_balanced_json_object(text: str, start: int) -> str | None:
        """从 `{` 起点截取与之配平的 JSON 对象子串。"""
        if start < 0 or start >= len(text) or text[start] != "{":
            return None
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if in_string:
                if ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    @staticmethod
    def _normalize_json_like(s: str) -> str:
        """替换弯引号为 ASCII 引号。"""
        return (
            s.replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("\uff02", '"')
            .replace("\u2018", "'")
            .replace("\u2019", "'")
        )

    @staticmethod
    def _span_strictly_inside(inner: tuple[int, int], outer: tuple[int, int]) -> bool:
        """inner 是否完全落在外层 span 内。"""
        a, b = inner
        x, y = outer
        return x < a and b < y

    def _is_valid_tool(self, name: str, args: Any, tool_specs: list) -> bool:
        """验证工具名是否在可用列表中且参数为 dict。

        Args:
            name: 工具名称。
            args: 工具参数，应为 dict。
            tool_specs: 当前会话可用的工具规范列表。

        Returns:
            工具名存在于 tool_specs 且 args 为 dict 时返回 True，否则 False。
        """
        if not isinstance(name, str) or not isinstance(args, dict):
            return False
        allowed = {t["name"] for t in tool_specs if isinstance(t, dict) and isinstance(t.get("name"), str)}
        return name in allowed

    def _format_observation(self, tool_name: str, args: dict, result: ToolResult) -> str:
        """将工具执行结果格式化为供 LLM 下一轮阅读的文本。

        默认使用 ``prompts/agent/tool_observation.txt`` 模板渲染，
        结果超长（>4000 字符）时自动截断并附提示。

        子类（如 ReActAgent）可覆盖此方法实现特殊处理，
        例如 RAG 工具使用简短格式避免把大段原文抄进推理过程。

        Args:
            tool_name: 工具名称。
            args: 调用工具时使用的参数。
            result: 工具执行结果（ToolResult）。

        Returns:
            格式化后的观察文本，用于注入 LLM 消息列表。
        """
        result_dict = asdict(result)
        result_str = json.dumps(result_dict, ensure_ascii=False, indent=2)
        if len(result_str) > 4000:
            result_str = result_str[:4000] + "\n[结果过长，已截断]"
        from ..prompts import load_prompt_fmt

        return load_prompt_fmt(
            "agent/tool_observation.txt",
            tool_name=tool_name,
            args=json.dumps(args, ensure_ascii=False, indent=2),
            result=result_str,
        )
