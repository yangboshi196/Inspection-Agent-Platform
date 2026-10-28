"""Embedding 向量化 HTTP API（供调试与外部调用）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from inspection_platform.embedding.backend import (
    embed_texts,
    embedding_dimension,
    embedding_device_label,
    resolve_embedding_backend,
)
from inspection_platform.embedding.openai_embed import embed_api_health
from inspection_platform.embedding.vllm_embed import vllm_health

router = APIRouter(prefix="/api/embedding", tags=["embedding"])


class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=256)
    model: str | None = Field(default=None, description="覆盖默认 embedding 模型；空则与知识库一致")


class EmbeddingResponse(BaseModel):
    backend: str
    model_device: str
    dimension: int
    vectors: list[list[float]]


@router.get("/status")
def embedding_status() -> dict[str, Any]:
    backend = resolve_embedding_backend()
    out: dict[str, Any] = {
        "backend": backend,
        "model_device": embedding_device_label(),
    }
    if backend == "openai":
        out["openai"] = embed_api_health()
    elif backend == "vllm":
        out["vllm"] = vllm_health()
    try:
        out["dimension"] = embedding_dimension()
        out["ready"] = True
    except Exception as e:
        out["ready"] = False
        out["error"] = str(e)
    return out


@router.post("/embed", response_model=EmbeddingResponse)
def embedding_embed(body: EmbeddingRequest) -> EmbeddingResponse:
    texts = [str(t) for t in body.texts if str(t).strip()]
    if not texts:
        raise HTTPException(status_code=400, detail="texts 不能为空")
    try:
        from inspection_platform.deps import platform_embedding_model_name

        vectors = embed_texts(
            texts,
            metadata={"api": "embedding_embed"},
            model_name=(body.model or "").strip() or platform_embedding_model_name(),
        )
        dim = embedding_dimension()
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return EmbeddingResponse(
        backend=resolve_embedding_backend(),
        model_device=embedding_device_label(),
        dimension=dim,
        vectors=vectors,
    )
