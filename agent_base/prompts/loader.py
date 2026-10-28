"""从 `SIA_agent/prompts/` 目录按相对路径加载文案，供各模块统一引用。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PROMPTS_ROOT = Path(__file__).resolve().parent


def load_prompt(relative_path: str) -> str:
    """
    读取相对 `SIA_agent/prompts/` 的文本文件（utf-8），返回去掉首尾空白的内容。

    ``relative_path`` 使用 POSIX 风格子路径，例如 ``agent/main_agent_default.txt``。
    """
    rel = relative_path.replace("\\", "/").strip().lstrip("/")
    if not rel or ".." in rel.split("/"):
        raise ValueError(f"invalid prompt path: {relative_path!r}")
    p = _PROMPTS_ROOT.joinpath(*rel.split("/"))
    if not p.is_file():
        raise FileNotFoundError(f"prompt file not found: {relative_path}")
    return p.read_text(encoding="utf-8").replace("\r\n", "\n").strip()


def load_prompt_fmt(relative_path: str, **kwargs: object) -> str:
    """`load_prompt` 后对 ``str.format``，模板中使用单花括号占位符。"""
    return load_prompt(relative_path).format(**kwargs)


def load_prompt_json(relative_path: str) -> dict[str, Any]:
    """读取 JSON 对象（用于多段标签、占位符字典等）。"""
    raw = load_prompt(relative_path)
    return json.loads(raw)
