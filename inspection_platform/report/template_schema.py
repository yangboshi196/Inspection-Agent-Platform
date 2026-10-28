"""报告模版 `report_template` 统一字段定义（全平台唯一参数表）。"""

from __future__ import annotations

from typing import Any

REPORT_TEMPLATE_API_FIELDS = (
    "template_id",
    "name",
    "description",
    "filename",
    "content",
    "storage_relpath",
    "size_label",
    "uploaded_at",
    "created_at",
    "updated_at",
)

REPORT_TEMPLATE_PATCH_FIELDS = (
    "name",
    "description",
    "filename",
    "content",
    "uploaded_at",
    "size_label",
)

REPORT_TEMPLATE_DB_COLUMNS = {
    "name": "name",
    "description": "description",
    "filename": "filename",
    "content": "content",
    "storage_relpath": "storage_relpath",
    "uploaded_at": "uploaded_at",
    "size_label": "size_label",
}


def template_row_to_api(row: Any) -> dict[str, Any]:
    keys = row.keys() if hasattr(row, "keys") else ()
    return {
        "template_id": str(row["template_id"]),
        "name": str(row["name"]),
        "description": str(row["description"] if "description" in keys else ""),
        "filename": str(row["filename"] or ""),
        "content": str(row["content"] if "content" in keys else ""),
        "storage_relpath": str(row["storage_relpath"] if "storage_relpath" in keys else ""),
        "size_label": str(row["size_label"] or ""),
        "uploaded_at": str(row["uploaded_at"] or ""),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def template_effective_content(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    return str(row.get("content") or "").strip()
