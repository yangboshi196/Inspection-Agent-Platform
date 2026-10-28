"""巡检业务 ↔ 报告模版绑定（仅引用 report_template，不重复存模版正文）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from inspection_platform.inspection_work.service import InspectionWorkService

from . import db
from .migrate_unified_template import fetch_template_map
from .template_schema import template_effective_content
from .service import ReportService


def _display_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _unique_work_ids(work_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in work_ids:
        wid = str(raw).strip()
        if not wid or wid in seen:
            continue
        seen.add(wid)
        out.append(wid)
    return out


def _ensure_saved_works(work_ids: list[str]) -> None:
    work_svc = InspectionWorkService()
    work_svc.ensure_ready()
    for wid in work_ids:
        if not work_svc.get(wid):
            raise ValueError(f"巡检业务 {wid} 不存在，请先保存业务后再绑定模版")


def _binding_row_with_template(row: Any, template_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    tid = str(row["template_id"] or "")
    tpl = template_map.get(tid)
    return db.work_template_binding_row_to_api(row, tpl)


class WorkReportTemplateBindingService:
    """业务级报告模版绑定；模版字段统一在 report_template。"""

    def ensure_ready(self) -> None:
        from .bootstrap import ensure_report_ready

        ensure_report_ready()

    def list_bindings(self) -> list[dict[str, Any]]:
        self.ensure_ready()
        conn = db.get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM work_report_template_binding ORDER BY updated_at DESC"
            ).fetchall()
            template_map = fetch_template_map(
                conn,
                [str(r["template_id"] or "") for r in rows],
            )
        finally:
            conn.close()
        return [_binding_row_with_template(r, template_map) for r in rows]

    def get_binding(self, work_id: str) -> dict[str, Any] | None:
        self.ensure_ready()
        wid = work_id.strip()
        if not wid:
            return None
        conn = db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM work_report_template_binding WHERE work_id = ?",
                (wid,),
            ).fetchone()
            if not row:
                return None
            template_map = fetch_template_map(conn, [str(row["template_id"] or "")])
        finally:
            conn.close()
        return _binding_row_with_template(row, template_map)

    def get_template_for_work(self, work_id: str) -> dict[str, Any] | None:
        """业务执行完成后生成报告时调用。"""
        binding = self.get_binding(work_id)
        if not binding or not binding.get("enabled"):
            return None
        tid = (binding.get("template_id") or "").strip()
        if not tid:
            return None
        tpl = binding.get("template") or ReportService().get_template(tid)
        if not tpl:
            return None
        if not template_effective_content(tpl):
            return None
        return {**binding, "template": tpl}

    def bind_template(self, *, work_ids: list[str], template_id: str, enabled: bool = True) -> list[dict[str, Any]]:
        """将已有 report_template 绑定到一个或多个业务。"""
        self.ensure_ready()
        ids = _unique_work_ids(work_ids)
        if not ids:
            raise ValueError("请至少选择一个已保存的巡检业务")
        tid = template_id.strip()
        if not tid:
            raise ValueError("请选择报告模版")
        tpl = ReportService().get_template(tid)
        if not tpl:
            raise ValueError(f"报告模版 {tid} 不存在")
        _ensure_saved_works(ids)

        flag = 1 if enabled else 0
        now = _display_now()
        for wid in ids:
            conn = db.get_connection()
            try:
                conn.execute(
                    """
INSERT INTO work_report_template_binding (work_id, enabled, template_id, created_at, updated_at)
VALUES (?, ?, ?, ?, ?)
ON DUPLICATE KEY UPDATE
    enabled = VALUES(enabled),
    template_id = VALUES(template_id),
    updated_at = VALUES(updated_at)
