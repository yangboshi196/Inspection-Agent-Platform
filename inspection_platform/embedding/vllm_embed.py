"""经 vLLM OpenAI 兼容 ``/v1/embeddings`` 服务做向量化（GPU 加速）。"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

_cached_dimension: int | None = None
_DEFAULT_BATCH = 64


def _base_url() -> str:
    from inspection_platform.envutil import env_first

    raw = (env_first("SIA_VLLM_EMBED_BASE_URL") or "http://127.0.0.1:8100/v1").strip()
    return raw.rstrip("/")


def _api_key() -> str:
    from inspection_platform.envutil import env_first

    return env_first("SIA_VLLM_EMBED_API_KEY") or "EMPTY"


def _model_name() -> str:
    from inspection_platform.envutil import env_first

    explicit = env_first("SIA_VLLM_EMBED_MODEL")
    if explicit:
        return explicit
    from inspection_platform.embedding.sentence_transformer_embed import (
        QWEN3_EMBED_HUB_ID,
        resolve_embedding_model_source,
    )

    source, local = resolve_embedding_model_source()
    if local is not None:
        return str(local)
    return source or QWEN3_EMBED_HUB_ID


def _timeout_sec() -> float:
    from inspection_platform.envutil import env_first

    raw = env_first("SIA_VLLM_EMBED_TIMEOUT_SEC")
    if raw:
        return max(5.0, float(raw))
    return 120.0


def _configured_dimension() -> int | None:
    from inspection_platform.envutil import env_first

    raw = env_first("SIA_EMBEDDING_DIMENSION")
    if not raw:
        return None
    return max(1, int(raw))


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0:
        return vec
    return [x / norm for x in vec]


def _post_embeddings(batch: list[str], *, model_name: str | None = None) -> list[list[float]]:
    import httpx

    url = f"{_base_url()}/embeddings"
    payload = {
        "model": (model_name or "").strip() or _model_name(),
        "input": batch,
        "encoding_format": "float",
    }
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=_timeout_sec()) as client:
            resp = client.post(url, json=payload, headers=headers)
    except httpx.ConnectError as e:
        raise ValueError(
            f"无法连接 vLLM embedding 服务 {url}；请先运行 scripts/start_vllm_embedding.sh"
        ) from e
    except Exception as e:
        raise ValueError(f"vLLM embedding 请求失败：{e}") from e

    if resp.status_code >= 400:
        raise ValueError(f"vLLM embedding HTTP {resp.status_code}: {resp.text[:500]}")

    body = resp.json()
    rows = body.get("data") or []
    if not isinstance(rows, list) or len(rows) != len(batch):
        raise ValueError(
            f"vLLM embedding 返回条数异常：期望 {len(batch)}，实际 {len(rows)}"
        )
    rows_sorted = sorted(rows, key=lambda r: int(r.get("index", 0)))
    out: list[list[float]] = []
    for row in rows_sorted:
        emb = row.get("embedding")
        if not isinstance(emb, list):
            raise ValueError("vLLM embedding 响应缺少 embedding 数组")
        out.append(_l2_normalize([float(x) for x in emb]))
    return out


def vllm_embed_texts(
    texts: list[str],
    *,
    metadata: dict[str, Any] | None = None,
    model_name: str | None = None,
) -> list[list[float]]:
    """批量文本向量化（vLLM HTTP）。"""
    _ = metadata
    if not texts:
        return []
    global _cached_dimension
    out: list[list[float]] = []
    batch_sz = _DEFAULT_BATCH
    for off in range(0, len(texts), batch_sz):
        part = [t if (t or "").strip() else " " for t in texts[off : off + batch_sz]]
        out.extend(_post_embeddings(part, model_name=model_name))
    if len(out) != len(texts):
        raise ValueError("vLLM embedding 返回向量数与输入不一致")
    if out and _cached_dimension is None:
        _cached_dimension = len(out[0])
    return out


def vllm_embedding_dimension() -> int:
    global _cached_dimension
    cfg = _configured_dimension()
    if cfg is not None:
        return cfg
    if _cached_dimension is not None:
        return _cached_dimension
    vllm_embed_texts(["dimension_probe"], metadata={"stage": "probe"})
    if _cached_dimension is None:
        raise ValueError("无法探测 vLLM embedding 维度")
    return _cached_dimension


def vllm_health() -> dict[str, Any]:
    import httpx

    base = _base_url()
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{base}/models", headers={"Authorization": f"Bearer {_api_key()}"})
        ok = resp.status_code < 400
        detail = resp.json() if ok else resp.text[:300]
    except Exception as e:
        return {"ok": False, "base_url": base, "error": str(e)}
    return {"ok": ok, "base_url": base, "models": detail}
