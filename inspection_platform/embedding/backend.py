"""Embedding 后端选择：SiliconFlow / vLLM（HTTP）或 SentenceTransformer（进程内）。"""

from __future__ import annotations

from typing import Any


def resolve_embedding_backend() -> str:
    """
    返回 ``openai``、``vllm`` 或 ``sentence_transformer``。

    环境变量 ``SIA_EMBEDDING_BACKEND``：
    - ``openai`` / ``siliconflow``：走 OpenAI 兼容 ``/v1/embeddings``（云端，如硅基流动）
    - ``vllm``：走 vLLM OpenAI ``/v1/embeddings``（需独立启动 vLLM 服务）
    - ``sentence_transformer``：进程内 SentenceTransformer
    - 未设置时：若配置了 ``SILICONFLOW_API_KEY`` 则默认 ``siliconflow``，
      否则若配置了 ``SIA_VLLM_EMBED_BASE_URL`` 则 ``vllm``，否则 ST
    """
    from inspection_platform.envutil import env_first

    raw = (env_first("SIA_EMBEDDING_BACKEND") or "").strip().lower()
    if raw in ("siliconflow", "sf", "cloud", "openai"):
        return "openai"
    if raw in ("vllm", "vllm_http", "http"):
        return "vllm"
    if raw in ("sentence_transformer", "st", "local"):
        return "sentence_transformer"
    if raw:
        raise ValueError(
            f"无效的 SIA_EMBEDDING_BACKEND={raw!r}；允许 openai、vllm、sentence_transformer"
        )
    if env_first("SIA_OPENAI_API_KEY", "SILICONFLOW_API_KEY"):
        return "openai"
    if env_first("SIA_VLLM_EMBED_BASE_URL"):
        return "vllm"
    return "sentence_transformer"


def embed_texts(
    texts: list[str],
    *,
    metadata: dict[str, Any] | None = None,
    model_name: str | None = None,
) -> list[list[float]]:
    backend = resolve_embedding_backend()
    if backend == "openai":
        from inspection_platform.embedding.openai_embed import embed_texts as openai_embed

        return openai_embed(texts, metadata=metadata, model_name=model_name)
    if backend == "vllm":
        from inspection_platform.embedding.vllm_embed import vllm_embed_texts

        return vllm_embed_texts(texts, metadata=metadata, model_name=model_name)
    from inspection_platform.embedding.sentence_transformer_embed import (
        sentence_transformer_embed_texts,
    )

    return sentence_transformer_embed_texts(texts, metadata=metadata)


async def embed_texts_async(
    texts: list[str],
    *,
    metadata: dict[str, Any] | None = None,
    model_name: str | None = None,
) -> list[list[float]]:
    backend = resolve_embedding_backend()
    if backend == "openai":
        from inspection_platform.embedding.openai_embed import embed_texts_async as openai_embed_async

        return await openai_embed_async(texts, metadata=metadata, model_name=model_name)
    if backend == "vllm":
        from inspection_platform.embedding.vllm_embed import vllm_embed_texts

        import asyncio

        return await asyncio.to_thread(
            vllm_embed_texts, texts, metadata=metadata, model_name=model_name
        )
    from inspection_platform.embedding.sentence_transformer_embed import (
        sentence_transformer_embed_texts,
    )

    import asyncio

    return await asyncio.to_thread(sentence_transformer_embed_texts, texts, metadata=metadata)


def embedding_dimension() -> int:
    backend = resolve_embedding_backend()
    if backend == "openai":
        from inspection_platform.embedding.openai_embed import embedding_dimension as openai_dim

        return openai_dim()
    if backend == "vllm":
        from inspection_platform.embedding.vllm_embed import vllm_embedding_dimension

        return vllm_embedding_dimension()
    from inspection_platform.embedding.sentence_transformer_embed import embedding_dimension as st_dim

    return st_dim()


def embedding_device_label() -> str:
    backend = resolve_embedding_backend()
    if backend == "openai":
        from inspection_platform.llm.openai_client import openai_embed_base_url, openai_embed_model

        return f"openai:{openai_embed_base_url()}:{openai_embed_model()}"
    if backend == "vllm":
        from inspection_platform.embedding.vllm_embed import _base_url

        return f"vllm:{_base_url()}"
    from inspection_platform.embedding.sentence_transformer_embed import embedding_device

    return embedding_device()


def warmup() -> None:
    embed_texts(["warmup"], metadata={"stage": "warmup"})
