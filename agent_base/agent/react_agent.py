"""
ReAct Agent - 标准 ReAct 推理 + 工具调用循环

设计原则（用户指定）：
1. 分析任务：理解用户想做什么
2. 思考需要用什么工具
3. 调用工具，接受结果
4. 分析现状，思考是继续调用工具还是总结
5. 循环直到 Agent 认为任务完成

事件类型：
- reasoning_start / reasoning_end：一轮模型输出边界（便于前端分块展示流水线）
- thinking_delta：推理文本增量（带 step，与 reasoning_start 对齐）
- tool_start：工具开始调用
- tool_end：工具执行结束
- delta：最终回答文本增量
- done：完成
"""

from __future__ import annotations

import concurrent.futures
import itertools
import json
import re
import threading
import time
from typing import Any, Generator, Iterator

from ..context import ContextManagerBase, format_memory_for_prompt
from ..llm.types import ChatRequest, LlmChatMessage, to_llm_chat_message
from ..tools.types import ToolError, ToolResult
from .base_agent import BaseAgent


class ReActAgent(BaseAgent):
    """标准 ReAct（Reasoning + Acting）推理链路 Agent。

    推理模式：Thought → Action → Observation → Thought → ... → Final Answer

    Attributes:
        context: 当前绑定的上下文管理器。

    SSE 事件类型：
        reasoning_start / reasoning_end : 一轮推理边界（便于前端分块展示流水线）
        thinking_delta                 : 推理文本增量
        tool_start / tool_end           : 工具调用边界
        delta                            : 最终回答文本增量
        done                             : 完成
        error                            : 错误

    与 SimpleAgent 的区别：
        - SimpleAgent：无推理过程，适合简单问答
        - ReActAgent：标准 ReAct 循环，适合需要多步推理的复杂任务
    """

    # ReAct 输出的关键标记（支持 Markdown 加粗格式）
    PATTERN_ACTION = re.compile(r"\*?\*?Action\*?\*?[:：]\s*(\w+)", re.IGNORECASE)
    PATTERN_ACTION_INPUT = re.compile(
        r"\*?\*?Action\s*Input\*?\*?[:：]\s*(\{[^}]+\}|\[.+?\]|.+?)(?=\n|$)",
        re.DOTALL | re.IGNORECASE
    )
    PATTERN_FINAL = re.compile(r"(?:Final\s*Answer|最终回答|结论)[:：]\s*(.+)", re.DOTALL | re.IGNORECASE)

    def _default_prompt_path(self) -> str:
        return "agent/react_agent_default.txt"

    @staticmethod
    def _agent_prefix() -> str:
        return "react"

    @property
    def context(self) -> ContextManagerBase:
        """当前 Agent 绑定的上下文管理器（可读写消息）。"""
        return self._context_manager

    def stream(
        self,
        *,
        session_id: str,
        user_input: str,
        model_name: str | None = None,
        images: list[str] | None = None,
        record_user_message: bool = True,
    ) -> Generator[dict[str, Any], None, None]:
        """执行 ReAct 推理循环的核心方法。

        流程：
        1. 若有图片：将路径写入系统提示词，由模型自行调用 image_recognize 等工具
        2. 构建 system prompt + 初始消息
        3. ReAct 循环（调用 chat 接口）：
           - 模型输出 thinking + 工具调用
           - 执行工具 → 注入结果 → 继续循环
           - 无工具调用 → 输出 Final Answer → 结束

        Args:
            session_id: 会话唯一标识符，用于上下文管理和历史追踪。
            user_input: 用户的原始输入文本。
            model_name: 可选的指定模型名称，不提供时使用默认模型。
            images: 可选的图片路径列表，用于多模态推理场景。
            record_user_message: 是否将用户消息持久化到上下文管理器，默认 True。

        Yields:
            dict[str, Any]: SSE 事件流，包含以下事件类型：
            - reasoning_start / reasoning_end: 推理边界
            - thinking_delta: 推理文本增量
            - tool_start / tool_end: 工具调用边界
            - delta: 最终回答文本增量
            - done: 完成
            - error: 错误（如有）

        Raises:
            LLMError: LLM 调用失败时。
            ToolError: 工具执行失败超过重试次数时。
        """
        request_id = self._model_manager.new_request_id()

        # 1) 持久化用户消息
        if record_user_message and self._context_manager:
            metadata = {"request_id": request_id}
            if images:
                metadata["images"] = images
            self._context_manager.add_message(
                session_id=session_id,
                role="user",
                content=user_input,
                metadata=metadata,
            )

        # 2) 获取工具列表并构建系统提示词
        tool_specs = self._tool_registry.list_specs()
        tools_description = self._format_tools_for_prompt(tool_specs)
        system_prompt = self._system_prompt.replace("{{available_tools}}", tools_description)

        # 限制 system prompt 长度
        if len(system_prompt) > 50000:
            system_prompt = system_prompt[:50000] + "\n\n[工具列表过长，已部分截断]"

        # 3) 如果有图片，传递路径信息到系统提示词中
        if images:
            image_paths = "\n".join([f"- {p}" for p in images])
            system_prompt = system_prompt.replace("{image_paths}", image_paths)
        else:
            system_prompt = system_prompt.replace("{image_paths}", "（无）")
        initial_context = user_input

        # 本轮结束后写入 context 的 assistant 正文：仅保存面向用户的最终回答（不含多步推理与工具 JSON）
        final_user_text = ""

        # 4) 从上下文管理器读取历史消息（支持摘要压缩）
        messages: list[LlmChatMessage] = [
            LlmChatMessage(role="system", content=system_prompt, metadata={}),
        ]
        # 注入摘要（如有）
        if self._context_manager:
            hist, imp = self._context_manager.get_summaries(session_id)
            mem_txt = format_memory_for_prompt(hist, imp)
            if mem_txt.strip():
                messages.append(
                    LlmChatMessage(role="system", content=mem_txt, metadata={"kind": "memory_injection"})
                )
            # 获取历史窗口
            history = self._context_manager.get_window(session_id, last_n=self._window_last_n)
            for m in history:
                messages.append(to_llm_chat_message(m))
            # get_window 已包含当前轮用户消息（由 step 1 持久化），不再重复添加
        else:
            # 无 context_manager 时兜底添加
            messages.append(LlmChatMessage(role="user", content=initial_context, metadata={}))

        # 5) ReAct 主循环（max_steps 为 None 时不限制步数）
        answered = False
        step_iter = (
            range(self._max_steps) if self._max_steps is not None else itertools.count()
        )
        for step in step_iter:
            rs: dict[str, Any] = {"type": "reasoning_start", "step": step}
            if self._stream_reasoning_agent:
                rs["agent"] = self._stream_reasoning_agent
            yield rs

            # 调用 chat 模型（纯文本）：边收 token 边推给前端
            response_text = ""
            try:
                for delta in self._iter_chat_stream_text(
                    messages=messages,
                    model_name=model_name,
                    request_id=request_id,
                    session_id=session_id,
                ):
                    response_text += delta
                    if delta:
                        yield {"type": "thinking_delta", "step": step, "text": delta}
            except NotImplementedError:
                # 不支持流式，降级为整段
                chat_req = ChatRequest(
                    messages=messages,
                    metadata={"request_id": request_id, "session_id": session_id},
                )
                resp = self._model_manager.call_chat(chat_req, model_name=model_name)
                response_text = resp.content or ""
                if response_text:
                    yield {"type": "thinking_delta", "step": step, "text": response_text}

            re_end: dict[str, Any] = {"type": "reasoning_end", "step": step}
            if self._stream_reasoning_agent:
                re_end["agent"] = self._stream_reasoning_agent
            yield re_end

            # 6) 解析工具调用（带解析失败重试机制）
            tool_calls = self._parse_tool_calls(response_text)
            parse_retry_count = 0
            max_parse_retries = 3  # 解析失败最多重试次数

            while parse_retry_count < max_parse_retries:
                if tool_calls:
                    break  # 解析成功

                # 解析失败，注入错误提示让模型重试
                parse_retry_count += 1
                remaining = max_parse_retries - parse_retry_count

                if remaining > 0:
                    ex1 = '{"tool_call": {"name": "calculator", "arguments": {"expr": "1+1"}}}'
                    ex2 = '{"expr": "1+1"}'
                    ex3 = '{"name": "calculator", "arguments": {"expr": "1+1"}}'
                    err_obs = (
                        f"[TOOL_RESULT: PARSE_ERROR]\n"
                        f"无法从上一段输出中解析出工具调用。\n"
                        f"剩余重试次数：{remaining}。\n"
                        "请**仅**输出下列**之一**（不要混在长推理中）：\n"
                        f"1) json 代码块内单行：{ex1}\n"
                        f"2) ReAct：Action: calculator 换行 Action Input: {ex2}\n"
                        f"3) OpenAI 风格：{ex3}\n"
                        "参数须为合法 JSON；Thought 后可接其中一种格式。"
                    )
                else:
                    # 达到最大重试次数，告知用户并终止
                    final_answer = self._extract_final_answer(response_text)
                    answer = final_answer if final_answer else response_text
                    final_user_text = (
                        f"抱歉，无法识别工具调用格式（连续 {max_parse_retries} 次解析失败）。\n"
                        "请将调用单独放在 json 代码块中，或使用 "
                        "「Action: 工具名」另起一行「Action Input: {JSON参数}」。\n"
                        "示例（整段仅含此代码块）：\n```json\n"
                        '{"tool_call":{"name":"calculator","arguments":{"expr":"1+1"}}}\n'
                        "```"
                    )
                    yield {"type": "delta", "text": final_user_text}
                    answered = True
                    break

                messages.append(
                    LlmChatMessage(
                        role="assistant",
                        content=response_text,
                        metadata={"step": step, "phase": "tool_calls_attempt"},
                    )
                )
                # 持久化到 context（与 SimpleAgent 保持一致）
                if self._context_manager:
                    self._context_manager.add_message(
                        session_id=session_id,
                        role="assistant",
                        content=response_text,
                        metadata={"step": step, "phase": "tool_calls_attempt", "request_id": request_id},
                    )
                messages.append(
                    LlmChatMessage(
                        role="user",
                        content=err_obs,
                        metadata={"type": "parse_error_retry"},
                    )
                )
                if self._context_manager:
                    self._context_manager.add_message(
                        session_id=session_id,
                        role="user",
                        content=err_obs,
                        metadata={"type": "parse_error_retry", "request_id": request_id},
                    )

                # 重新调用模型获取修正后的输出
                response_text = ""
                try:
                    for delta in self._iter_chat_stream_text(
                        messages=messages,
                        model_name=model_name,
                        request_id=request_id,
                        session_id=session_id,
                    ):
                        response_text += delta
                        if delta:
                            yield {"type": "thinking_delta", "step": step, "text": delta}
                except NotImplementedError:
                    chat_req = ChatRequest(
                        messages=messages,
                        metadata={"request_id": request_id, "session_id": session_id},
                    )
                    resp = self._model_manager.call_chat(chat_req, model_name=model_name)
                    response_text = resp.content or ""
                    if response_text:
                        yield {"type": "thinking_delta", "step": step, "text": response_text}

                # 重新解析
                tool_calls = self._parse_tool_calls(response_text)

            # 如果解析成功或未达到重试上限，继续执行
            if not answered and not tool_calls:
                # 最终兜底：仍然没有工具调用，输出文本内容
                final_answer = self._extract_final_answer(response_text)
                answer = final_answer if final_answer else response_text
                final_user_text = answer
                yield {"type": "delta", "text": answer}
                answered = True
                break

            if not tool_calls:
                continue  # answered=True 时会 break，这里是兜底

            # 7) 执行工具调用：本步模型输出只追加一次 assistant，避免多工具时重复同一段输出
            messages.append(
                LlmChatMessage(
                    role="assistant",
                    content=response_text,
                    metadata={"step": step, "phase": "tool_calls"},
                )
            )
            # 持久化到 context（与 SimpleAgent 保持一致）
            if self._context_manager:
                self._context_manager.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=response_text,
                    metadata={"step": step, "phase": "tool_calls", "request_id": request_id},
                )

            # 单次工具调用重试追踪（按 tool_call_id，不按工具名聚合）
            tool_attempts: dict[str, int] = {}
            max_tool_retries = 3  # 同一次调用 id 的最大失败/无效尝试次数

            for call in tool_calls:
                name = call.get("name", "")
                args = call.get("arguments", {})
                tool_call_id = call.get("id", f"call_{step}_{int(time.time() * 1000)}")

                if not self._is_valid_tool(name, args, tool_specs):
                    tool_attempts[tool_call_id] = tool_attempts.get(tool_call_id, 0) + 1
                    n = tool_attempts[tool_call_id]
                    err_obs = (
                        f"[TOOL_RESULT: {name}]\n"
                        f"执行失败：工具名不在可用列表或参数格式错误。\n"
                        f"剩余重试次数：{max_tool_retries - n}。\n"
                        f"请使用系统提示中列出的工具名，并以 JSON 形式调用。"
                    )
                    messages.append(
                        LlmChatMessage(
                            role="user",
                            content=err_obs,
                            metadata={"tool_call_id": tool_call_id, "type": "observation_error"},
                        )
                    )
                    # 持久化到 context（与 SimpleAgent 保持一致）
                    if self._context_manager:
                        self._context_manager.add_message(
                            session_id=session_id,
                            role="user",
                            content=err_obs,
                            metadata={
                                "tool_call_id": tool_call_id,
                                "tool_name": name,
                                "type": "observation_error",
                                "request_id": request_id,
                            },
                        )
                    if n >= max_tool_retries:
                        final_user_text = (
                            f"抱歉，本次工具调用（{name}）已连续失败 {n} 次，"
                            "可能是任务超出当前能力范围，建议简化问题或分步提问。"
                        )
                        yield {"type": "delta", "text": final_user_text}
                        answered = True
                        break
                    continue

                # 面向用户：SSE 仅暴露友好状态，不携带参数与原始返回
                tool_evt: dict[str, Any] = {
                    "name": name,
                    "label": self._tool_user_label(name),
                    "tool_call_id": tool_call_id,
                    "request_id": request_id,
                }
                agent_meta = self._sse_tool_agent_meta(name)
                if agent_meta is not None:
                    tool_evt["agent"] = agent_meta
                if self._tool_start_card is not None:
                    start_c = self._tool_start_card(
                        name,
                        args,
                        tool_call_id=tool_call_id,
                        request_id=request_id,
                    )
                    if start_c is not None:
                        tool_evt["card"] = start_c
                yield {"type": "tool_start", "tool": tool_evt}

                result = self._tool_registry.invoke(name, args, request_id=request_id)

                end_tool: dict[str, Any] = {
                    "name": name,
                    "label": self._tool_user_label(name),
                    "tool_call_id": tool_call_id,
                    "request_id": request_id,
                    "ok": result.ok,
                }
                if agent_meta is not None:
                    end_tool["agent"] = agent_meta
                end_payload: dict[str, Any] = {
                    "type": "tool_end",
                    "tool": end_tool,
                }
                if self._tool_stream_card is not None:
                    card = self._tool_stream_card(name, result)
                    if card is not None:
                        end_payload["card"] = card
                yield end_payload

                # 工具执行失败时的重试逻辑（仅针对本 tool_call_id）
                if not result.ok:
                    tool_attempts[tool_call_id] = tool_attempts.get(tool_call_id, 0) + 1
                    fail_n = tool_attempts[tool_call_id]
                    error_msg = result.error.message if result.error else "未知错误"
                    remaining = max_tool_retries - fail_n

                    if remaining > 0:
                        err_obs = (
                            f"[TOOL_RESULT: {name}]\n"
                            f"执行失败：{error_msg}\n"
                            f"剩余重试次数：{remaining}。\n"
                            f"请检查参数后重新调用。"
                        )
                    else:
                        err_obs = (
                            f"[TOOL_RESULT: {name}]\n"
                            f"执行失败（{fail_n} 次）：{error_msg}\n"
                            f"已达到最大重试次数，无法继续。"
                        )

                    messages.append(
                        LlmChatMessage(
                            role="user",
                            content=err_obs,
                            metadata={"tool_call_id": tool_call_id, "type": "observation_error"},
                        )
                    )

                    if remaining <= 0:
                        final_user_text = (
                            f"抱歉，本次工具调用（{name}）已连续执行失败 {fail_n} 次：{error_msg}\n"
                            "建议您检查输入参数或简化请求。"
                        )
                        yield {"type": "delta", "text": final_user_text}
                        answered = True
                        break
                    continue

                # 成功：清除本调用的尝试计数（不影响其它 tool_call_id）
                tool_attempts.pop(tool_call_id, None)

                # 8) 将观察结果注入消息列表，准备下一轮
                observation = self._format_observation(name, args, result)

                messages.append(LlmChatMessage(
                    role="user",
                    content=observation,
                    metadata={"tool_call_id": tool_call_id, "type": "observation"},
                ))
                # 持久化到 context（与 SimpleAgent 保持一致）
                if self._context_manager:
                    self._context_manager.add_message(
                        session_id=session_id,
                        role="user",
                        content=observation,
                        metadata={
                            "tool_call_id": tool_call_id,
                            "tool_name": name,
                            "type": "observation",
                            "request_id": request_id,
                        },
                    )

            if answered:
                break

        if not answered and self._max_steps is not None:
            final_user_text = (
                f"已达到最大推理步数（{self._max_steps}），请简化任务或分步提问。"
            )
            yield {"type": "delta", "text": final_user_text}

        # 9) 记录到上下文（与 SSE 最终回答一致，便于多轮窗口保持简洁）
        if self._context_manager:
            self._context_manager.add_message(
                session_id=session_id,
                role="assistant",
                content=final_user_text,
                metadata={"request_id": request_id, "kind": "react_final_answer"},
            )
            self._context_manager.on_turn_end(session_id)

        yield {
            "type": "done",
            "session_id": session_id,
            "request_id": request_id,
            "model_name": model_name,
        }

    # ── ReAct 特有方法 ─────────────────────────────────

    def _iter_chat_stream_text(
        self,
        messages: list[LlmChatMessage],
        model_name: str | None,
        request_id: str,
        session_id: str,
    ) -> Iterator[str]:
        """流式拉取 chat 文本增量。

        首个 token 带有自适应超时保护（3~30s，根据历史消息长度计算），
        若超时则抛 NotImplementedError，由调用方降级为非流式调用。

        Args:
            messages: LLM 消息列表。
            model_name: 指定模型名称。
            request_id: 本次请求 ID（用于日志追踪）。
            session_id: 会话 ID。

        Yields:
            str: 模型输出的文本增量（token 粒度）。

        Raises:
            NotImplementedError: 流式调用超时或不可用时。
        """
        chat_req = ChatRequest(
            messages=messages,
            metadata={"request_id": request_id, "session_id": session_id},
        )

        total_chars = sum(len(str(m.content or "")) for m in messages)
        first_timeout = max(3.0, min(30.0, 3.0 + (total_chars / 4000.0) * 1.2))
        # 首个 token 之后若流长期无增量，也会卡死整段 SSE；对每一块都加超时
        chunk_timeout = max(first_timeout, 75.0)

        class _StreamEnd:
            pass

        _END = _StreamEnd()

        try:
            it: Iterator = self._model_manager.call_chat_stream(chat_req, model_name=model_name)
        except NotImplementedError:
            raise

        def _read_one(box: list[Any]) -> None:
            try:
                n = next(it)
            except StopIteration:
                box.append(("end", None))
            except BaseException as e:
                box.append(("exc", e))
            else:
                box.append(("chunk", str(n) if n else ""))

        while True:
            box: list[Any] = []
            th = threading.Thread(target=_read_one, args=(box,), daemon=True)
            th.start()
            th.join(timeout=chunk_timeout)
            if th.is_alive():
                # 不等待阻塞中的 next(it) 结束，避免占满线程池导致后续死锁
                raise NotImplementedError("stream stalled")
            if len(box) != 1:
                raise NotImplementedError("stream stalled")
            kind, payload = box[0]
            if kind == "exc":
                raise payload
            if kind == "end":
                break
            if kind == "chunk" and payload:
                yield payload

    def _tool_user_label(self, tool_name: str) -> str:
        """返回面向用户的工具阶段友好说明。

        优先取 ToolSpec.display_name，未配置时默认返回"处理中"。

        Args:
            tool_name: 工具名称。

        Returns:
            str: 面向用户展示的阶段标签。
        """
        tool = self._tool_registry.get(tool_name)
        if tool is not None:
            dn = tool.spec.display_name
            if isinstance(dn, str) and dn.strip():
                return dn.strip()
        return "处理中"

    def _extract_final_answer(self, text: str) -> str | None:
        """从模型输出文本中提取 Final Answer 标记后的内容。

        支持正则：``(?:Final\\s*Answer|最终回答|结论)[:：]\\s*(.+)``

        Args:
            text: LLM 输出的原始文本。

        Returns:
            str | None: Final Answer 后的内容（去除首尾空白），无匹配时返回 None。
        """
        match = self.PATTERN_FINAL.search(text)
        return match.group(1).strip() if match else None

    def _parse_tool_calls_natural_language(self, text: str) -> list[dict[str, Any]]:
        """ReAct：Action + Action Input（支持嵌套 JSON）；否则回退基类松散中文匹配。"""
        react_calls = self._parse_react_action_with_balanced_json(text)
        if react_calls:
            return react_calls
        return super()._parse_tool_calls_natural_language(text)

    def _parse_react_action_with_balanced_json(self, text: str) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        for i, match in enumerate(self.PATTERN_ACTION.finditer(text)):
            tool_name = match.group(1).strip()
            if not tool_name:
                continue
            arguments: dict[str, Any] = {}
            tail = text[match.end() :]
            aim = re.search(
                r"(?:Action\s*Input|action_input|参数)\s*[:：]\s*",
                tail,
                re.IGNORECASE | re.DOTALL,
            )
            if aim:
                abs_after_label = match.end() + aim.end()
                rest = text[abs_after_label:]
                stripped = rest.lstrip()
                offset = len(rest) - len(stripped)
                jstart = abs_after_label + offset
                if jstart < len(text) and text[jstart] == "{":
                    raw = self._slice_balanced_json_object(text, jstart)
                    if raw:
                        try:
                            parsed = json.loads(raw)
                            if isinstance(parsed, dict):
                                arguments = parsed
                        except json.JSONDecodeError:
                            arguments = self._parse_key_value_args(raw)
            calls.append({
                "name": tool_name,
                "arguments": arguments if isinstance(arguments, dict) else {},
                "id": f"{self._agent_prefix()}_nl_{i}",
            })
        return calls

    def _format_rag_observation_for_llm(self, tool_name: str, args: dict, result: ToolResult) -> str:
        """RAG 工具专用观察格式化：尽量简短，避免原文抄进推理。

        将检索到的 chunks 压缩为带相似度评分的摘录，
        每条截取前 400 字符，总长度控制在 2800 字符以内。

        提示 LLM 先归纳要点、在最终回答中按需引用来源，
        而不是逐段复述检索原文。

        Args:
            tool_name: 工具名称（以 rag_search_ 开头）。
            args: 调用参数（含 query）。
            result: 工具执行结果（含 contexts）。

        Returns:
            str: 格式化的 RAG 观察文本。
        """
        data = result.data if isinstance(result.data, dict) else {}
        contexts = data.get("contexts") if isinstance(data.get("contexts"), list) else []
        q = (args.get("query") if isinstance(args.get("query"), str) else "") or str(data.get("query") or "")
        lines: list[str] = [
            f"[TOOL_RESULT: {tool_name}]",
            f"检索查询：{q.strip()}",
            "",
            "以下为相似度达阈值后的摘录（不要在推理里逐段复述；先归纳要点，最终回答中再按需引用来源）：",
            "",
        ]
        budget = 2800
        used = sum(len(x) + 1 for x in lines)
        for i, ctx in enumerate(contexts, 1):
            if not isinstance(ctx, dict):
                continue
            text = str(ctx.get("text") or "").strip()
            excerpt = (text[:400] + "…") if len(text) > 400 else text
            score_v = ctx.get("score")
            score_s = f"{float(score_v):.3f}" if isinstance(score_v, (int, float)) else "?"
            src = ctx.get("source") if isinstance(ctx.get("source"), dict) else {}
            doc = str(src.get("doc_name") or "").strip()
            chunk = f"[{i}] 相似度≈{score_s} 来源《{doc or '未知文档'}》\n{excerpt}\n"
            if used + len(chunk) > budget:
                lines.append(f"\n[其余 {max(0, len(contexts) - i + 1)} 条已省略以控制长度]")
                break
            lines.append(chunk)
            used += len(chunk) + 1
        lines.append(
            "\n请据摘录继续推理；面向用户的最终回答应清晰概括，不要堆砌检索原文。"
        )
        return "\n".join(lines)

    def _format_observation(self, tool_name: str, args: dict, result: ToolResult) -> str:
        """格式化工具结果。

        RAG 工具（tool_name 以 ``rag_search_`` 开头）使用特殊简短格式
        （_format_rag_observation_for_llm），其余工具走父类默认格式。

        Args:
            tool_name: 工具名称。
            args: 调用参数。
            result: 工具执行结果。

        Returns:
            str: 格式化的观察文本，用于注入 LLM 消息列表。
        """
        if tool_name.startswith("rag_search_"):
            if result.ok:
                return self._format_rag_observation_for_llm(tool_name, args, result)
            err = (result.error.message if result.error else "") or "unknown"
            return (
                f"[TOOL_RESULT: {tool_name}]\n检索失败：{err}\n"
                f"请尝试改写 query 或调整检索条件后再调用工具。"
            )

        return super()._format_observation(tool_name, args, result)
