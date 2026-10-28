"""报告模版文件上传：解析文本、存储原文件。"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from inspection_platform.app.config import get_settings

from .template_text import (
    DEFAULT_WORK_REPORT_TEMPLATE,
    extract_template_text,
    normalize_template_filename,
)


def _display_now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M")


def format_size_label(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def _storage_root() -> Path:
    root = get_settings().data_path / "report_templates"
    root.mkdir(parents=True, exist_ok=True)
    return root


def store_template_file(*, template_id: str, filename: str, raw: bytes) -> str:
    ext = Path(filename).suffix.lower() or ".txt"
    rel_dir = f"report_templates/{template_id}"
    abs_dir = _storage_root() / template_id
    abs_dir.mkdir(parents=True, exist_ok=True)
    rel_path = f"{rel_dir}/original{ext}"
    (abs_dir / f"original{ext}").write_bytes(raw)
    return rel_path


def build_template_fields_from_upload(
    *,
    file_content: bytes,
    original_filename: str,
    template_id: str | None = None,
    name: str | None = None,
    description: str = "",
) -> dict[str, Any]:
    filename = normalize_template_filename(original_filename)
    content = extract_template_text(filename=filename, raw=file_content)
    if not content.strip():
        content = DEFAULT_WORK_REPORT_TEMPLATE
    tid = (template_id or "").strip() or f"tpl-{uuid.uuid4().hex[:10]}"
    display_name = (name or "").strip() or Path(filename).stem or "报告模版"
    now = _display_now()
    storage_relpath = store_template_file(template_id=tid, filename=filename, raw=file_content)
    return {
        "template_id": tid,
        "name": display_name,
        "description": (description or "").strip(),
        "filename": filename,
        "content": content,
        "storage_relpath": storage_relpath,
        "size_label": format_size_label(len(file_content)),
        "uploaded_at": now,
        "created_at": now,
        "updated_at": now,
    }
