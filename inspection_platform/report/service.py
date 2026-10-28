"""报告模版 / 计划 / 巡检报告 CRUD 与内置种子。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _display_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _builtin_seed_path() -> Path:
    return Path(__file__).resolve().parent / "builtin_seed.json"


class ReportService:
    def ensure_ready(self) -> None:
        from .bootstrap import ensure_report_ready

        ensure_report_ready()

    # --- templates ---

    def list_templates(
        self,
        *,
        q: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        self.ensure_ready()
        limit = max(1, min(500, limit))
        offset = max(0, offset)
        where: list[str] = []
        params: list[Any] = []
        if q and q.strip():
            where.append(
                "(template_id LIKE ? OR name LIKE ? OR filename LIKE ? OR description LIKE ?)"
            )
            pat = f"%{q.strip()}%"
            params.extend([pat, pat, pat, pat])
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        conn = db.get_connection()
        try:
            total = int(
                conn.execute(f"SELECT COUNT(*) AS c FROM report_template {clause}", params).fetchone()["c"]
            )
            rows = conn.execute(
                f"SELECT * FROM report_template {clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            bind_counts = self._template_binding_counts(conn)
        finally:
            conn.close()
        return [self._template_api_with_meta(r, bind_counts) for r in rows], total

    def _template_binding_counts(self, conn: Any) -> dict[str, int]:
        rows = conn.execute(
            """
SELECT template_id, COUNT(*) AS c
FROM work_report_template_binding
WHERE template_id IS NOT NULL AND template_id != ''
GROUP BY template_id
"""
        ).fetchall()
        out: dict[str, int] = {}
        for r in rows:
            out[str(r["template_id"])] = int(r["c"])
        return out

    def _template_api_with_meta(self, row: Any, bind_counts: dict[str, int]) -> dict[str, Any]:
        api = db.template_row_to_api(row)
        tid = str(api.get("template_id") or "")
        api["bound_work_count"] = bind_counts.get(tid, 0)
        return api

    def get_template(self, template_id: str) -> dict[str, Any] | None:
        self.ensure_ready()
        conn = db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM report_template WHERE template_id = ?",
                (template_id.strip(),),
            ).fetchone()
            if not row:
                return None
            bind_counts = self._template_binding_counts(conn)
        finally:
            conn.close()
        return self._template_api_with_meta(row, bind_counts)

    def get_template_by_name(self, name: str) -> dict[str, Any] | None:
        """按模版名称精确匹配（兼容误把 name 当 id 的旧调用）。"""
        self.ensure_ready()
        key = name.strip()
        if not key:
            return None
        conn = db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM report_template WHERE name = ? ORDER BY updated_at DESC LIMIT 1",
                (key,),
            ).fetchone()
            if not row:
                return None
            bind_counts = self._template_binding_counts(conn)
        finally:
            conn.close()
        return self._template_api_with_meta(row, bind_counts)

    def resolve_template(self, template_id_or_name: str) -> dict[str, Any] | None:
        key = template_id_or_name.strip()
        if not key:
            return None
        row = self.get_template(key)
        if row:
            return row
        return self.get_template_by_name(key)

    def create_template(
        self,
        *,
        template_id: str | None,
        name: str,
        description: str = "",
        filename: str = "",
        content: str = "",
        storage_relpath: str = "",
        uploaded_at: str | None = None,
        size_label: str = "",
    ) -> dict[str, Any]:
        self.ensure_ready()
        tid = (template_id or "").strip() or f"tpl-{uuid.uuid4().hex[:10]}"
        now = _display_now()
        stamp = uploaded_at or now
        body_content = (content or "").strip()
        conn = db.get_connection()
        try:
            conn.execute(
                """
