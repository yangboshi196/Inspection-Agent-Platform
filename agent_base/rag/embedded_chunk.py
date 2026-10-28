"""
RAG 向量检索的基本数据单元 - 一条可检索的文本块及其元数据。

包含：
- EmbeddedChunk：可检索单元，携带 chunk_id / text / vector / meta
"""


from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EmbeddedChunk:
    """
    RAG 中的一条可检索单元。

    - `chunk_id`：业务侧稳定标识（写入 Chroma 时会再映射为内部 id）
    - `text`：参与展示与模型拼接的正文片段
    - `vector`：与 `text` 对应的 embedding（检索结果里可能为空列表，仅元数据回填场景）
    - `meta`：引用来源等过滤/展示用字段（需符合 Chroma metadata 约束）
    """

    chunk_id: str
    text: str
    vector: list[float]
    meta: dict[str, Any]
