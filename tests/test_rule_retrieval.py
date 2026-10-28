"""规范向量检索：min_score + gap 动态 K 过滤。"""



from __future__ import annotations



import unittest



from inspection_platform.inspection_work.retrieval import (

    RULE_VECTOR_MAX_K,

    RULE_VECTOR_MIN_SCORE,

    RULE_VECTOR_SCORE_GAP,

    _filter_scored_hits,

    keyword_recall_rate,

)





class RuleRetrievalFilterTests(unittest.TestCase):

    def test_keyword_recall_rate(self) -> None:

        rule = {

            "name": "地库消防通道管理",

            "desc": "针对地下停车场消防通道违停问题",

            "requirements": "每日巡检",

        }

        rate = keyword_recall_rate("地库消防通道违停检测", rule)

        self.assertGreater(rate, 0.3)



    def test_filter_requires_min_score(self) -> None:

        rows = [

            (0.55, {"rule_id": "r1", "name": "A"}),

            (0.52, {"rule_id": "r2", "name": "B"}),

        ]

        out = _filter_scored_hits(

            rows,

            topic="无关描述",

            min_score=RULE_VECTOR_MIN_SCORE,

            gap=RULE_VECTOR_SCORE_GAP,

            max_k=RULE_VECTOR_MAX_K,

        )

        self.assertEqual(out, [])



    def test_filter_dynamic_k_with_gap(self) -> None:

        rows = [

            (0.88, {"rule_id": "r1", "name": "A", "desc": "a"}),

            (0.82, {"rule_id": "r2", "name": "B", "desc": "b"}),

            (0.79, {"rule_id": "r3", "name": "C", "desc": "c"}),

            (0.60, {"rule_id": "r4", "name": "D", "desc": "d"}),

        ]

        out = _filter_scored_hits(

            rows,

            topic="地库消防",

            min_score=RULE_VECTOR_MIN_SCORE,

            gap=RULE_VECTOR_SCORE_GAP,

            max_k=RULE_VECTOR_MAX_K,

        )

        ids = [h.rule["rule_id"] for h in out]

        self.assertEqual(ids, ["r1", "r2", "r3"])

        self.assertEqual(out[0].score, 0.88)





    def test_top_near_miss_without_min_score(self) -> None:
        from inspection_platform.inspection_work.retrieval import _top_near_miss_hits

        rows = [
            (0.55, {"rule_id": "r1", "name": "A"}),
            (0.52, {"rule_id": "r2", "name": "B"}),
            (0.48, {"rule_id": "r3", "name": "C"}),
            (0.40, {"rule_id": "r4", "name": "D"}),
        ]
        out = _top_near_miss_hits(rows, topic="地库消防", max_k=3)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0].rule["rule_id"], "r1")
        self.assertAlmostEqual(out[0].score, 0.55)


if __name__ == "__main__":

    unittest.main()

