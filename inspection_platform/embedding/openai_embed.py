"""OpenAI 兼容 ``/embeddings`` 向量化（AsyncOpenAI，多 batch 并发）。"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from typing import Any

from inspection_platform.llm.async_runtime import run_async
from inspection_platform.llm.openai_client import (
    get_async_openai_embed_client,
    openai_embed_base_url,
    openai_embed_model,
)

logger = logging.getLogger(__name__)

_cached_dimension: int | None = None
_DEFAULT_BATCH = 32
_MAX_CONCURRENT_BATCHES = 4


def _configured_dimension() -> int | None:
    from inspection_platform.envutil import env_first

    raw = env_first("SIA_EMBEDDING_DIMENSION")
    if not raw:
        return None
    return max(1, int(raw))


def _max_concurrent_batches() -> int:
    from inspection_platform.envutil import env_first

    raw = env_first(
        "SIA_OPENAI_EMBED_CONCURRENCY",
        "SILICONFLOW_EMBED_CONCURRENCY",
        "SIA_EMBED_CONCURRENCY",
    )
    if not raw:
        return _MAX_CONCURRENT_BATCHES
    try:
        return max(1, min(int(raw), 16))
    except ValueError:
        return _MAX_CONCURRENT_BATCHES


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0:
        return vec
    return [x / norm for x in vec]


def _embed_key_kind() -> str:
    key = openai_embed_api_key()
    if key.startswith("sk-"):
        return "sk"
    return "other"


async def _embed_batch_async(batch: list[str], *, model_name: str | None = None) -> list[list[float]]:
    client = get_async_openai_embed_client()
    try:
        resp = await client.embeddings.create(
            model=openai_embed_model(model_name),
            input=batch,
            encoding_format="float",
        )
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "Invalid token" in msg:
            from inspection_platform.llm.openai_client import openai_embed_api_key

            logger.error(
                "embedding 401 base=%s model=%s key_kind=%s len=%s",
                openai_embed_base_url(),
                openai_embed_model(model_name),
                _embed_key_kind(),
                len(openai_embed_api_key()),
            )
        raise
    rows = sorted(resp.data, key=lambda r: int(getattr(r, "index", 0) or 0))
    if len(rows) != len(batch):
        raise ValueError(
            f"embedding 返回条数异常：期望 {len(batch)}，实际 {len(rows)}"
        )
    out: list[list[float]] = []
    for row in rows:
        emb = getattr(row, "embedding", None)
        if not isinstance(emb, list):
            raise ValueError("embedding 响应缺少 embedding 数组")
        out.append(_l2_normalize([float(x) for x in emb]))
    return out


async def embed_texts_async(
    texts: list[str],
    *,
    metadata: dict[str, Any] | None = None,
    model_name: str | None = None,
) -> list[list[float]]:
    _ = metadata
    if not texts:
        return []
    global _cached_dimension
    normalized = [t if (t or "").strip() else " " for t in texts]
    batches: list[tuple[int, list[str]]] = []
    for off in range(0, len(normalized), _DEFAULT_BATCH):
        batches.append((off, normalized[off : off + _DEFAULT_BATCH]))

    sem = asyncio.Semaphore(_max_concurrent_batches())
    results: dict[int, list[list[float]]] = {}

    async def run_one(off: int, part: list[str]) -> None:
        async with sem:
            results[off] = await _embed_batch_async(part, model_name=model_name)

    await asyncio.gather(*(run_one(off, part) for off, part in batches))

    out: list[list[float]] = []
    for off, _part in batches:
        out.extend(results[off])
    if len(out) != len(texts):
        raise ValueError("embedding 返回向量数与输入不一致")
    if out and _cached_dimension is None:
        _cached_dimension = len(out[0])
    return out


def embed_texts(
    texts: list[str],
    *,
    metadata: dict[str, Any] | None = None,
    model_name: str | None = None,
) -> list[list[float]]:
    return run_async(embed_texts_async(texts, metadata=metadata, model_name=model_name))


def embedding_dimension() -> int:
    global _cached_dimension
    cfg = _configured_dimension()
    if cfg is not None:
        return cfg
    if _cached_dimension is not None:
        return _cached_dimension
    embed_texts(["dimension_probe"], metadata={"stage": "probe"})
    if _cached_dimension is None:
        raise ValueError("无法探测 embedding 维度")
    return _cached_dimension


def embed_api_health() -> dict[str, Any]:
    try:
        vectors = embed_texts(["health_probe"])
        dim = len(vectors[0]) if vectors else None
        return {
            "ok": True,
            "base_url": openai_embed_base_url(),
            "model": openai_embed_model(),
            "dimension": dim,
        }
    except Exception as e:
        return {
            "ok": False,
            "base_url": openai_embed_base_url(),
            "model": openai_embed_model(),
            "error": str(e),
        }