INSERT INTO report_template (
    template_id, name, description, filename, content, storage_relpath,
    uploaded_at, size_label, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                (
                    tid,
                    name.strip(),
                    (description or "").strip(),
                    filename or "",
                    body_content,
                    storage_relpath or "",
                    stamp,
                    size_label or "",
                    stamp,
                    stamp,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            conn.rollback()
            raise ValueError("模版 id 已存在") from e
        finally:
            conn.close()
        return self.get_template(tid) or {}

    def create_template_from_upload(
        self,
        *,
        file_content: bytes,
        original_filename: str,
        template_id: str | None = None,
        name: str | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        from .template_upload import build_template_fields_from_upload

        fields = build_template_fields_from_upload(
            file_content=file_content,
            original_filename=original_filename,
            template_id=template_id,
            name=name,
            description=description,
        )
        fields.pop("created_at", None)
        fields.pop("updated_at", None)
        return self.create_template(**fields)

    def update_template(self, template_id: str, **fields: Any) -> dict[str, Any] | None:
        self.ensure_ready()
        tid = template_id.strip()
        if not self.get_template(tid):
            return None
        from .template_schema import REPORT_TEMPLATE_DB_COLUMNS

        mapping = dict(REPORT_TEMPLATE_DB_COLUMNS)
        sets: list[str] = []
        params: list[Any] = []
        for key, col in mapping.items():
            if key not in fields or fields[key] is None:
                continue
            sets.append(f"{col} = ?")
            params.append(str(fields[key]))
        if not sets:
            return self.get_template(tid)
        sets.append("updated_at = ?")
        params.append(_display_now())
        params.append(tid)
        conn = db.get_connection()
        try:
            conn.execute(f"UPDATE report_template SET {', '.join(sets)} WHERE template_id = ?", params)
            conn.commit()
        finally:
            conn.close()
        return self.get_template(tid)

    def delete_template(self, template_id: str) -> bool:
        self.ensure_ready()
        tid = template_id.strip()
        conn = db.get_connection()
        try:
            bound = conn.execute(
                "SELECT COUNT(*) AS c FROM work_report_template_binding WHERE template_id = ?",
                (tid,),
            ).fetchone()
            if bound and int(bound["c"]) > 0:
                raise ValueError("模版仍被巡检业务绑定，请先解除绑定后再删除")
            conn.execute(
                "UPDATE report_plan SET template_id = NULL, updated_at = ? WHERE template_id = ?",
                (_display_now(), tid),
            )
            cur = conn.execute("DELETE FROM report_template WHERE template_id = ?", (tid,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # --- plans ---

    def list_plans(
        self,
        *,
        frequency: str | None = None,
        enabled: bool | None = None,
        q: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        self.ensure_ready()
        limit = max(1, min(500, limit))
        offset = max(0, offset)
        where: list[str] = []
        params: list[Any] = []
        if frequency:
            where.append("frequency = ?")
            params.append(frequency.strip())
        if enabled is not None:
            where.append("enabled = ?")
            params.append(1 if enabled else 0)
        if q and q.strip():
            where.append("(plan_id LIKE ? OR name LIKE ? OR content_prompt LIKE ?)")
            pat = f"%{q.strip()}%"
            params.extend([pat, pat, pat])
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        conn = db.get_connection()
        try:
            total = int(conn.execute(f"SELECT COUNT(*) AS c FROM report_plan {clause}", params).fetchone()["c"])
            rows = conn.execute(
                f"SELECT * FROM report_plan {clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        finally:
            conn.close()
        return [db.plan_row_to_api(r) for r in rows], total

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        self.ensure_ready()
        conn = db.get_connection()
        try:
            row = conn.execute("SELECT * FROM report_plan WHERE plan_id = ?", (plan_id.strip(),)).fetchone()
        finally:
            conn.close()
        return db.plan_row_to_api(row) if row else None

    def create_plan(
        self,
        *,
        plan_id: str | None,
        name: str,
        enabled: bool = True,
        frequency: str = "daily",
        work_ids: list[str] | None = None,
        content_prompt: str = "",
        template_id: str | None = None,
        weekday: int | None = None,
        month_day: int | None = None,
        generate_time: str = "08:00",
    ) -> dict[str, Any]:
        self.ensure_ready()
        pid = (plan_id or "").strip() or f"plan-{uuid.uuid4().hex[:10]}"
        freq = frequency.strip().lower()
        if freq not in ("daily", "weekly", "monthly"):
            raise ValueError("frequency 须为 daily | weekly | monthly")
        now = _display_now()
        conn = db.get_connection()
        try:
            conn.execute(
                """
INSERT INTO report_plan (
    plan_id, name, enabled, frequency, work_ids_json, content_prompt,
    template_id, weekday, month_day, generate_time, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                (
                    pid,
                    name.strip(),
                    1 if enabled else 0,
                    freq,
                    json.dumps(work_ids or [], ensure_ascii=False),
                    content_prompt or "",
                    template_id,
                    weekday,
                    month_day,
                    generate_time or "08:00",
                    now,
                    now,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            conn.rollback()
            raise ValueError("计划 id 已存在") from e
        finally:
            conn.close()
        return self.get_plan(pid) or {}

    def update_plan(self, plan_id: str, **fields: Any) -> dict[str, Any] | None:
        self.ensure_ready()
        pid = plan_id.strip()
        if not self.get_plan(pid):
            return None
        mapping: dict[str, str] = {
            "name": "name",
            "enabled": "enabled",
            "frequency": "frequency",
            "content_prompt": "content_prompt",
            "template_id": "template_id",
            "weekday": "weekday",
            "month_day": "month_day",
            "generate_time": "generate_time",
        }
        sets: list[str] = []
        params: list[Any] = []
        if "work_ids" in fields and fields["work_ids"] is not None:
            sets.append("work_ids_json = ?")
            params.append(json.dumps(fields["work_ids"], ensure_ascii=False))
        for key, col in mapping.items():
            if key not in fields:
                continue
            val = fields[key]
            if val is None and key == "template_id":
                sets.append(f"{col} = NULL")
                continue
            if val is None:
                continue
            if key == "enabled":
                val = 1 if bool(val) else 0
            elif key == "frequency":
                val = str(val).strip().lower()
                if val not in ("daily", "weekly", "monthly"):
                    raise ValueError("frequency 须为 daily | weekly | monthly")
            sets.append(f"{col} = ?")
            params.append(val)
        if not sets:
            return self.get_plan(pid)
        sets.append("updated_at = ?")
        params.append(_display_now())
        params.append(pid)
        conn = db.get_connection()
        try:
            conn.execute(f"UPDATE report_plan SET {', '.join(sets)} WHERE plan_id = ?", params)
            conn.commit()
        finally:
            conn.close()
        return self.get_plan(pid)

    def toggle_plan(self, plan_id: str) -> dict[str, Any] | None:
        plan = self.get_plan(plan_id)
        if not plan:
            return None
        return self.update_plan(plan_id, enabled=not plan["enabled"])

    def delete_plan(self, plan_id: str) -> bool:
        self.ensure_ready()
        conn = db.get_connection()
        try:
            cur = conn.execute("DELETE FROM report_plan WHERE plan_id = ?", (plan_id.strip(),))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def generate_from_plan(self, plan_id: str, *, source: str = "manual") -> dict[str, Any]:
        """按计划生成巡检报告草稿并入库。"""
        from inspection_platform.deps import get_model_manager
        from inspection_platform.document.region_meta import RegionMetaService
        from inspection_platform.inspection_work.service import InspectionWorkService
        from inspection_platform.report.generator import build_report_from_plan

        plan = self.get_plan(plan_id)
        if not plan:
            raise ValueError("plan not found")

        template = None
        tid = plan.get("template_id")
        if tid:
            template = self.get_template(str(tid))

        rw = InspectionWorkService()
        rw.ensure_ready()
        works_catalog, _ = rw.list_all(limit=500, offset=0)

        region_svc = RegionMetaService()
        region_svc.ensure_ready()
        regions = region_svc.list_regions()
        region_names = {str(r.get("id") or ""): str(r.get("name") or "") for r in regions}

        src = "scheduled" if str(source).strip().lower() == "scheduled" else "manual"
        try:
            mm = get_model_manager()
        except Exception:
            mm = None

        draft = build_report_from_plan(
            plan,
            works_catalog=works_catalog,
            template=template,
            region_names=region_names,
            source=src,
            model_manager=mm,
        )
        draft.pop("created_at", None)
        draft.pop("updated_at", None)
        return self.create_report(**draft)

    # --- inspection reports ---

    def list_reports(
        self,
        *,
        status: str | None = None,
        frequency: str | None = None,
        plan_id: str | None = None,
        q: str | None = None,
        limit: int = 200,
        offset: int = 0,
        subscribed_work_ids: set[str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        self.ensure_ready()
        limit = max(1, min(500, limit))
        offset = max(0, offset)
        where: list[str] = []
        params: list[Any] = []
        if status:
            where.append("status = ?")
            params.append(status.strip())
        if frequency:
            where.append("frequency = ?")
            params.append(frequency.strip())
        if plan_id:
            where.append("plan_id = ?")
            params.append(plan_id.strip())
        if q and q.strip():
            where.append("(report_id LIKE ? OR title LIKE ? OR summary LIKE ? OR plan_name LIKE ?)")
            pat = f"%{q.strip()}%"
            params.extend([pat, pat, pat, pat])
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        conn = db.get_connection()
        try:
            if subscribed_work_ids is not None:
                rows = conn.execute(
                    f"SELECT * FROM inspection_report {clause} ORDER BY updated_at DESC",
                    params,
                ).fetchall()
            else:
                total = int(
                    conn.execute(f"SELECT COUNT(*) AS c FROM inspection_report {clause}", params).fetchone()["c"]
                )
                rows = conn.execute(
                    f"SELECT * FROM inspection_report {clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                    [*params, limit, offset],
                ).fetchall()
        finally:
            conn.close()

        items = [db.report_row_to_api(r) for r in rows]
        if subscribed_work_ids is not None:
            if not subscribed_work_ids:
                return [], 0
            from .push_subscription import ReportPushSubscriptionService

            items = [
                item
                for item in items
                if ReportPushSubscriptionService.report_matches_work_ids(
                    [str(w) for w in (item.get("work_ids") or [])],
                    subscribed_work_ids,
                )
            ]
            total = len(items)
            return items[offset : offset + limit], total

        return items, total

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        self.ensure_ready()
        conn = db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM inspection_report WHERE report_id = ?",
                (report_id.strip(),),
            ).fetchone()
        finally:
            conn.close()
        return db.report_row_to_api(row) if row else None

    def create_report(
        self,
        *,
        report_id: str | None = None,
        title: str,
        period: str = "",
        frequency: str = "weekly",
        work_ids: list[str] | None = None,
        status: str = "draft",
        source: str = "manual",
        content_prompt: str = "",
        plan_id: str | None = None,
        plan_name: str | None = None,
        template_id: str | None = None,
        template_name: str | None = None,
        summary: str = "",
        sections: list[dict[str, Any]] | None = None,
        full_text: str = "",
    ) -> dict[str, Any]:
        self.ensure_ready()
        rid = (report_id or "").strip() or f"rep-{uuid.uuid4().hex[:10]}"
        now = _display_now()
        conn = db.get_connection()
        try:
            conn.execute(
                """
INSERT INTO inspection_report (
    report_id, plan_id, plan_name, title, period, frequency, work_ids_json,
    status, source, content_prompt, template_id, template_name,
    summary, sections_json, full_text, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                (
                    rid,
                    plan_id,
                    plan_name,
                    title.strip(),
                    period or "",
                    frequency,
                    json.dumps(work_ids or [], ensure_ascii=False),
                    status,
                    source,
                    content_prompt or "",
                    template_id,
                    template_name,
                    summary or "",
                    json.dumps(sections or [], ensure_ascii=False),
                    full_text or "",
                    now,
                    now,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            conn.rollback()
            raise ValueError("报告 id 已存在") from e
        finally:
            conn.close()
        return self.get_report(rid) or {}

    def update_report(self, report_id: str, **fields: Any) -> dict[str, Any] | None:
        self.ensure_ready()
        rid = report_id.strip()
        if not self.get_report(rid):
            return None
        mapping: dict[str, str] = {
            "title": "title",
            "period": "period",
            "frequency": "frequency",
            "status": "status",
            "source": "source",
            "content_prompt": "content_prompt",
            "plan_id": "plan_id",
            "plan_name": "plan_name",
            "template_id": "template_id",
            "template_name": "template_name",
            "summary": "summary",
            "full_text": "full_text",
        }
        sets: list[str] = []
        params: list[Any] = []
        if "work_ids" in fields and fields["work_ids"] is not None:
            sets.append("work_ids_json = ?")
            params.append(json.dumps(fields["work_ids"], ensure_ascii=False))
        if "sections" in fields and fields["sections"] is not None:
            sets.append("sections_json = ?")
            params.append(json.dumps(fields["sections"], ensure_ascii=False))
        for key, col in mapping.items():
            if key not in fields:
                continue
            val = fields[key]
            if val is None and key in ("plan_id", "plan_name", "template_id", "template_name"):
                sets.append(f"{col} = NULL")
                continue
            if val is None:
                continue
            sets.append(f"{col} = ?")
            params.append(val)
        if not sets:
            return self.get_report(rid)
        sets.append("updated_at = ?")
        params.append(_display_now())
        params.append(rid)
        conn = db.get_connection()
        try:
            conn.execute(f"UPDATE inspection_report SET {', '.join(sets)} WHERE report_id = ?", params)
            conn.commit()
        finally:
            conn.close()
        return self.get_report(rid)

    def publish_report(self, report_id: str) -> dict[str, Any] | None:
        report = self.get_report(report_id)
        if not report:
            return None
        if report["status"] == "published":
            return report
        return self.update_report(report_id, status="published")

    def delete_report(self, report_id: str) -> bool:
        self.ensure_ready()
        conn = db.get_connection()
        try:
            cur = conn.execute("DELETE FROM inspection_report WHERE report_id = ?", (report_id.strip(),))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def seed_builtin(self) -> dict[str, int]:
        self.ensure_ready()
        path = _builtin_seed_path()
        if not path.is_file():
            return {"templates": 0, "plans": 0, "reports": 0}
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"templates": 0, "plans": 0, "reports": 0}

        counts = {"templates": 0, "plans": 0, "reports": 0}
        conn = db.get_connection()
        try:
            for item in raw.get("templates") or []:
                if not isinstance(item, dict):
                    continue
                tid = str(item.get("template_id") or "").strip()
                if not tid:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM report_template WHERE template_id = ?",
                    (tid,),
                ).fetchone()
                if exists:
                    continue
                now = str(item.get("updated_at") or item.get("created_at") or _display_now())
                content = str(item.get("content") or item.get("outline") or "")
                conn.execute(
                    """
INSERT INTO report_template (
    template_id, name, description, filename, content, storage_relpath,
    uploaded_at, size_label, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                    (
                        tid,
                        str(item.get("name") or ""),
                        str(item.get("description") or ""),
                        str(item.get("filename") or ""),
                        content,
                        str(item.get("storage_relpath") or ""),
                        str(item.get("uploaded_at") or now),
                        str(item.get("size_label") or ""),
                        str(item.get("created_at") or now),
                        str(item.get("updated_at") or now),
                    ),
                )
                counts["templates"] += 1

            for item in raw.get("plans") or []:
                if not isinstance(item, dict):
                    continue
                pid = str(item.get("plan_id") or "").strip()
                if not pid:
                    continue
                exists = conn.execute("SELECT 1 FROM report_plan WHERE plan_id = ?", (pid,)).fetchone()
                if exists:
                    continue
                now = str(item.get("updated_at") or item.get("created_at") or _display_now())
                work_ids = item.get("work_ids") or []
                if not isinstance(work_ids, list):
                    work_ids = []
                conn.execute(
                    """
INSERT INTO report_plan (
    plan_id, name, enabled, frequency, work_ids_json, content_prompt,
    template_id, weekday, month_day, generate_time, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                    (
                        pid,
                        str(item.get("name") or ""),
                        1 if item.get("enabled", True) else 0,
                        str(item.get("frequency") or "daily"),
                        json.dumps(work_ids, ensure_ascii=False),
                        str(item.get("content_prompt") or ""),
                        item.get("template_id"),
                        item.get("weekday"),
                        item.get("month_day"),
                        str(item.get("generate_time") or "08:00"),
                        str(item.get("created_at") or now),
                        str(item.get("updated_at") or now),
                    ),
                )
                counts["plans"] += 1

            for item in raw.get("reports") or []:
                if not isinstance(item, dict):
                    continue
                rid = str(item.get("report_id") or "").strip()
                if not rid:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM inspection_report WHERE report_id = ?",
                    (rid,),
                ).fetchone()
                if exists:
                    continue
                now = str(item.get("updated_at") or item.get("created_at") or _display_now())
                work_ids = item.get("work_ids") or []
                sections = item.get("sections") or []
                if not isinstance(work_ids, list):
                    work_ids = []
                if not isinstance(sections, list):
                    sections = []
                conn.execute(
                    """
INSERT INTO inspection_report (
    report_id, plan_id, plan_name, title, period, frequency, work_ids_json,
    status, source, content_prompt, template_id, template_name,
    summary, sections_json, full_text, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                    (
                        rid,
                        item.get("plan_id"),
                        item.get("plan_name"),
                        str(item.get("title") or ""),
                        str(item.get("period") or ""),
                        str(item.get("frequency") or "weekly"),
                        json.dumps(work_ids, ensure_ascii=False),
                        str(item.get("status") or "draft"),
                        str(item.get("source") or "manual"),
                        str(item.get("content_prompt") or ""),
                        item.get("template_id"),
                        item.get("template_name"),
                        str(item.get("summary") or ""),
                        json.dumps(sections, ensure_ascii=False),
                        str(item.get("full_text") or ""),
                        str(item.get("created_at") or now),
                        str(item.get("updated_at") or now),
                    ),
                )
                counts["reports"] += 1

            conn.commit()
        finally:
            conn.close()
        return counts
