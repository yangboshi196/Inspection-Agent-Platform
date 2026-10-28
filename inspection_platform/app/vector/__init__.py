"""向量存储工厂（仅 Milvus）。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from inspection_platform.app.config import get_settings


class VectorStore(Protocol):
    chunk_count: int

    def reset(self) -> None: ...
    def delete_by_filters(self, filters: dict[str, Any]) -> int: ...
    def count_by_filters(self, filters: dict[str, Any]) -> int: ...
    def add_embedded_chunks(self, chunks: list[Any], *, batch_size: int = 128) -> None: ...
    def query_similar_chunks(self, query_vector: list[float], **kwargs: Any) -> list[tuple[float, Any]]: ...


def _require_milvus_backend() -> None:
    backend = os.environ.get("SIA_VECTOR_BACKEND", "milvus").strip().lower()
    if backend and backend != "milvus":
        raise ValueError(
            f"不支持的向量后端 {backend!r}；本平台仅支持 Milvus，"
            "请设置 SIA_VECTOR_BACKEND=milvus 并确保 Milvus 服务可用"
        )


def create_vector_store(*, kb_id: str, persist_dir: Path | None = None) -> Any:
    """创建 Milvus 向量存储（按 kb_id 映射 collection）。"""
    _require_milvus_backend()
    from inspection_platform.app.vector.milvus_store import MilvusVectorStore

    settings = get_settings()
    dim: int | None = None
    try:
        from inspection_platform.embedding.backend import embedding_dimension

        dim = embedding_dimension()
    except Exception:
        dim = None

    store = MilvusVectorStore(
        host=settings.milvus_host,
        port=settings.milvus_port,
        kb_id=kb_id,
        persist_dir=persist_dir or settings.milvus_persist_path,
        dim=dim,
    )
    _ = store.chunk_count
    return store


def list_vector_collections() -> list[str]:
    """列出 Milvus 中全部 collection（知识库分区）。"""
    _require_milvus_backend()
    try:
        from pymilvus import MilvusClient
    except ImportError as e:
        raise RuntimeError("未安装 pymilvus，无法连接 Milvus") from e

    settings = get_settings()
    client = MilvusClient(uri=f"http://{settings.milvus_host}:{settings.milvus_port}")
    names = list(client.list_collections() or [])
    return names if names else ["default"]
