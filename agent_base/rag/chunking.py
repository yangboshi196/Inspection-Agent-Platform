"""
SIA_agent.rag.chunking - 文档分块策略

提供多种文本切分策略：
- chunk_text / fixed：固定窗口切分（核心算法）
- paragraph：按段落切分（语义友好，按 chunk_size 合并）
- vision_paragraph：多模态富化后的段落切分（本模块不处理，由 KnowledgeBase 调度）

适用场景：
- RAG 建索引前的文本预处理
- 长文档上下文窗口压缩
"""

from __future__ import annotations


def chunk_text(text: str, *, chunk_size: int = 1000, chunk_overlap: int = 150) -> list[str]:
    """
    按固定窗口与重叠长度将长文本切成多条子串，供 RAG 建索引。

    空串返回 `[]`；`chunk_overlap` 会被限制在合法范围内以避免死循环。
    """
    t = (text or "").strip()
    if not t:
        return []
    chunk_size = max(1, int(chunk_size))
    chunk_overlap = max(0, min(int(chunk_overlap), chunk_size - 1))
    chunks: list[str] = []
    start = 0
    while start < len(t):
        end = min(len(t), start + chunk_size)
        chunk = t[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(t):
            break
        start = max(0, end - chunk_overlap)
    return chunks


def chunk_text_by_strategy(
    text: str,
    *,
    strategy: str = "fixed",
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
) -> list[str]:
    """
    分割策略抽象：

    - fixed: 固定窗口（等价于 `chunk_text`）
    - paragraph: 先按空行分段，再按 chunk_size 合并为块（更“语义段落友好”）
    - vision_paragraph: 在 `KnowledgeBase.ingest_file` 中先做多模态识图与正文融合，再按 paragraph 分块（此处不会收到该值）
    """
    s = (strategy or "fixed").strip().lower()
    # 若误把入库策略传到分块层，按 paragraph 处理（与 `KnowledgeBase.ingest_file` 一致）
    if s == "vision_paragraph":
        s = "paragraph"
    if s in ("fixed", "window", "sliding"):
        return chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    if s in ("paragraph", "para"):
        t = (text or "").strip()
        if not t:
            return []
        chunk_size = max(1, int(chunk_size))
        paras = [p.strip() for p in t.split("\n\n") if p.strip()]
        if not paras:
            return []
        out: list[str] = []
        buf = ""
        for p in paras:
            if not buf:
                buf = p
                continue
            # +2 for the blank line separator
            if len(buf) + 2 + len(p) <= chunk_size:
                buf = f"{buf}\n\n{p}"
            else:
                out.append(buf)
                buf = p
        if buf:
            out.append(buf)
        # paragraph 策略不做 overlap（避免重复段落），如需可后续扩展
        return out

    # fallback: unknown strategy -> fixed
    return chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

