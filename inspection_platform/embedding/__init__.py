"""平台本地 embedding（SentenceTransformer）。"""

from .sentence_transformer_embed import (
    QWEN3_EMBED_HUB_ID,
    embedding_dimension,
    embedding_model_path,
    resolve_embedding_model_source,
    sentence_transformer_embed_texts,
)

__all__ = [
    "QWEN3_EMBED_HUB_ID",
    "embedding_dimension",
    "embedding_model_path",
    "resolve_embedding_model_source",
    "sentence_transformer_embed_texts",
]
