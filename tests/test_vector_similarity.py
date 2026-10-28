"""向量相似度换算单元测试。"""

from __future__ import annotations

import math
import unittest

from agent_base.rag.vector_similarity import (
    chroma_cosine_distance_to_similarity,
    clamp_similarity_for_display,
    cosine_similarity,
    milvus_cosine_hit_to_similarity,
    score_query_against_stored_vector,
)


class VectorSimilarityTests(unittest.TestCase):
    def test_milvus_cosine_field_is_similarity_not_distance(self) -> None:
        # 官方：COSINE 检索 distance ∈ [-1,1]，越大越相似
        self.assertAlmostEqual(milvus_cosine_hit_to_similarity(0.66), 0.66, places=6)
        self.assertAlmostEqual(milvus_cosine_hit_to_similarity(0.0003), 0.0003, places=6)
        self.assertAlmostEqual(milvus_cosine_hit_to_similarity(-0.2), 0.0, places=6)

    def test_old_formula_would_have_shown_100_percent(self) -> None:
        raw = 0.0003
        wrong = 1.0 - raw
        self.assertGreater(wrong, 0.99)
        self.assertAlmostEqual(milvus_cosine_hit_to_similarity(raw), raw, places=6)

    def test_milvus_legacy_cosine_distance_range(self) -> None:
        # 少数部署返回 cosine distance ∈ (1, 2]
        self.assertAlmostEqual(milvus_cosine_hit_to_similarity(1.2), 0.0, places=6)

    def test_perfect_match_is_one_not_zero(self) -> None:
        self.assertAlmostEqual(milvus_cosine_hit_to_similarity(1.0), 1.0, places=6)

    def test_chroma_cosine_distance(self) -> None:
        self.assertAlmostEqual(chroma_cosine_distance_to_similarity(0.0), 1.0, places=6)
        self.assertAlmostEqual(chroma_cosine_distance_to_similarity(0.25), 0.75, places=6)

    def test_recompute_from_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [0.6, 0.8]  # unit vector, cos with a = 0.6
        self.assertAlmostEqual(cosine_similarity(a, b), 0.6, places=6)
        score = score_query_against_stored_vector(a, b, milvus_raw=0.99)
        self.assertAlmostEqual(score, 0.6, places=6)

    def test_recompute_fallback_to_milvus_raw(self) -> None:
        self.assertAlmostEqual(
            score_query_against_stored_vector([1.0, 0.0], None, milvus_raw=0.55),
            0.55,
            places=6,
        )


if __name__ == "__main__":
    unittest.main()
