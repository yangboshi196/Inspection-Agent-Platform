"""知识库文本治理：清洗、脱敏、去噪（入库前）。"""

from __future__ import annotations

import re

# 常见页眉页脚 / 目录噪声
_NOISE_PATTERNS = (
    re.compile(r"^\s*第\s*\d+\s*页\s*(共\s*\d+\s*页)?\s*$", re.MULTILINE),
    re.compile(r"^\s*[-—]\s*\d+\s*[-—]\s*$", re.MULTILINE),
    re.compile(r"^\s*目\s*录\s*$", re.MULTILINE),
)

# 脱敏：手机号、身份证、邮箱
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# 连续重复字符 / 控制符
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_REPEAT_RE = re.compile(r"(.)\1{6,}")

# Word Heading2：序号 + 全角空格 + 标题（与「1、」列表区分）
_H2_HEADING_RE = re.compile(r"^(\d+)\u3000(.+)$")

# 行首编号列表项：1、 / 1. / 1．
_LIST_ITEM_LINE_RE = re.compile(r"^(\d+)[、．.](.+)$")

_INLINE_ENUM_RE = re.compile(
    r"(\d+)[、．.](.*?)(?=\s+\d+[、．.]|$)",
    re.DOTALL,
)

_SENTENCE_END = "。！？!?；"

_SKIP_BOILERPLATE = frozenset(
    {
        "评估表摘录（供对照，非逐字法律条文）",
        "生产管理要求（模拟细化，可写入项目细则）",
    }
)

_META_PREFIXES = (
    "情形说明：",
    "情形说明:",
    "检查或控制要求",
    "实施中需事先厘清",
    "现场曾讨论的实施要点",
)


def _strip_item_tail(text: str) -> str:
    return (text or "").strip().rstrip("；;，,")


