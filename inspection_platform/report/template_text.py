"""报告模版文件文本提取（txt / md / doc / docx）。"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ALLOWED_TEMPLATE_EXTENSIONS = {".txt", ".md", ".markdown", ".docx", ".doc"}
MAX_TEMPLATE_BYTES = 5 * 1024 * 1024

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

DEFAULT_WORK_REPORT_TEMPLATE = """# 巡检业务执行报告

## 一、业务概要
- 业务名称：
- 执行时间：
- 作用区域：

## 二、规范对照
（对照已绑定规范条款，列出合规项与待整改项）

## 三、算法识别结果
（按算法汇总检测事件、截图与置信度）

## 四、设备与数据采集
（摄像头/传感器在线状态与关键读数）

## 五、异常与待办
（需跟进告警与整改建议）

## 六、结论
（本次巡检总体评价与下一步动作）
"""


def normalize_template_filename(name: str) -> str:
    base = Path(name or "template.txt").name.strip()
    return base or "template.txt"


def assert_allowed_template_file(filename: str, size: int) -> str:
    if size <= 0:
        raise ValueError("上传文件为空")
    if size > MAX_TEMPLATE_BYTES:
        raise ValueError(f"文件过大，最大 {MAX_TEMPLATE_BYTES // (1024 * 1024)} MB")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_TEMPLATE_EXTENSIONS:
        raise ValueError("仅支持 .txt / .md / .doc / .docx 格式")
    return ext


def extract_template_text(*, filename: str, raw: bytes) -> str:
    ext = assert_allowed_template_file(filename, len(raw))
    if ext in {".txt", ".md", ".markdown"}:
        return _extract_plain_text(raw)
    if ext == ".docx":
        return _extract_docx_text(raw)
    if ext == ".doc":
        return _extract_doc_binary(raw)
    raise ValueError("不支持的文件格式")


def _extract_plain_text(raw: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            text = raw.decode(enc).strip()
            if text:
                return text
        except UnicodeDecodeError:
            continue
    raise ValueError("文本文件解码失败，请使用 UTF-8 或 GBK 编码")


def _extract_docx_text(raw: bytes) -> str:
    if raw[:2] == b"PK":
        try:
            from docx import Document
        except ImportError as e:
            raise ValueError("服务端未安装 python-docx，无法解析 .docx 文件") from e
        try:
            doc = Document(io.BytesIO(raw))
        except Exception as e:
            raise ValueError(".docx 文件解析失败，请确认文件未损坏") from e
        lines = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
        text = "\n".join(lines).strip()
        if text:
            return text
        fallback = re.sub(r"\s+", " ", _extract_docx_xml_fallback(raw)).strip()
        if fallback:
            return fallback
        raise ValueError(".docx 文件无有效文本内容")
    # 扩展名 .docx 但实际是旧版 .doc
    if raw.startswith(_OLE_MAGIC):
        return _extract_doc_binary(raw)
    raise ValueError("不是有效的 .docx 文件（ZIP 格式），请确认扩展名与内容一致")


def _extract_doc_binary(raw: bytes) -> str:
    """解析旧版 Word 二进制 .doc（OLE），python-docx 不支持此格式。"""
    if not raw.startswith(_OLE_MAGIC):
        raise ValueError("不是有效的 Word .doc 文件")

    for extractor in (_extract_doc_via_antiword, _extract_doc_utf16_runs):
        text = extractor(raw)
        if text.strip():
            return text.strip()

    raise ValueError(
        "无法从 .doc 文件提取文本；建议在 WPS/Word 中「另存为」.docx 或 .txt 后重新上传"
    )


def _extract_doc_via_antiword(raw: bytes) -> str:
    """可选：系统已安装 antiword 时用于高质量 .doc 提取。"""
    antiword = shutil.which("antiword")
    if not antiword:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    try:
        proc = subprocess.run(
            [antiword, "-m", "UTF-8.txt", tmp_path],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            return ""
        return proc.stdout.decode("utf-8", errors="ignore").strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _utf16_code_to_char(code: int) -> str | None:
    if code in (0x0D, 0x0A):
        return "\n"
    if code in (0x09,):
        return " "
    if 0x20 <= code <= 0x7E:
        return chr(code)
    if 0x4E00 <= code <= 0x9FFF:
        return chr(code)
    if 0x3000 <= code <= 0x303F or 0xFF00 <= code <= 0xFFEF:
        return chr(code)
    return None


def _extract_doc_utf16_runs(raw: bytes) -> str:
    """从 .doc 二进制中扫描 UTF-16LE 可读文本段（适用于 WPS/Word 简单文档）。"""
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(raw)
    while i + 1 < n:
        code = raw[i] | (raw[i + 1] << 8)
        i += 2
        ch = _utf16_code_to_char(code)
        if ch is not None:
            buf.append(ch)
            continue
        if len(buf) >= 2:
            parts.append("".join(buf))
        buf = []

    if len(buf) >= 2:
        parts.append("".join(buf))

    lines: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for line in part.splitlines():
            line = re.sub(r"[ \t]+", " ", line).strip()
            if len(line) < 2:
                continue
            if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", line):
                continue
            if line in seen:
                continue
            seen.add(line)
            lines.append(line)
    return "\n".join(lines)


def _extract_docx_xml_fallback(raw: bytes) -> str:
    try:
        import zipfile

        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    except Exception:
        return ""
    return re.sub(r"<[^>]+>", " ", xml)
