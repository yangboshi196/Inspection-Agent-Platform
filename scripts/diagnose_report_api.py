"""诊断报告模版 / 绑定 API 在 MySQL 下的查询问题。"""
from __future__ import annotations

import traceback

from inspection_platform.app.database import init_db, get_connection
from inspection_platform.report.bootstrap import bootstrap_report_module
from inspection_platform.report.service import ReportService
from inspection_platform.report.work_template_binding import WorkReportTemplateBindingService


def main() -> None:
    init_db()
    try:
        bootstrap_report_module(force=True)
        print("bootstrap: ok")
    except Exception:
        print("bootstrap: FAILED")
        traceback.print_exc()
        return

    conn = get_connection()
    try:
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()"
        ).fetchall()
        names = sorted(str(r[0] if not hasattr(r, "keys") else r["table_name"]) for r in tables)
        for t in ("report_template", "work_report_template_binding", "report_plan"):
            print(f"table {t}:", "yes" if t in names else "MISSING")
        if "work_report_template_binding" in names:
            cols = conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'work_report_template_binding'"
            ).fetchall()
            print("binding columns:", [str(c[0] if not hasattr(c, "keys") else c["column_name"]) for c in cols])
    except Exception:
        print("schema check FAILED")
        traceback.print_exc()
    finally:
        conn.close()

    try:
        items, total = ReportService().list_templates(limit=5)
        print(f"list_templates: ok total={total} items={len(items)}")
        if items:
            print("first keys:", list(items[0].keys()))
    except Exception:
        print("list_templates FAILED")
        traceback.print_exc()

    try:
        bindings = WorkReportTemplateBindingService().list_bindings()
        print(f"list_bindings: ok count={len(bindings)}")
    except Exception:
        print("list_bindings FAILED")
        traceback.print_exc()

    try:
        import httpx

        paths = (
            "/api/report-templates/?limit=1",
            "/api/work-report-template-bindings/",
            "/api/work-report-template-bindings/iw-3",
        )
        with httpx.Client(base_url="http://127.0.0.1:8001", timeout=30) as client:
            login = client.post("/api/auth/login", json={"account": "zhang.gong", "password": "demo1234"})
            token = login.json().get("token")
            h = {"Authorization": f"Bearer {token}"}
            spec = client.get("/openapi.json").json()
            upload_path = "/api/report-templates/upload"
            has_upload = upload_path in spec.get("paths", {})
            print(f"live openapi has upload route: {has_upload}")
            for path in paths:
                r = client.get(path, headers=h)
                print(f"live httpx {path} -> {r.status_code} {r.text[:160]}")
    except Exception:
        print("live httpx FAILED")
        traceback.print_exc()


if __name__ == "__main__":
    main()
