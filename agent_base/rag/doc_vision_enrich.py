"""
从 PDF / DOCX 中提取插图，调用多模态（visual）模型生成文字描述，
并把描述插入到正文中（在版式信息不足时，尽量按「阅读顺序」贴近原位置），
供后续分块与 embedding 使用。
"""

from __future__ import annotations

import base64
import logging
from functools import lru_cache
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from docx import Document as load_docx
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table as DocxTable, _Cell
from docx.text.paragraph import Paragraph as DocxParagraph
from docx.text.run import Run as DocxRun
from pypdf import PdfReader

from ..llm.errors import LLMError
from ..llm.mime import guess_image_mime_from_bytes
from ..llm.types import VisualImage, VisualRequest
from ..model_manager.manager import ModelManager
from ..prompts import load_prompt, load_prompt_json

_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_DEFAULT_MAX_IMAGES = 32

_log = logging.getLogger(__name__)

IngestProgressCallback = Callable[[dict[str, Any]], None]


def _emit_progress(cb: IngestProgressCallback | None, ev: dict[str, Any]) -> None:
    if not cb:
        return
    try:
        cb(ev)
    except Exception:
        pass


def _vision_bar_percent(current: int, total: int, *, cap: int = 68) -> int:
    """识图阶段占整体进度的前 cap%（余量留给分块与 embedding）。"""
    if total <= 0:
        return min(cap, 5)
    return min(cap, max(1, int(cap * current / total)))


@lru_cache(maxsize=1)
def _rag_vision_caption_template() -> str:
    return load_prompt("rag/doc_image_caption.txt")


@lru_cache(maxsize=1)
def _rag_vision_inline_msgs() -> dict[str, str]:
    return load_prompt_json("rag/vision_inline.json")


@lru_cache(maxsize=1)
def _rag_vision_progress_tpl() -> str:
    return load_prompt("rag/vision_progress.txt")


def _describe_one_image(
    model_manager: ModelManager,
    data: bytes,
    *,
    request_id: str,
    vision_model_name: str | None,
    ordinal: int,
) -> str:
    vi = _rag_vision_inline_msgs()
    mime = guess_image_mime_from_bytes(data[:32])
    b64 = base64.standard_b64encode(data).decode("ascii")
    img = VisualImage(base64=b64, mime_type=mime)
    prompt = _rag_vision_caption_template().format(ordinal=ordinal)
    req = VisualRequest(
        prompt=prompt,
        images=[img],
        metadata={"request_id": request_id, "kind": "rag_vision_index"},
    )
    _log.info(
        "rag_vision_index: start request_id=%s ordinal=%s bytes=%s model=%s",
        request_id,
        ordinal,
        len(data),
        vision_model_name or "(default)",
    )
    try:
        resp = model_manager.call_visual(req, model_name=vision_model_name)
        txt = (resp.content or "").strip()
        out = txt or str(vi["describe_empty"])
        _log.info(
            "rag_vision_index: done request_id=%s ordinal=%s content_chars=%s",
            request_id,
            ordinal,
            len(out),
        )
        return out
    except LLMError as e:
        _log.warning(
            "rag_vision_index: failed request_id=%s ordinal=%s err=%s",
            request_id,
            ordinal,
            e.message,
        )
        return f"{vi['describe_error_prefix']}{e.message}{vi['describe_error_suffix']}"


def _extract_image_blobs_from_run(run: DocxRun) -> list[bytes]:
    """从单个 run 的 DrawingML 中取出嵌入图片二进制。"""
    out: list[bytes] = []
    part = run.part
    for blip in run._element.findall(f".//{qn('a:blip')}"):
        rid = blip.get(qn("r:embed")) or blip.get(qn("r:link"))
        if not rid:
            continue
        try:
            rel = part.related_parts[rid]
        except KeyError:
            continue
        blob = getattr(rel, "blob", None)
        if isinstance(blob, (bytes, bytearray)) and blob:
            out.append(bytes(blob))
    return out


