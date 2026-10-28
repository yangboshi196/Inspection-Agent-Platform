"""报告模版文本提取单测。"""

from __future__ import annotations

import unittest

from inspection_platform.report.template_text import (
    _OLE_MAGIC,
    _extract_doc_binary,
    _extract_doc_utf16_runs,
    _extract_plain_text,
    extract_template_text,
)


def _fake_doc_with_text(text: str) -> bytes:
    """构造含 UTF-16LE 文本段的简易 .doc 二进制（非完整 OLE，仅测扫描逻辑）。"""
    body = text.encode("utf-16-le")
    return _OLE_MAGIC + b"\x00" * 512 + body + b"\x00" * 64


class TemplateTextTests(unittest.TestCase):
    def test_plain_utf8(self) -> None:
        raw = "# 标题\n\n正文".encode("utf-8")
        self.assertIn("标题", extract_template_text(filename="a.md", raw=raw))

    def test_plain_gbk(self) -> None:
        raw = "巡检报告模板".encode("gb18030")
        self.assertIn("巡检", extract_template_text(filename="a.txt", raw=raw))

    def test_doc_utf16_runs(self) -> None:
        sample = "描述出当前业务的区域、设备、算法\n给出执行结果"
        raw = _fake_doc_with_text(sample)
        out = _extract_doc_utf16_runs(raw)
        self.assertIn("描述出当前业务", out)
        self.assertIn("给出执行结果", out)

    def test_doc_binary(self) -> None:
        sample = "1. 描述出当前业务的区域、设备、算法\n2. 描述出当前业务执行状态\n3. 给出执行结果"
        raw = _fake_doc_with_text(sample)
        out = _extract_doc_binary(raw)
        self.assertIn("区域、设备、算法", out)
        self.assertIn("执行结果", out)


if __name__ == "__main__":
    unittest.main()
