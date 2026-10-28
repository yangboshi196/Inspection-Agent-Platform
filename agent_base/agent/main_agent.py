"""SimpleAgent - 简单对话 + 工具调用 Agent

本模块实现 SimpleAgent（轻量级单轮对话 Agent）：
- 不使用 ReAct 推理循环，直接调用 chat
- 支持工具调用，最多循环 max_steps 次
- 同时提供 stream()（流式 SSE）和 run()（同步阻塞）两种接口

SSE 事件类型：
    thinking_delta : 文本增量（面向用户输出）
    tool_start     : 工具开始调用
    tool_end       : 工具执行结束
    done           : 完成
    error          : 错误

Usage:
    agent = SimpleAgent(model_manager=..., tool_registry=..., context_manager=...)
    for event in agent.stream(session_id="s1", user_input="你好"):
        print(event)
"""

import itertools
import json
from dataclasses import asdict
from typing import Any, Iterator

from ..context import ContextManagerBase, ContextManager, format_memory_for_prompt
from ..llm.types import ChatRequest, LlmChatMessage, to_llm_chat_message
from ..model_manager.manager import ModelManager
from ..tools.registry import ToolRegistry
from ..tools.types import ToolResult
from .base_agent import BaseAgent


class SimpleAgent(BaseAgent):
    """轻量级对话 Agent：无 ReAct 推理，直接 chat + 工具调用。

    Attributes:
        context: 当前绑定的上下文管理器，用于读写消息历史。

    继承自 BaseAgent，共享工具解析、格式化等公共方法。
    子类只需实现 _default_prompt_path() 和 stream()/run() 主体逻辑。

    与 ReActAgent 的区别：
    - SimpleAgent：无推理过程，适合简单问答和一次性工具调用
    - ReActAgent：标准 ReAct 循环，适合需要多步推理的复杂任务
    """

    def _default_prompt_path(self) -> str:
        return "agent/simple_agent_default.txt"

    @staticmethod
    def _agent_prefix() -> str:
        return "simple"

    @property
    def context(self) -> ContextManagerBase:
        """当前 Agent 绑定的上下文管理器（可读写消息）。"""
        return self._context_manager

    def build_turn_llm_messages(self, *, session_id: str) -> list[LlmChatMessage]:
        """
        在已将本轮 user 写入 context 之后，组装与 `run()` 首轮相同的 LLM messages（system + 摘要注入 + 窗口）。

        供流式对话等路径复用，避免与 `run()` 上下文不一致。
        """
        tool_specs = self._tool_registry.list_specs()
        tool_section = self._format_tools_for_prompt(tool_specs)
        system_prompt = (
            self._system_prompt.replace("{{available_tools}}", tool_section)
            if "{{available_tools}}" in self._system_prompt
            else f"{self._system_prompt}\n\n## 可用工具\n{tool_section}"
        )

        window = self._context_manager.get_window(session_id, last_n=self._window_last_n)
        llm_messages: list[LlmChatMessage] = [
            LlmChatMessage(role="system", content=system_prompt, metadata={})
        ]
        if hasattr(self._context_manager, "get_summaries"):
            hist, imp = self._context_manager.get_summaries(session_id)  # type: ignore[union-attr]
            mem_txt = format_memory_for_prompt(hist, imp)
            if mem_txt.strip():
                llm_messages.append(
                    LlmChatMessage(role="system", content=mem_txt, metadata={"kind": "memory_injection"})
                )
        for m in window:
            llm_messages.append(to_llm_chat_message(m))
        return llm_messages

    def stream(
        self,
        *,
        session_id: str,
        user_input: str,
        model_name: str | None = None,
        record_user_message: bool = True,
    ) -> Iterator[dict[str, Any]]:
        """流式处理单轮用户输入，yield SSE 事件。

        流程：
        1. 将 user 消息持久化到 context_manager（如启用）
        2. 构建 LLM 消息列表（system + 摘要 + 历史窗口）
        3. 调用 chat → 解析工具调用 → 执行工具 → 注入结果
        4. 循环至无工具调用或达到 max_steps
        5. 输出最终文本，yield done

        Args:
            session_id: 会话 ID，用于 context_manager 读写。
            user_input: 用户输入文本。
            model_name: 指定模型名称（None 则使用 ModelManager 默认）。
            record_user_message: 是否将 user 消息写入 context_manager。

        Yields:
            dict: SSE 事件字典，type 字段取：
            delta / tool_start / tool_end / done / error。
        """
        request_id = self._model_manager.new_request_id()
        try:
            if record_user_message and self._context_manager:
                self._context_manager.add_message(
                    session_id=session_id,
                    role="user",
                    content=user_input,
                    metadata={"request_id": request_id},
                )

            llm_messages = self.build_turn_llm_messages(session_id=session_id)
            tool_specs = self._tool_registry.list_specs()

            step_iter = (
                range(self._max_steps) if self._max_steps is not None else itertools.count()
            )
            for step in step_iter:
                # 调用 chat
                req = ChatRequest(
                    messages=llm_messages,
                    metadata={"request_id": request_id, "session_id": session_id},
                )
                resp = self._model_manager.call_chat(req, model_name=model_name)
                response_text = resp.content or ""

                # 记录 assistant 消息
                if self._context_manager:
                    self._context_manager.add_message(
                        session_id=session_id,
                        role="assistant",
                        content=response_text,
                        metadata={"request_id": request_id},
                    )
                llm_messages.append(LlmChatMessage(role="assistant", content=response_text, metadata={}))

                # 解析工具调用
                tool_calls = self._parse_tool_calls(response_text)

                if not tool_calls:
                    # 无工具调用 → 输出文本，结束
                    if response_text:
                        yield {"type": "delta", "text": response_text}
                    break

                # 执行工具
                for call in tool_calls:
                    name = call.get("name", "")
                    args = call.get("arguments", {})
                    tool_call_id = call.get("id", f"simple_{step}_{id(self)}")

                    if not self._is_valid_tool(name, args, tool_specs):
                        err_obs = (
                            f"[TOOL_RESULT: {name}]\n"
                            f"执行失败：工具名不在可用列表或参数不是 JSON 对象。"
                        )
                        if self._context_manager:
                            self._context_manager.add_message(
                                session_id=session_id,
                                role="user",
                                content=err_obs,
                                metadata={"tool_call_id": tool_call_id},
                            )
                        llm_messages.append(LlmChatMessage(role="user", content=err_obs, metadata={}))
                        continue

                    # SSE: 工具开始
                    yield {
                        "type": "tool_start",
                        "tool": {"name": name, "tool_call_id": tool_call_id},
                    }

                    result: ToolResult = self._tool_registry.invoke(name, args, request_id=request_id)

                    # SSE: 工具结束
                    yield {
                        "type": "tool_end",
                        "tool": {"name": name, "tool_call_id": tool_call_id, "ok": result.ok},
                    }

                    # 注入观察结果
                    observation = self._format_observation(name, args, result)
                    if self._context_manager:
                        self._context_manager.add_message(
                            session_id=session_id,
                            role="user",
                            content=observation,
                            metadata={"tool_call_id": tool_call_id, "tool_name": name},
                        )
                    llm_messages.append(LlmChatMessage(role="user", content=observation, metadata={}))

            # 完成
            if self._context_manager and hasattr(self._context_manager, "on_turn_end"):
                self._context_manager.on_turn_end(session_id)

            yield {"type": "done", "session_id": session_id, "request_id": request_id}

        except Exception as e:
            yield {"type": "error", "error": str(e)}

    def run(
        self,
        *,
        session_id: str,
        user_input: str,
        model_name: str | None = None,
        record_user_message: bool = True,
    ) -> dict[str, Any]:
        """同步阻塞版：处理单轮用户输入。

        与 stream() 逻辑相同，但以同步方式一次性返回结果。
        适用于非 SSE 场景（如单元测试或批量处理）。

        Args:
            session_id: 会话 ID。
            user_input: 用户输入文本。
            model_name: 指定模型名称（None 则使用默认）。
            record_user_message: 是否将 user 消息写入 context_manager。

        Returns:
            dict: 包含 request_id、session_id、最终 content 和 tool_trace。
        """
        request_id = self._model_manager.new_request_id()
        tool_trace: list[dict[str, Any]] = []
        try:
            if record_user_message:
                self._context_manager.add_message(
                    session_id=session_id, role="user", content=user_input, metadata={"request_id": request_id}
                )

            llm_messages = self.build_turn_llm_messages(session_id=session_id)
            tool_specs = self._tool_registry.list_specs()

            final_content = ""

            step_iter = (
                range(self._max_steps) if self._max_steps is not None else itertools.count()
            )
            for step in step_iter:
                req = ChatRequest(
                    messages=llm_messages,
                    metadata={"request_id": request_id, "session_id": session_id},
                )
                resp = self._model_manager.call_chat(req, model_name=model_name)
                response_text = resp.content or ""

                # 记录 assistant 消息
                self._context_manager.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=response_text,
                    metadata={"request_id": request_id},
                )
                llm_messages.append(LlmChatMessage(role="assistant", content=response_text, metadata={}))

                # 解析工具调用
                tool_calls = self._parse_tool_calls(response_text)

                if not tool_calls:
                    final_content = response_text
                    break

                # 执行工具
                for call in tool_calls:
                    name = call.get("name", "")
                    args = call.get("arguments", {})
                    tool_call_id = call.get("id", f"main_{step}_{len(tool_trace)}")

                    if not self._is_valid_tool(name, args, tool_specs):
                        err_obs = (
                            f"[TOOL_RESULT: {name}]\n"
                            f"执行失败：工具名不在可用列表或参数不是 JSON 对象。\n"
                            f"请使用系统提示中列出的工具名，并以 `{{\"action\": \"...\", \"action_input\": {{...}}}}` 形式调用。"
                        )
                        self._context_manager.add_message(
                            session_id=session_id,
                            role="user",
                            content=err_obs,
                            metadata={"tool_call_id": tool_call_id, "type": "observation_error"},
                        )
                        llm_messages.append(LlmChatMessage(role="user", content=err_obs, metadata={}))
                        continue

                    result: ToolResult = self._tool_registry.invoke(name, args, request_id=request_id)
                    tool_trace.append({
                        "tool_call_id": tool_call_id,
                        "name": name,
                        "arguments": args,
                        "result": asdict(result),
                    })

                    observation = self._format_observation(name, args, result)
                    self._context_manager.add_message(
                        session_id=session_id,
                        role="user",
                        content=observation,
                        metadata={"tool_call_id": tool_call_id, "tool_name": name},
                    )
                    llm_messages.append(LlmChatMessage(role="user", content=observation, metadata={}))

            return {
                "request_id": request_id,
                "session_id": session_id,
                "content": final_content,
                "tool_trace": tool_trace,
            }
        except Exception as e:
            return {
                "request_id": request_id,
                "session_id": session_id,
                "content": "",
                "tool_trace": tool_trace,
                "error": str(e),
            }