def _render_paragraph_inline(
    paragraph: DocxParagraph,
    *,
    model_manager: ModelManager,
    request_id: str,
    vision_model_name: str | None,
    counters: dict[str, int],
    max_images: int,
    progress_callback: IngestProgressCallback | None = None,
    vision_total: int = 0,
    prog: dict[str, int] | None = None,
) -> str:
    pieces: list[str] = []
    st = prog if prog is not None else {"done": 0}
    vi = _rag_vision_inline_msgs()
    for run in paragraph.runs:
        if run.text:
            pieces.append(run.text)
        for blob in _extract_image_blobs_from_run(run):
            if counters["described"] >= max_images:
                pieces.append(str(vi["skip_over_limit"]))
                counters["skipped_cap"] += 1
                continue
            if len(blob) > _MAX_IMAGE_BYTES:
                pieces.append(str(vi["skip_too_large"]))
                counters["skipped_size"] += 1
                continue
            counters["seen"] += 1
            ordinal = counters["seen"]
            st["done"] += 1
            if progress_callback and vision_total > 0:
                cur = st["done"]
                _emit_progress(
                    progress_callback,
                    {
                        "type": "progress",
                        "stage": "vision",
                        "current": cur,
                        "total": vision_total,
                        "percent": _vision_bar_percent(cur, vision_total),
                        "message": _rag_vision_progress_tpl().format(current=cur, total=vision_total),
                    },
                )
            desc = _describe_one_image(
                model_manager, blob, request_id=request_id, vision_model_name=vision_model_name, ordinal=ordinal
            )
            if "识别失败" in desc:
                counters["errors"] += 1
            counters["described"] += 1
            pieces.append(f"{vi['wrap_desc_prefix']}{desc}{vi['wrap_desc_suffix']}")
    return "".join(pieces).strip()


def _iter_block_items(parent: Any) -> Iterator[DocxParagraph | DocxTable]:
    if isinstance(parent, DocxDocument):
        body = parent.element.body
    elif isinstance(parent, _Cell):
        body = parent._tc
    else:
        return
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield DocxParagraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield DocxTable(child, parent)


def _serialize_table(
    table: DocxTable,
    *,
    model_manager: ModelManager,
    request_id: str,
    vision_model_name: str | None,
    counters: dict[str, int],
    max_images: int,
    progress_callback: IngestProgressCallback | None = None,
    vision_total: int = 0,
    prog: dict[str, int] | None = None,
) -> str:
    rows_out: list[str] = []
    for row in table.rows:
        cells_out: list[str] = []
        for cell in row.cells:
            cell_parts: list[str] = []
            for block in _iter_block_items(cell):
                if isinstance(block, DocxParagraph):
                    t = _render_paragraph_inline(
                        block,
                        model_manager=model_manager,
                        request_id=request_id,
                        vision_model_name=vision_model_name,
                        counters=counters,
                        max_images=max_images,
                        progress_callback=progress_callback,
                        vision_total=vision_total,
                        prog=prog,
                    )
                    if t:
                        cell_parts.append(t)
                elif isinstance(block, DocxTable):
                    nested = _serialize_table(
                        block,
                        model_manager=model_manager,
                        request_id=request_id,
                        vision_model_name=vision_model_name,
                        counters=counters,
                        max_images=max_images,
                        progress_callback=progress_callback,
                        vision_total=vision_total,
                        prog=prog,
                    )
                    if nested:
                        cell_parts.append(nested)
            cells_out.append("\n".join(x for x in cell_parts if x).strip())
        rows_out.append(" | ".join(cells_out))
    return "\n".join(rows_out).strip()


def _docx_count_describable_images(parent: Any, *, max_images: int) -> int:
    """与入库遍历一致：统计将实际送入多模态的嵌入图张数上限（含表格嵌套）。"""
    n = 0
    for block in _iter_block_items(parent):
        if isinstance(block, DocxParagraph):
            for run in block.runs:
                for blob in _extract_image_blobs_from_run(run):
                    if n >= max_images:
                        return n
                    if len(blob) > _MAX_IMAGE_BYTES:
                        continue
                    n += 1
        elif isinstance(block, DocxTable):
            for row in block.rows:
                for cell in row.cells:
                    n += _docx_count_describable_images(cell, max_images=max_images - n)
                    if n >= max_images:
                        return n
    return n