""",
                    (wid, flag, tid, now, now),
                )
                conn.commit()
            finally:
                conn.close()
        return [self.get_binding(wid) for wid in ids if self.get_binding(wid)]

    def clear_binding(self, work_id: str) -> None:
        """取消业务报告模版绑定（删除绑定行）。"""
        self.ensure_ready()
        wid = work_id.strip()
        if not wid:
            raise ValueError("work_id 不能为空")
        _ensure_saved_works([wid])
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM work_report_template_binding WHERE work_id = ?", (wid,))
            conn.commit()
        finally:
            conn.close()

    def save_binding(self, *, work_id: str, template_id: str | None) -> dict[str, Any] | None:
        """保存单条业务绑定：有 template_id 则绑定并启用，否则清除绑定。"""
        self.ensure_ready()
        wid = work_id.strip()
        if not wid:
            raise ValueError("work_id 不能为空")
        tid = (template_id or "").strip()
        if not tid:
            self.clear_binding(wid)
            return None
        items = self.bind_template(work_ids=[wid], template_id=tid, enabled=True)
        row = items[0] if items else self.get_binding(wid)
        if not row:
            raise ValueError("报告模版绑定保存失败，请重试")
        return row

    def set_enabled(self, *, work_ids: list[str], enabled: bool) -> list[dict[str, Any]]:
        self.ensure_ready()
        ids = _unique_work_ids(work_ids)
        if not ids:
            raise ValueError("请至少选择一个已保存的巡检业务")
        _ensure_saved_works(ids)

        flag = 1 if enabled else 0
        now = _display_now()
        out: list[dict[str, Any]] = []
        for wid in ids:
            existing = self.get_binding(wid)
            if enabled and (not existing or not (existing.get("template_id") or "").strip()):
                raise ValueError(f"业务 {wid} 尚未绑定报告模版，请先选择或上传模版")
            conn = db.get_connection()
            try:
                conn.execute(
                    """
INSERT INTO work_report_template_binding (work_id, enabled, template_id, created_at, updated_at)
VALUES (?, ?, ?, ?, ?)
ON DUPLICATE KEY UPDATE
    enabled = VALUES(enabled),
    updated_at = VALUES(updated_at)
""",
                    (wid, flag, (existing or {}).get("template_id") or "", now, now),
                )
                conn.commit()
            finally:
                conn.close()
            row = self.get_binding(wid)
            if row:
                out.append(row)
        return out

    def upload_and_bind(
        self,
        *,
        work_ids: list[str],
        file_content: bytes,
        original_filename: str,
        name: str | None = None,
        description: str = "",
    ) -> list[dict[str, Any]]:
        """上传文件 → 写入 report_template → 绑定业务。"""
        self.ensure_ready()
        ids = _unique_work_ids(work_ids)
        if not ids:
            raise ValueError("请至少选择一个已保存的巡检业务")
        _ensure_saved_works(ids)

        tpl = ReportService().create_template_from_upload(
            file_content=file_content,
            original_filename=original_filename,
            name=name,
            description=description,
        )
        return self.bind_template(work_ids=ids, template_id=str(tpl["template_id"]), enabled=True)


def get_work_report_template_snapshot(work_id: str) -> dict[str, Any] | None:
    binding = WorkReportTemplateBindingService().get_template_for_work(work_id.strip())
    if not binding:
        return None
    tpl = binding.get("template") or {}
    storage = str(tpl.get("storage_relpath") or "")
    return {
        "work_id": binding["work_id"],
        "template_id": binding.get("template_id") or "",
        "storage_dir": storage.rsplit("/", 1)[0] if storage else "",
        "content": template_effective_content(tpl),
        "template_name": str(tpl.get("name") or ""),
        "filename": str(tpl.get("filename") or ""),
    }


def require_work_report_template(work_id: str) -> dict[str, Any]:
    wid = work_id.strip()
    svc = WorkReportTemplateBindingService()
    resolved = svc.get_template_for_work(wid)
    if not resolved:
        binding = svc.get_binding(wid)
        if not binding or not binding.get("enabled"):
            raise ValueError("该业务未启用报告模板绑定，请先在巡检业务详情中配置报告模版")
        if not (binding.get("template_id") or "").strip():
            raise ValueError("该业务已勾选报告模板绑定，但尚未选择报告模版")
        raise ValueError("报告模版不存在或内容为空，请重新上传有效的报告模版")
    tpl = resolved.get("template") or {}
    return {
        **resolved,
        "template_name": tpl.get("name") or "",
        "filename": tpl.get("filename") or "",
        "content": template_effective_content(tpl),
        "storage_relpath": tpl.get("storage_relpath") or "",
    }
