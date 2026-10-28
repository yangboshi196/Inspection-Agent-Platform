"""用户诉求意图识别：提取明确点名的区域、算法、设备。"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from agent_base.llm.errors import LLMError
from agent_base.llm.types import ChatRequest, LlmChatMessage
from agent_base.model_manager.manager import ModelManager
from agent_base.prompts import load_prompt

_INTENT_PROMPT = load_prompt("inspection_work/intent_extract.txt")


def _repair_json_text(s: str) -> str:
    t = s.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    t = re.sub(r",\s*]", "]", t)
    t = re.sub(r",\s*}", "}", t)
    return t


def _parse_json_object(content: str) -> dict[str, Any]:
    s = (content or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.IGNORECASE)
    if m:
        s = m.group(1).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("意图识别输出中未找到 JSON 对象")
    blob = s[start : end + 1]
    for cand in (blob, _repair_json_text(blob)):
        try:
            val = json.loads(cand)
            if isinstance(val, dict):
                return val
        except json.JSONDecodeError:
            continue
    raise ValueError("意图识别 JSON 无法解析")


def extract_user_intent(
    mm: ModelManager,
    *,
    topic: str,
    model_name: str | None = None,
) -> dict[str, Any]:
    """返回 { regions: [], algorithms: [], devices: [] }；失败时返回空结构。"""
    req = ChatRequest(
        messages=[
            LlmChatMessage(role="system", content=_INTENT_PROMPT, metadata={}),
            LlmChatMessage(role="user", content=f"用户描述：\n{topic.strip()}", metadata={}),
        ],
        metadata={"request_id": uuid.uuid4().hex, "purpose": "inspection_work_intent"},
        temperature=0.0,
        max_output_tokens=1024,
    )
    try:
        resp = mm.call_chat(req, model_name=model_name)
        data = _parse_json_object(resp.content or "")
    except (LLMError, ValueError, json.JSONDecodeError):
        return {"regions": [], "algorithms": [], "devices": []}

    out: dict[str, Any] = {"regions": [], "algorithms": [], "devices": []}
    for key in out:
        raw = data.get(key)
        if not isinstance(raw, list):
            continue
        cleaned: list[dict[str, str]] = []
        for el in raw:
            if not isinstance(el, dict):
                continue
            cleaned.append(
                {
                    "id": str(el.get("id") or "").strip(),
                    "name": str(el.get("name") or "").strip(),
                }
            )
        out[key] = cleaned
    return out