def _enrich_docx(
    path: Path,
    *,
    model_manager: ModelManager,
    request_id: str,
    vision_model_name: str | None,
    max_images: int,
    progress_callback: IngestProgressCallback | None = None,
) -> tuple[str, dict[str, Any]]:
    doc = load_docx(str(path))
    vision_total = _docx_count_describable_images(doc, max_images=max_images)
    prog = {"done": 0}
    _emit_progress(
        progress_callback,
        {
            "type": "progress",
            "stage": "vision",
            "current": 0,
            "total": vision_total,
            "percent": 0,
            "message": f"准备识图（共 {vision_total} 张）",
        },
    )
    counters: dict[str, int] = {
        "seen": 0,
        "described": 0,
        "errors": 0,
        "skipped_size": 0,
        "skipped_cap": 0,
    }
    sections: list[str] = []
    for block in _iter_block_items(doc):
        if isinstance(block, DocxParagraph):
            t = _render_paragraph_inline(
                block,
                model_manager=model_manager,
                request_id=request_id,
                vision_model_name=vision_model_name,
                counters=counters,
                max_images=max_images,
                progress_callback=progress_callback,
                vision_total=vision_total,
                prog=prog,
            )
            if t:
                sections.append(t)
        elif isinstance(block, DocxTable):
            t = _serialize_table(
                block,
                model_manager=model_manager,
                request_id=request_id,
                vision_model_name=vision_model_name,
                counters=counters,
                max_images=max_images,
                progress_callback=progress_callback,
                vision_total=vision_total,
                prog=prog,
            )
            if t:
                sections.append(t)
    text = "\n\n".join(sections).strip()
    stats: dict[str, Any] = {
        "used": True,
        "format": "docx",
        "images_seen": counters["seen"],
        "images_described": counters["described"],
        "multimodal_calls": counters["described"],
        "images_skipped_oversize": counters["skipped_size"],
        "images_skipped_cap": counters["skipped_cap"],
        "vision_errors": counters["errors"],
    }
    if counters["seen"] == 0:
        stats["hint"] = (
            "未在正文/表格段落中解析到 DrawingML 嵌入位图，因此本次没有调用多模态接口。"
            "若文档确有图：可能是链接型图片、仅存在于页眉页脚、或版式特殊；也可尝试 PDF 上传看能否被 pypdf 枚举。"
        )
        _log.info("rag_vision_index: done path=%s format=docx multimodal_calls=0", path.name)
    else:
        _log.info(
            "rag_vision_index: done path=%s format=docx multimodal_calls=%s errors=%s",
            path.name,
            counters["described"],
            counters["errors"],
        )
    return text, stats


def _enrich_pdf(
    path: Path,
    *,
    model_manager: ModelManager,
    request_id: str,
    vision_model_name: str | None,
    max_images: int,
    progress_callback: IngestProgressCallback | None = None,
) -> tuple[str, dict[str, Any]]:
    reader = PdfReader(str(path))
    counters: dict[str, int] = {
        "seen": 0,
        "described": 0,
        "errors": 0,
        "skipped_size": 0,
        "skipped_cap": 0,
    }
    jobs: list[tuple[int, int, bytes]] = []
    truncated = False
    for pi, page in enumerate(reader.pages):
        if len(jobs) >= max_images:
            break
        try:
            imgs = list(page.images)
        except Exception:
            imgs = []
        for ii, imgf in enumerate(imgs):
            if len(jobs) >= max_images:
                counters["skipped_cap"] += 1
                truncated = True
                break
            data = getattr(imgf, "data", None) or b""
            if not isinstance(data, (bytes, bytearray)) or not data:
                continue
            data = bytes(data)
            if len(data) > _MAX_IMAGE_BYTES:
                counters["skipped_size"] += 1
                continue
            jobs.append((pi, ii, data))
        if truncated:
            break
    total_jobs = len(jobs)
    _emit_progress(
        progress_callback,
        {
            "type": "progress",
            "stage": "vision",
            "current": 0,
            "total": total_jobs,
            "percent": 0,
            "message": f"准备识图（共 {total_jobs} 张）",
        },
    )
    page_desc: dict[int, list[str]] = {}
    for idx, (pi, ii, data) in enumerate(jobs):
        cur = idx + 1
        _emit_progress(
            progress_callback,
            {
                "type": "progress",
                "stage": "vision",
                "current": cur,
                "total": total_jobs,
                "percent": _vision_bar_percent(cur, total_jobs),
                "message": f"多模态识图 {cur}/{total_jobs}（第 {pi + 1} 页）",
            },
        )
        counters["seen"] += 1
        ordinal = counters["seen"]
        desc = _describe_one_image(
            model_manager, data, request_id=request_id, vision_model_name=vision_model_name, ordinal=ordinal
        )
        if "识别失败" in desc:
            counters["errors"] += 1
        counters["described"] += 1
        page_desc.setdefault(pi, []).append(f"[第{pi + 1}页插图 {ii + 1}]\n{desc}")

    page_blobs: list[str] = []
    for pi, page in enumerate(reader.pages):
        try:
            t = (page.extract_text() or "").strip()
        except Exception:
            t = ""
        extras = page_desc.get(pi) or []
        join_img = "\n\n".join(extras) if extras else ""
        if t and join_img:
            chunk = (t + "\n\n" + join_img).strip()
        else:
            chunk = (t or join_img).strip()
        if chunk:
            page_blobs.append(chunk)
    text = "\n\n".join(page_blobs).strip()
    stats: dict[str, Any] = {
        "used": True,
        "format": "pdf",
        "images_seen": counters["seen"],
        "images_described": counters["described"],
        "multimodal_calls": counters["described"],
        "images_skipped_oversize": counters["skipped_size"],
        "images_skipped_cap": counters["skipped_cap"],
        "vision_errors": counters["errors"],
    }
    if counters["seen"] == 0:
        stats["hint"] = (
            "pypdf 在本 PDF 中未枚举到可读取的嵌入位图对象，因此没有调用多模态。"
            "常见原因：扫描件整页只是一张「大背景图」但生成方式不在 XObject 列表、纯文字 PDF、或图片经特殊压缩。"
            "可尝试另存为 DOCX、或用带嵌入图的测试 PDF 验证。"
        )
        _log.info("rag_vision_index: done path=%s format=pdf multimodal_calls=0", path.name)
    else:
        _log.info(
            "rag_vision_index: done path=%s format=pdf multimodal_calls=%s errors=%s",
            path.name,
            counters["described"],
            counters["errors"],
        )
    return text, stats


def enrich_document_text_for_indexing(
    path: Path,
    *,
    model_manager: ModelManager,
    request_id: str,
    vision_model_name: str | None = None,
    max_images: int = _DEFAULT_MAX_IMAGES,
    progress_callback: IngestProgressCallback | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    返回 `(全文, stats)`。对 `.txt`/`.md` 不做识图，仅原样读文本并标记 `used:false`。
    """
    suf = path.suffix.lower()
    if suf in (".txt", ".md"):
        _emit_progress(
            progress_callback,
            {
                "type": "progress",
                "stage": "vision",
                "current": 0,
                "total": 0,
                "percent": 10,
                "message": "纯文本：跳过识图",
            },
        )
        raw = path.read_text(encoding="utf-8", errors="ignore")
        return raw, {
            "used": False,
            "reason": "no_images_in_plaintext",
            "format": suf.lstrip("."),
            "multimodal_calls": 0,
            "hint": "纯文本格式没有「嵌入图」通道，不会调用多模态；若需识图请用 PDF/DOCX。",
        }
    if suf == ".docx":
        return _enrich_docx(
            path,
            model_manager=model_manager,
            request_id=request_id,
            vision_model_name=vision_model_name,
            max_images=max_images,
            progress_callback=progress_callback,
        )
    if suf == ".pdf":
        return _enrich_pdf(
            path,
            model_manager=model_manager,
            request_id=request_id,
            vision_model_name=vision_model_name,
            max_images=max_images,
            progress_callback=progress_callback,
        )
    return "", {"used": False, "reason": "unsupported", "format": suf, "multimodal_calls": 0}
