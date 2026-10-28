"""用户与会话表结构。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from inspection_platform.app.mysql_compat import row_keys

from .config import auth_db_path
from .permissions import ALL_PERMISSIONS, DEFAULT_USER_PERMISSIONS, normalize_permissions

SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_user (
    user_id TEXT PRIMARY KEY,
    account TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    password TEXT NOT NULL,
    permissions_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_session (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES auth_user(user_id)
);

CREATE INDEX IF NOT EXISTS idx_auth_user_account ON auth_user(account);
CREATE INDEX IF NOT EXISTS idx_auth_session_user ON auth_session(user_id);
"""

# 旧库迁移：role 列存在且 permissions_json 为空时，按历史角色回填后再删列
_LEGACY_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": list(ALL_PERMISSIONS),
    "operator": [
        "p-dash",
        "p-reports",
        "p-events",
        "p-inspection-view",
        "p-inspection",
        "p-device",
        "p-knowledge",
        "p-algo",
    ],
    "viewer": list(DEFAULT_USER_PERMISSIONS),
}


def get_connection():
    from inspection_platform.app.database import get_connection as _gc

    return _gc()


def init_db() -> None:
    from inspection_platform.app.database import init_db as _init_tables

    _init_tables()


def _permissions_from_legacy_role(role: str) -> list[str]:
    key = (role or "viewer").strip().lower()
    return list(_LEGACY_ROLE_PERMISSIONS.get(key, _LEGACY_ROLE_PERMISSIONS["viewer"]))


def _seed_passwords_by_account() -> dict[str, str]:
    path = Path(__file__).resolve().parent / "builtin_seed.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, list):
        return {}
    out: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        account = str(item.get("account") or "").strip().lower()
        if account:
            out[account] = str(item.get("password") or "demo1234")
    return out


def _backfill_permissions_from_role(conn: sqlite3.Connection) -> None:
    cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(auth_user)")}
    if "role" not in cols:
        return
    rows = conn.execute("SELECT user_id, role, permissions_json FROM auth_user").fetchall()
    for row in rows:
        raw = str(row["permissions_json"] or "[]")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = []
        perms = normalize_permissions(parsed if isinstance(parsed, list) else [])
        if not perms:
            perms = _permissions_from_legacy_role(str(row["role"]))
            conn.execute(
                "UPDATE auth_user SET permissions_json = ? WHERE user_id = ?",
                (json.dumps(perms, ensure_ascii=False), str(row["user_id"])),
            )


def _drop_role_column(conn: sqlite3.Connection) -> None:
    cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(auth_user)")}
    if "role" not in cols:
        return
    _backfill_permissions_from_role(conn)
    if "password" in cols:
        conn.executescript(
            """
CREATE TABLE auth_user_new (
    user_id TEXT PRIMARY KEY,
    account TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    password TEXT NOT NULL,
    permissions_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
INSERT INTO auth_user_new (
    user_id, account, name, status, password, permissions_json, created_at, updated_at
)
SELECT
    user_id, account, name, status, password, permissions_json, created_at, updated_at
FROM auth_user;
DROP TABLE auth_user;
ALTER TABLE auth_user_new RENAME TO auth_user;
CREATE INDEX IF NOT EXISTS idx_auth_user_account ON auth_user(account);
"""
        )
        return
    conn.executescript(
        """
CREATE TABLE auth_user_new (
    user_id TEXT PRIMARY KEY,
    account TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    password_salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    permissions_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
INSERT INTO auth_user_new (
    user_id, account, name, status, password_salt, password_hash, permissions_json, created_at, updated_at
)
SELECT
    user_id, account, name, status, password_salt, password_hash, permissions_json, created_at, updated_at
FROM auth_user;
DROP TABLE auth_user;
ALTER TABLE auth_user_new RENAME TO auth_user;
CREATE INDEX IF NOT EXISTS idx_auth_user_account ON auth_user(account);
"""
    )


def _migrate_hashed_password_columns(conn: sqlite3.Connection) -> None:
    cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(auth_user)")}
    if "password" in cols or "password_salt" not in cols:
        return
    seed_passwords = _seed_passwords_by_account()
    rows = conn.execute(
        "SELECT user_id, account, name, status, permissions_json, created_at, updated_at FROM auth_user"
    ).fetchall()
    conn.executescript(
        """
CREATE TABLE auth_user_new (
    user_id TEXT PRIMARY KEY,
    account TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    password TEXT NOT NULL,
    permissions_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""
    )
    for row in rows:
        account = str(row["account"]).strip().lower()
        password = seed_passwords.get(account, "demo1234")
        conn.execute(
            """
INSERT INTO auth_user_new (
    user_id, account, name, status, password, permissions_json, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""",
            (
                str(row["user_id"]),
                account,
                str(row["name"]),
                str(row["status"]),
                password,
                str(row["permissions_json"] or "[]"),
                str(row["created_at"]),
                str(row["updated_at"]),
            ),
        )
    conn.executescript(
        """
DROP TABLE auth_user;
ALTER TABLE auth_user_new RENAME TO auth_user;
CREATE INDEX IF NOT EXISTS idx_auth_user_account ON auth_user(account);
"""
    )


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(auth_user)")}
    if not cols:
        return
    if "permissions_json" not in cols:
        conn.execute("ALTER TABLE auth_user ADD COLUMN permissions_json TEXT NOT NULL DEFAULT '[]'")
    _drop_role_column(conn)
    _migrate_hashed_password_columns(conn)


def init_db() -> None:
    from inspection_platform.app.database import init_db as _init_tables

    _init_tables()


def db_path() -> Path:
    return auth_db_path()


def parse_permissions_json(raw: str | None) -> list[str]:
    if raw is not None:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return normalize_permissions(parsed)
        except json.JSONDecodeError:
            pass
    return list(DEFAULT_USER_PERMISSIONS)


def user_row_to_api(
    row: sqlite3.Row,
    permissions: list[str],
    *,
    role_id: str | None = None,
    role_name: str | None = None,
) -> dict[str, Any]:
    return {
        "user_id": str(row["user_id"]),
        "account": str(row["account"]),
        "name": str(row["name"]),
        "status": str(row["status"]),
        "permissions": permissions,
        "role_id": role_id,
        "role_name": role_name,
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def role_row_to_api(row: sqlite3.Row, permissions: list[str]) -> dict[str, Any]:
    return {
        "role_id": str(row["role_id"]),
        "name": str(row["name"]),
        "description": str(row["description"]) if "description" in row_keys(row) else "",
        "permissions": permissions,
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }
