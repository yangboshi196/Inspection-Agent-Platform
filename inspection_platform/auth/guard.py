"""API 路径与所需权限。"""

from __future__ import annotations


def required_permission(path: str, method: str) -> str | None:
    """返回所需权限 id；None 表示仅需登录。"""
    p = (path.rstrip("/") or "/")
    m = method.upper()
    is_write = m in {"POST", "PUT", "PATCH", "DELETE"}

    if p.startswith("/api/auth/me") or p.startswith("/api/auth/bootstrap") or p.startswith("/api/auth/logout"):
        return None
    if p.startswith("/api/auth/users") or p.startswith("/api/auth/roles"):
        return "p-perm"

    if p.startswith("/api/inspection-events/stats"):
        return "p-dash"
    if p.startswith("/api/inspection-events/runtime"):
        return "p-inspection-view"
    if p.startswith("/api/inspection-events"):
        return "p-events"

    if p.startswith("/api/report-push/me"):
        return None
    if p.startswith("/api/report-push/subscriptions"):
        return "p-inspection"

    if (
        p.startswith("/api/inspection-reports")
        or p.startswith("/api/report-templates")
        or p.startswith("/api/report-plans")
        or p.startswith("/api/work-report-template-bindings")
    ):
        return "p-reports"

    if p.startswith("/api/inspection-work"):
        return "p-inspection" if is_write else "p-inspection-view"

    if p.startswith("/api/equipment") or p.startswith("/api/region"):
        return "p-device" if is_write else "p-inspection-view"

    if p.startswith("/api/algorithm"):
        return "p-algo"

    if p.startswith("/api/knowledge") or p.startswith("/api/spec"):
        return "p-knowledge"

    if p.startswith("/api/document"):
        return "p-docs"

    if p.startswith("/api/chat"):
        return "p-workflow"

    if p.startswith("/api/logs"):
        return "p-logs"

    if is_write:
        return "p-perm"
    return None
