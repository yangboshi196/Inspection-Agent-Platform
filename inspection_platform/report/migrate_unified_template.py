"""将历史 work_report_template_binding 内嵌模版迁移到 report_template 统一表。"""

from __future__ import annotations

import logging
import threading
from typing import Any

from . import db
from .template_schema import template_row_to_api
from .template_schema import template_effective_content

logger = logging.getLogger(__name__)

_MIGRATED = False
_LOCK = threading.Lock()


def _row_get(row: Any, key: str, default: str = "") -> str:
    if row is None:
        return default
    keys = row.keys() if hasattr(row, "keys") else ()
    if key not in keys:
        return default
    return str(row[key] or default)


def migrate_legacy_binding_templates() -> None:
    """一次性：binding 表中的 content/filename 等迁入 report_template。"""
    global _MIGRATED
    if _MIGRATED:
        return

    with _LOCK:
        if _MIGRATED:
            return
        conn = db.get_connection()
        try:
            keys = conn.execute("SELECT * FROM work_report_template_binding LIMIT 1").fetchone()
            if keys is None:
                _MIGRATED = True
                return
            row_keys = keys.keys() if hasattr(keys, "keys") else ()
            if "content" not in row_keys:
                _MIGRATED = True
                return

            rows = conn.execute(
                """
SELECT work_id, template_id, template_name, filename, storage_relpath, content, created_at, updated_at
FROM work_report_template_binding
WHERE template_id IS NOT NULL AND template_id != ''
"""
            ).fetchall()
            now_cols = conn.execute("SELECT * FROM report_template LIMIT 1").fetchone()
            tpl_keys = now_cols.keys() if now_cols is not None and hasattr(now_cols, "keys") else ()

            for row in rows:
                tid = _row_get(row, "template_id").strip()
                if not tid:
                    continue
                content = _row_get(row, "content")
                if not content.strip():
                    continue
                exists = conn.execute(
                    "SELECT * FROM report_template WHERE template_id = ?",
                    (tid,),
                ).fetchone()
                if exists:
                    if "content" in tpl_keys and not _row_get(exists, "content").strip():
                        conn.execute(
                            """
UPDATE report_template
SET content = ?, filename = ?, storage_relpath = ?, updated_at = ?
WHERE template_id = ?
""",
                            (
                                content,
                                _row_get(row, "filename"),
                                _row_get(row, "storage_relpath"),
                                _row_get(row, "updated_at"),
                                tid,
                            ),
                        )
                    continue

                name = _row_get(row, "template_name") or "报告模版"
                stamp = _row_get(row, "created_at") or _row_get(row, "updated_at")
                insert_cols = [
                    "template_id",
                    "name",
                    "description",
                    "filename",
                    "content",
                    "storage_relpath",
                    "uploaded_at",
                    "size_label",
                    "created_at",
                    "updated_at",
                ]
                values = [
                    tid,
                    name,
                    "",
                    _row_get(row, "filename"),
                    content,
                    _row_get(row, "storage_relpath"),
                    stamp,
                    "",
                    stamp,
                    _row_get(row, "updated_at") or stamp,
                ]
                placeholders = ", ".join("?" for _ in insert_cols)
                conn.execute(
                    f"INSERT INTO report_template ({', '.join(insert_cols)}) VALUES ({placeholders})",
                    values,
                )
            conn.commit()
            _MIGRATED = True
            logger.info("migrated legacy work report templates into report_template")
        except Exception:
            conn.rollback()
            logger.exception("legacy template migration failed")
            raise
        finally:
            conn.close()


def fetch_template_map(conn: Any, template_ids: list[str]) -> dict[str, dict[str, Any]]:
    ids = [t.strip() for t in template_ids if t and t.strip()]
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM report_template WHERE template_id IN ({placeholders})",
        ids,
    ).fetchall()
    return {str(r["template_id"]): template_row_to_api(r) for r in rows}
