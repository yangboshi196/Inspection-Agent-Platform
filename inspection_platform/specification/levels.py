"""重要等级：关键词 + 来源简单规则。"""

from __future__ import annotations


def infer_level(*, name: str, desc: str, requirements: str, source: str) -> str:
    blob = f"{name}\n{desc}\n{requirements}\n{source}"
    if any(
        k in blob
        for k in ("严禁", "禁止", "顶格", "追究刑事责任", "重大事故", "停产停业")
    ):
        return "top"
    if source.startswith("national") or "处罚" in blob or "吊销" in blob:
        return "important"
    return "common"
