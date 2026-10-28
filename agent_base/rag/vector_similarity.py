"""向量检索分数：统一为可展示的余弦相似度 [0, 1]。"""

from __future__ import annotations

import math


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """两向量余弦相似度，原始值 ∈ [-1, 1]。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (na * nb)


def clamp_similarity_for_display(similarity: float) -> float:
    """业务展示 / 阈值过滤用语义相似度，钳制到 [0, 1]（略负相关视为 0）。"""
    return max(0.0, min(1.0, float(similarity)))


def milvus_cosine_hit_to_similarity(raw_distance: float) -> float:
    """
    将 Milvus ``metric_type=COSINE`` 搜索命中里的 ``distance`` 转为展示用相似度。

    官方语义（Milvus 2.x）：该字段为 **cosine similarity** ∈ [-1, 1]，
    数值越大越相似；**不是** ``1 - cosine_similarity`` 距离。
    参见 https://milvus.io/docs/single-vector-search.md

    历史代码误用 ``1 - distance`` 会在几乎不相关（≈0）时显示成 ≈100%。
    """
    v = float(raw_distance)
    if 1.0 < v <= 2.0:
        # 兼容极少数按 cosine distance 返回的旧索引/部署
        return clamp_similarity_for_display(1.0 - v)
    return clamp_similarity_for_display(v)


def chroma_cosine_distance_to_similarity(distance: float) -> float:
    """Chroma ``hnsw:space=cosine`` 返回 distance = 1 - cosine_similarity。"""
    return clamp_similarity_for_display(1.0 - float(distance))


def score_query_against_stored_vector(
    query_vector: list[float],
    stored_vector: list[float] | None,
    *,
    milvus_raw: float | None = None,
) -> float:
    """
    优先用查询向量与库内向量手算余弦（与 embedding 模型一致时最可信）；
    无库内向量时回退 Milvus ``distance`` 字段。
    """
    if stored_vector and query_vector and len(stored_vector) == len(query_vector):
        return clamp_similarity_for_display(cosine_similarity(query_vector, stored_vector))
    if milvus_raw is not None:
        return milvus_cosine_hit_to_similarity(milvus_raw)
    return 0.0
