"""页面权限 id 定义与校验（用户通过角色或直接 permissions_json 获得）。"""

from __future__ import annotations

ALL_PERMISSIONS: tuple[str, ...] = (
    "p-dash",
    "p-trigger-task",
    "p-reports",
    "p-events",
    "p-inspection-view",
    "p-inspection",
    "p-device",
    "p-knowledge",
    "p-algo",
    "p-perm",
    "p-logs",
    "p-docs",
    "p-workflow",
)

DEFAULT_USER_PERMISSIONS: tuple[str, ...] = (
    "p-dash",
    "p-trigger-task",
    "p-reports",
    "p-events",
    "p-inspection-view",
)


def is_valid_permission(perm: str) -> bool:
    return perm.strip() in ALL_PERMISSIONS


def normalize_permissions(perms: list[str] | None) -> list[str]:
    if not perms:
        return []
    allowed = set(ALL_PERMISSIONS)
    seen: set[str] = set()
    out: list[str] = []
    for raw in perms:
        pid = str(raw).strip()
        if pid in allowed and pid not in seen:
            seen.add(pid)
            out.append(pid)
    return sorted(out)


def is_full_admin(*, status: str, permissions: list[str] | None) -> bool:
    """启用中且拥有全部页面权限的管理员。"""
    if (status or "").strip() != "active":
        return False
    return normalize_permissions(list(permissions or [])) == normalize_permissions(list(ALL_PERMISSIONS))
