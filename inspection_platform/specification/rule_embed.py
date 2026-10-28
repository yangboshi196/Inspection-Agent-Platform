"""规范规则发布向量的索引文本构建。"""

from __future__ import annotations

from typing import Any

RULE_EMBED_MAX_CHARS = 1800
REQUIREMENTS_PREVIEW_MAX = 500


def requirements_preview(text: str, *, max_chars: int = REQUIREMENTS_PREVIEW_MAX) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1] + "…"


def build_rule_embed_text(rec: dict[str, Any], *, max_chars: int = RULE_EMBED_MAX_CHARS) -> str:
    """
    发布向量索引串：name + desc + requirements 固定模板。
    超长时优先保留标题与场景，截断 requirements 尾部。
    """
    name = (rec.get("name") or "").strip()
    desc = (rec.get("desc") or "").strip()
    req = (rec.get("requirements") or "").strip()

    head: list[str] = []
    if name:
        head.append(f"【{name}】")
    if desc:
        head.append(f"适用场景：{desc}")

    head_text = "\n".join(head)
    if not req:
        if len(head_text) <= max_chars:
            return head_text
        return head_text[: max_chars - 1] + "…"

    req_label = "可执行要求："
    sep = "\n" if head_text else ""
    prefix = f"{head_text}{sep}{req_label}" if head_text else req_label
    budget = max_chars - len(prefix)
    if budget < 1:
        if head_text and len(head_text) <= max_chars:
            return head_text
        fallback = head_text or req_label
        return fallback[: max_chars - 1] + "…"

    req_part = req if len(req) <= budget else req[: budget - 1] + "…"
    return prefix + req_part
