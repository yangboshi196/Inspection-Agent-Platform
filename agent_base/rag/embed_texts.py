"""平台与 RAG 共用的文本向量化入口（经 ``ModelManager``）。

业务层（如 FastAPI 知识库、规范管理）应调用本模块，而不是直接使用
Chroma 内置 ONNX 嵌入，以便与 Agent 使用同一套 ``models.json`` 与密钥配置。
"""

from __future__ import annotations

from typing import Any

from ..llm.types import EmbeddingRequest, EmbeddingResponse
from ..model_manager.manager import ModelManager


def embed_texts(
    model_manager: ModelManager,
    texts: list[str],
    *,
    model_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[list[float]]:
    """
    将 ``texts`` 批量编码为浮点向量列表。

    ``model_name`` 为 ``None`` 时，使用 ``ModelManager`` 中带 ``default`` 标签的
    embedding 模型（见 ``model_manager/models.json``）。
    """
    if not texts:
        return []
    meta: dict[str, Any] = dict(metadata or {})
    resp: EmbeddingResponse = model_manager.call_embedding(
        EmbeddingRequest(texts=texts, metadata=meta),
        model_name=model_name,
    )
    out: list[list[float]] = []
    for v in resp.vectors:
        if v is None:
            raise ValueError("embedding response contains null vector")
        out.append(list(map(float, v)))
    if len(out) != len(texts):
        raise ValueError(
            f"embedding 返回 {len(out)} 条向量，期望 {len(texts)} 条；"
            "请检查 embedding 服务是否可用且已加载向量模型"
        )
    return out
