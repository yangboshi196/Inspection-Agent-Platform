"""合并 content 相同的 report_template，统一 binding / plan / report 引用。"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import datetime
from typing import Any

from . import db
from .template_schema import template_effective_content

logger = logging.getLogger(__name__)

_DEDUPED = False
_LOCK = threading.Lock()


def _display_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _content_fingerprint(row: dict[str, Any]) -> str:
    content = template_effective_content(row)
    if content:
        normalized = "\n".join(line.rstrip() for line in content.splitlines()).strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    name = str(row.get("name") or "").strip().lower()
    filename = str(row.get("filename") or "").strip().lower()
    return f"namefile:{name}|{filename}"


def _canonical_score(row: dict[str, Any]) -> tuple[int, str]:
    tid = str(row.get("template_id") or "")
    score = 0
    if tid.startswith("tpl-"):
        score += 100
    storage = str(row.get("storage_relpath") or "")
    if storage.startswith("report_templates/"):
        score += 50
    if template_effective_content(row):
        score += 20
    if str(row.get("size_label") or "").strip():
        score += 10
    if str(row.get("description") or "").strip():
        score += 5
    # 同分取较早创建的，保持稳定
    created = str(row.get("created_at") or "")
    return score, created


def _pick_canonical(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return max(rows, key=lambda r: (_canonical_score(r), str(r.get("template_id") or "")))


def dedupe_report_templates() -> dict[str, int]:
    """按模版正文去重；返回 merged_groups / updated_bindings / deleted_templates。"""
    global _DEDUPED
    if _DEDUPED:
        return {"merged_groups": 0, "updated_bindings": 0, "deleted_templates": 0}

    with _LOCK:
        if _DEDUPED:
            return {"merged_groups": 0, "updated_bindings": 0, "deleted_templates": 0}

        stats = {"merged_groups": 0, "updated_bindings": 0, "deleted_templates": 0}
        conn = db.get_connection()
        try:
            raw_rows = conn.execute("SELECT * FROM report_template ORDER BY created_at ASC").fetchall()
            if len(raw_rows) <= 1:
                _DEDUPED = True
                return stats

            rows = [db.template_row_to_api(r) for r in raw_rows]
            groups: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                fp = _content_fingerprint(row)
                groups.setdefault(fp, []).append(row)

            now = _display_now()
            for fp, group in groups.items():
                if len(group) <= 1:
                    continue
                canonical = _pick_canonical(group)
                keep_id = str(canonical["template_id"])
                dup_ids = [str(r["template_id"]) for r in group if str(r["template_id"]) != keep_id]
                if not dup_ids:
                    continue

                stats["merged_groups"] += 1
                for dup_id in dup_ids:
                    cur = conn.execute(
                        "UPDATE work_report_template_binding SET template_id = ?, updated_at = ? WHERE template_id = ?",
                        (keep_id, now, dup_id),
                    )
                    stats["updated_bindings"] += int(getattr(cur, "rowcount", 0) or 0)

                    conn.execute(
                        "UPDATE report_plan SET template_id = ?, updated_at = ? WHERE template_id = ?",
                        (keep_id, now, dup_id),
                    )
                    conn.execute(
                        "UPDATE inspection_report SET template_id = ?, template_name = ? WHERE template_id = ?",
                        (keep_id, str(canonical.get("name") or ""), dup_id),
                    )
                    conn.execute("DELETE FROM report_template WHERE template_id = ?", (dup_id,))
                    stats["deleted_templates"] += 1

                logger.info(
                    "deduped templates fingerprint=%s keep=%s removed=%s",
                    fp[:12],
                    keep_id,
                    dup_ids,
                )

            conn.commit()
            _DEDUPED = True
        except Exception:
            conn.rollback()
            logger.exception("report template dedupe failed")
            raise
        finally:
            conn.close()

        if stats["deleted_templates"]:
            logger.info("report template dedupe: %s", stats)
        return stats
