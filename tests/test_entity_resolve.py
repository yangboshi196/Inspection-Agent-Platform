"""意图路实体解析通用逻辑测试（不依赖具体业务词表）。"""

from __future__ import annotations

import unittest

from inspection_platform.inspection_work.entity_resolve import (
    _score_text_match,
    collect_pin_search_terms,
    expand_mention_phrases,
    extract_explicit_mentions,
)


class EntityResolveGenericTest(unittest.TestCase):
    def test_strip_detection_suffix_generic(self) -> None:
        terms = expand_mention_phrases("任意对象检测")
        self.assertIn("任意对象检测", terms)
        self.assertIn("任意对象", terms)

    def test_capability_phrase_extraction(self) -> None:
        topic = "另外还需要做温度超限识别和烟雾检测，摄像头要覆盖"
        m = extract_explicit_mentions(topic, {"regions": [], "algorithms": [], "devices": []})
        self.assertTrue(any("温度超限" in x or "温度超限识别" in x for x in m.algorithms))
        self.assertTrue(any("烟雾" in x for x in m.algorithms))
        self.assertIn("摄像头", m.devices)

    def test_fuzzy_score_substring(self) -> None:
        # 用户表述与目录名不完全一致时，子串/token 仍应得高分
        score = _score_text_match("石头", "石头裸露识别")
        self.assertGreaterEqual(score, 0.85)

    def test_pin_terms_only_from_explicit_mentions(self) -> None:
        topic = "A区日常巡检，另外做foo检测和bar识别"
        intent = {
            "regions": [{"id": "", "name": "A区"}],
            "algorithms": [{"id": "", "name": "bar识别"}],
            "devices": [],
        }
        algo_terms, region_terms, _device_terms = collect_pin_search_terms(topic, intent)
        self.assertTrue(any("bar" in t for t in algo_terms))
        self.assertTrue(any("foo" in t for t in algo_terms))
        self.assertTrue(any("A区" in t for t in region_terms))
        # 不应把整段 topic 里的无关词都塞进 pin
        self.assertFalse(any("日常巡检" == t for t in algo_terms))


if __name__ == "__main__":
    unittest.main()
