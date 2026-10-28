"""简单人工规则分块：优先按空行分段，再按句号切分，最后按最大字符切分并带重叠。"""

from __future__ import annotations

import re

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s+")


def chunk_text(
    text: str,
    *,
    max_chars: int = 900,
    overlap: int = 120,
) -> list[str]:
    max_chars = max(200, int(max_chars))
    overlap = max(0, min(int(overlap), max_chars // 2))
    t = (text or "").strip()
    if not t:
        return []
    # 优先按空行切段；单段内若含「序号　标题」分项则再按分项切开（一分项一片）
    parts = [p.strip() for p in re.split(r"\n\s*\n+", t) if p.strip()]
    if len(parts) <= 1 and re.search(r"^\d+\u3000", t, re.MULTILINE):
        split_parts: list[str] = []
        buf: list[str] = []
        for ln in t.split("\n"):
            s = ln.strip()
            if not s:
                continue
            if re.match(r"^\d+\u3000", s) and buf:
                split_parts.append("\n".join(buf))
                buf = [s]
            else:
                buf.append(s)
        if buf:
            split_parts.append("\n".join(buf))
        if len(split_parts) > 1:
            parts = split_parts
    if not parts:
        parts = [t]
    h2_parts = [p for p in parts if re.match(r"^\d+\u3000", p.split("\n", 1)[0].strip())]
    if h2_parts:
        intro = [p for p in parts if p not in h2_parts]
        return [p for p in intro + h2_parts if p.strip()]
    out: list[str] = []
    buf = ""
    for p in parts:
        units = _split_sentences(p) if len(p) > max_chars else [p]
        for unit in units:
            if len(buf) + len(unit) + 2 <= max_chars:
                buf = f"{buf}\n\n{unit}" if buf else unit
                continue
            if buf:
                out.extend(_split_hard(buf, max_chars=max_chars, overlap=overlap))
            if len(unit) <= max_chars:
                buf = unit
            else:
                out.extend(_split_hard(unit, max_chars=max_chars, overlap=overlap))
                buf = ""
    if buf.strip():
        out.extend(_split_hard(buf, max_chars=max_chars, overlap=overlap))
    return [x for x in out if x.strip()]


def _split_sentences(paragraph: str) -> list[str]:
    """按中英文句号、分号边界切分，保留标点。"""
    p = paragraph.strip()
    if not p:
        return []
    pieces = [x.strip() for x in _SENTENCE_SPLIT_RE.split(p) if x.strip()]
    if not pieces:
        return [p]
    merged: list[str] = []
    buf = ""
    for piece in pieces:
        if not buf:
            buf = piece
            continue
        if len(buf) + 1 + len(piece) <= 400:
            buf = f"{buf} {piece}"
        else:
            merged.append(buf)
            buf = piece
    if buf:
        merged.append(buf)
    return merged


def _split_hard(s: str, *, max_chars: int, overlap: int) -> list[str]:
    s = s.strip()
    if not s:
        return []
    if len(s) <= max_chars:
        return [s]
    chunks: list[str] = []
    start = 0
    while start < len(s):
        end = min(len(s), start + max_chars)
        piece = s[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(s):
            break
        start = max(0, end - overlap)
    return chunks