def _ensure_sentence_end(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return s
    if s[-1] in _SENTENCE_END:
        return s
    return s + "。"


def _clause_body(text: str) -> str:
    return _strip_item_tail(text).rstrip("。！？!?")


def _join_clauses(clauses: list[str]) -> str:
    parts = [_clause_body(c) for c in clauses if _clause_body(c)]
    if not parts:
        return ""
    body = "；".join(parts)
    return _ensure_sentence_end(body)


def _join_numbered_items(items: list[tuple[str, str]], *, delimiter: str = "、") -> str:
    parts: list[str] = []
    for num, body in items:
        body = _strip_item_tail(body)
        if not body:
            continue
        parts.append(f"{num}{delimiter}{body}")
    return "；".join(parts)


def _parse_inline_numbered_list(text: str) -> tuple[str, list[tuple[str, str]]] | None:
    s = (text or "").strip()
    if not s:
        return None

    m = re.search(r"(\d+)[、．.]", s)
    if not m or m.group(1) != "1":
        return None

    prefix = s[: m.start()].rstrip()
    if prefix and not prefix.endswith(("：", ":")):
        if m.start() != 0:
            return None

    rest = s[m.start() :]
    raw_items = [(g[0], g[1]) for g in _INLINE_ENUM_RE.findall(rest)]
    if len(raw_items) < 2:
        return None

    nums = [int(n) for n, _ in raw_items]
    if nums[0] != 1 or nums != list(range(1, len(nums) + 1)):
        return None

    if prefix.endswith(("：", ":")):
        prefix = prefix.rstrip("：:") + "："
    return prefix, raw_items


def _normalize_inline_numbered_list(text: str) -> str:
    parsed = _parse_inline_numbered_list(text)
    if not parsed:
        return text
    prefix, items = parsed
    body = _join_numbered_items(items)
    if not body:
        return text
    merged = f"{prefix}{body}" if prefix else body
    return _ensure_sentence_end(merged)


def _collect_following_list(lines: list[str], start: int) -> tuple[list[str], int] | None:
    if start >= len(lines):
        return None
    m0 = _LIST_ITEM_LINE_RE.match(lines[start])
    if not m0 or m0.group(1) != "1":
        return None

    block = [lines[start]]
    j = start + 1
    expect = 2
    while j < len(lines):
        mj = _LIST_ITEM_LINE_RE.match(lines[j])
        if mj and int(mj.group(1)) == expect:
            block.append(lines[j])
            expect += 1
            j += 1
        else:
            break
    if len(block) < 2:
        return None
    return block, j


def _merge_break_numbered_lists(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]

        if i + 1 < len(lines) and not _LIST_ITEM_LINE_RE.match(ln):
            collected = _collect_following_list(lines, i + 1)
            if collected:
                block, j = collected
                items = [
                    (m.group(1), m.group(2))
                    for b in block
                    if (m := _LIST_ITEM_LINE_RE.match(b))
                ]
                body = _join_numbered_items(items)
                prefix = ln.rstrip()
                if not prefix.endswith(("：", ":")):
                    prefix = prefix + "："
                else:
                    prefix = prefix.rstrip("：:") + "："
                out.append(_ensure_sentence_end(f"{prefix}{body}"))
                i = j
                continue

        collected = _collect_following_list(lines, i)
        if collected:
            block, j = collected
            items = [
                (m.group(1), m.group(2))
                for b in block
                if (m := _LIST_ITEM_LINE_RE.match(b))
            ]
            out.append(_ensure_sentence_end(_join_numbered_items(items)))
            i = j
            continue

        out.append(ln)
        i += 1
    return out


def _split_h2_sections(lines: list[str]) -> list[list[str]]:
    sections: list[list[str]] = []
    current: list[str] = []
    for ln in lines:
        if _H2_HEADING_RE.match(ln):
            if current:
                sections.append(current)
            current = [ln]
        elif ln.strip():
            if current:
                current.append(ln.strip())
            else:
                current = [ln.strip()]
    if current:
        sections.append(current)
    return sections


def _is_meta_line(line: str) -> bool:
    return any(line.startswith(p) for p in _META_PREFIXES)


def _compress_h2_section(lines: list[str]) -> str:
    """
    将单个 Heading2 分项压成 1～2 句，便于一分项一片入库。

    - 有句1：标题 + 评估摘录（情形/检查/问题/讨论）
    - 句2：生产管理要求要点（常见为 2～4 条合并）
    """
    if not lines:
        return ""
    title = lines[0].strip()
    if not _H2_HEADING_RE.match(title):
        return "\n".join(lines)

    meta: list[str] = []
    mgmt: list[str] = []
    after_prod_label = False

    for ln in lines[1:]:
        s = ln.strip()
        if not s or s in _SKIP_BOILERPLATE:
            if s == "生产管理要求（模拟细化，可写入项目细则）":
                after_prod_label = True
            continue
        if _is_meta_line(s):
            meta.append(s)
            after_prod_label = False
            continue
        if after_prod_label or not meta:
            mgmt.append(s)
        else:
            meta.append(s)

    sentences: list[str] = []
    if meta:
        meta_body = "；".join(_clause_body(m) for m in meta)
        sentences.append(_ensure_sentence_end(f"{title}：{meta_body}"))
    elif mgmt:
        if len(mgmt) >= 3:
            lead = "；".join(_clause_body(x) for x in mgmt[:2])
            sentences.append(_ensure_sentence_end(f"{title}：{lead}"))
            sentences.append(_ensure_sentence_end(_clause_body(mgmt[2])))
            tail = mgmt[3:]
            if tail:
                sentences.append(_join_clauses(tail))
        elif len(mgmt) == 2:
            sentences.append(_ensure_sentence_end(f"{title}：{_clause_body(mgmt[0])}"))
            sentences.append(_ensure_sentence_end(_clause_body(mgmt[1])))
        else:
            sentences.append(_ensure_sentence_end(f"{title}：{_clause_body(mgmt[0])}"))
    else:
        return title

    if meta and mgmt:
        if len(mgmt) >= 3:
            sentences.append(_join_clauses(mgmt[:2]))
            sentences.append(_ensure_sentence_end(mgmt[2]))
            if len(mgmt) > 3:
                sentences.append(_join_clauses(mgmt[3:]))
        else:
            sentences.append(_join_clauses(mgmt))

    # 最多保留两句（用户场景：评估句 + 管理句）；多余管理句并入第二句
    if len(sentences) > 2:
        first = sentences[0]
        rest = "；".join(_clause_body(s) for s in sentences[1:])
        return f"{first}\n{_ensure_sentence_end(rest)}"
    return "\n".join(sentences)


def _restructure_h2_sections(lines: list[str]) -> tuple[list[str], bool]:
    """按「36　标题」类分项切分，每项压成两句并以空行分隔（一分项一片）。"""
    sections = _split_h2_sections(lines)
    if not sections:
        return lines, False
    out: list[str] = []
    for sec in sections:
        block = _compress_h2_section(sec)
        if block:
            out.append(block)
    if not out:
        return lines, False
    # 仅当存在至少一个 Heading2 分项时才视为已重构
    if not any(_H2_HEADING_RE.match(s[0]) for s in sections if s):
        return lines, False
    return out, True


def govern_text(text: str) -> str:
    """
    对抽取后的纯文本做治理，返回可安全分块入库的文本。

    步骤：去控制符 → 去噪行 → 脱敏 → 编号列表归并 → 分项两句压缩 → 空白归一。
    """
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not t.strip():
        return ""

    t = _CTRL_RE.sub("", t)
    for pat in _NOISE_PATTERNS:
        t = pat.sub("", t)

    t = _PHONE_RE.sub("[PHONE]", t)
    t = _ID_CARD_RE.sub("[ID_CARD]", t)
    t = _EMAIL_RE.sub("[EMAIL]", t)
    t = _REPEAT_RE.sub(r"\1\1\1", t)

    lines = [ln.strip() for ln in t.split("\n")]
    lines = _merge_break_numbered_lists(lines)
    lines = [_normalize_inline_numbered_list(ln) for ln in lines]

    # 将 lines 再展开为「行」，分项块内可能含 \\n
    flat: list[str] = []
    for ln in lines:
        if not ln:
            continue
        flat.extend([x.strip() for x in ln.split("\n") if x.strip()])

    section_blocks, restructured = _restructure_h2_sections(flat)
    if restructured:
        out_lines: list[str] = []
        for i, block in enumerate(section_blocks):
            if i > 0:
                out_lines.append("")
            out_lines.extend([x for x in block.split("\n") if x.strip()])
        lines = out_lines
    else:
        lines = flat

    out_lines: list[str] = []
    blank_run = 0
    for ln in lines:
        if not ln:
            blank_run += 1
            if blank_run <= 2:
                out_lines.append("")
            continue
        blank_run = 0
        out_lines.append(ln)

    return "\n".join(out_lines).strip()
