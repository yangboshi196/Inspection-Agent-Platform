"""知识库文本治理单元测试。"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


def _load_preprocess():
    path = Path(__file__).resolve().parents[1] / "inspection_platform/knowledge/preprocess.py"
    spec = importlib.util.spec_from_file_location("knowledge_preprocess", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_preprocess = _load_preprocess()
govern_text = _preprocess.govern_text


class GovernTextNumberedListTest(unittest.TestCase):
    def test_inline_numbered_list_joined_with_semicolon_and_period(self) -> None:
        raw = (
            "现场曾讨论的实施要点（原表「记录内容」栏）："
            "1、摄像头要考虑安装位置  2、吊篮是临时一个月  3、摄像头是动态变位置的"
        )
        out = govern_text(raw)
        self.assertIn("1、摄像头要考虑安装位置；2、吊篮是临时一个月；3、摄像头是动态变位置的", out)
        self.assertTrue(out.endswith("。"))

    def test_inline_question_list_keeps_question_marks(self) -> None:
        raw = (
            "实施中需事先厘清的问题（原表）："
            "1、洞口附近是否可以临时加装摄像头？  2、监护人在岗的时间怎么获取或定义？"
        )
        out = govern_text(raw)
        self.assertIn("？；2、", out)

    def test_multiline_numbered_list_merged(self) -> None:
        raw = "检查要点：\n1、佩戴安全帽\n2、系好安全带\n3、设置警戒区"
        out = govern_text(raw)
        self.assertEqual(
            out,
            "检查要点：1、佩戴安全帽；2、系好安全带；3、设置警戒区。",
        )

    def test_multiline_without_colon_prefix(self) -> None:
        raw = "1、第一项要求\n2、第二项要求"
        out = govern_text(raw)
        self.assertEqual(out, "1、第一项要求；2、第二项要求。")

    def test_h2_section_compressed_to_two_sentences(self) -> None:
        raw = (
            "36\u3000螺丝栓松动（施工机具（隐患判定可视化图集））\n"
            "评估表摘录（供对照，非逐字法律条文）\n"
            "生产管理要求（模拟细化，可写入项目细则）\n"
            "按图集要点编制专项检查表，检查频次建议每周不少于一次，检查人须签字。\n"
            "发现疑似隐患应下发整改通知单，明确责任人、措施与完成时限；整改完成后须复查销号。\n"
            "本条目实施中遇到的界面问题应在协调会纪要中固化，并告知相关班组。"
        )
        out = govern_text(raw)
        lines = [ln for ln in out.split("\n") if ln.strip()]
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("36\u3000"))
        self.assertIn("专项检查表", lines[0])
        self.assertIn("协调会纪要", lines[1])

    def test_heading_with_fullwidth_space_not_merged(self) -> None:
        raw = "二、分项执行要求\n1　吊篮超员检查（人数统计类）\n评估表摘录"
        out = govern_text(raw)
        self.assertIn("1　吊篮超员检查", out)
        self.assertIn("评估表摘录", out)


if __name__ == "__main__":
    unittest.main()
