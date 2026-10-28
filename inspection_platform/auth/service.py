"""用户认证、会话与按用户权限。"""

from __future__ import annotations

import json
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from inspection_platform.app.mysql_compat import is_integrity_error, row_keys

from . import db
from .permissions import DEFAULT_USER_PERMISSIONS, is_full_admin, normalize_permissions


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _builtin_seed_path() -> Path:
    return Path(__file__).resolve().parent / "builtin_seed.json"


_FULL_ADMIN_REQUIRED_MSG = "至少保留一名全权限且启用中的管理员"

_UNSET = object()

_TOKEN_CACHE_TTL_SEC = 30.0
_TOKEN_MISS_CACHE_TTL_SEC = 10.0
_token_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_token_cache_lock = threading.Lock()
_token_resolve_lock = threading.Lock()


class _TokenCacheMiss:
    pass


_TOKEN_CACHE_MISS = _TokenCacheMiss()


def _cache_get(token: str) -> dict[str, Any] | None | _TokenCacheMiss:
    with _token_cache_lock:
        entry = _token_cache.get(token)
        if entry is None:
            return _TOKEN_CACHE_MISS
        expires_at, user = entry
        if expires_at <= time.monotonic():
            _token_cache.pop(token, None)
            return _TOKEN_CACHE_MISS
        return user


def _cache_set(token: str, user: dict[str, Any] | None) -> None:
    ttl = _TOKEN_CACHE_TTL_SEC if user else _TOKEN_MISS_CACHE_TTL_SEC
    with _token_cache_lock:
        _token_cache[token] = (time.monotonic() + ttl, user)


def _cache_invalidate(token: str | None = None) -> None:
    with _token_cache_lock:
        if token:
            _token_cache.pop(token.strip(), None)
        else:
            _token_cache.clear()


class AuthService:
    session_ttl_hours = 24 * 7

    def _row_role_id(self, row: Any) -> str:
        if "role_id" not in row_keys(row):
            return ""
        raw = row["role_id"]
        if raw is None:
            return ""
        return str(raw).strip()

    def _row_to_user(self, row: Any, *, role: dict[str, Any] | None = None) -> dict[str, Any]:
        rid = self._row_role_id(row) or None
        if rid and role is None:
            role = self.get_role(rid)
        perms = self._effective_permissions_from_row(row, role=role)
        role_name = str(role["name"]) if role else None
        return db.user_row_to_api(row, perms, role_id=rid, role_name=role_name)

    def _effective_permissions_from_row(
        self,
        row: Any,
        *,
        role: dict[str, Any] | None = None,
    ) -> list[str]:
        rid = self._row_role_id(row)
        if rid:
            r = role if role is not None else self.get_role(rid)
            if r:
                return normalize_permissions(r.get("permissions"))
        return db.parse_permissions_json(
            str(row["permissions_json"]) if "permissions_json" in row_keys(row) else None,
        )

    def _row_to_role(self, row: Any) -> dict[str, Any]:
        perms = db.parse_permissions_json(
            str(row["permissions_json"]) if "permissions_json" in row_keys(row) else None,
        )
        return db.role_row_to_api(row, perms)

    def get_role(self, role_id: str) -> dict[str, Any] | None:
        rid = role_id.strip()
        if not rid:
            return None
        conn = db.get_connection()
        try:
            row = conn.execute("SELECT * FROM auth_role WHERE role_id = ?", (rid,)).fetchone()
        finally:
            conn.close()
        return self._row_to_role(row) if row else None

    def list_roles(self) -> list[dict[str, Any]]:
        conn = db.get_connection()
        try:
            rows = conn.execute("SELECT * FROM auth_role ORDER BY name").fetchall()
        finally:
            conn.close()
        return [self._row_to_role(r) for r in rows]

    def create_role(
        self,
        *,
        role_id: str | None = None,
        name: str,
        description: str = "",
        permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        title = name.strip()
        if not title:
            raise ValueError("角色名称不能为空")
        perms = normalize_permissions(list(permissions) if permissions is not None else [])
        rid = (role_id or "").strip() or f"role-{secrets.token_hex(6)}"
        now = _utc_now()
        conn = db.get_connection()
        try:
            conn.execute(
                """
INSERT INTO auth_role (
    role_id, name, description, permissions_json, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?)
""",
                (
                    rid,
                    title,
                    (description or "").strip(),
                    json.dumps(perms, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.commit()
        except Exception as e:
            if is_integrity_error(e):
                conn.rollback()
                raise ValueError("角色名称或 id 已存在") from e
            raise
        finally:
            conn.close()
        return self.get_role(rid) or {}

    def update_role(
        self,
        role_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        permissions: list[str] | None = None,
    ) -> dict[str, Any] | None:
        rid = role_id.strip()
        current = self.get_role(rid)
        if not current:
            return None
        sets: list[str] = []
        params: list[Any] = []
        invalidate_sessions = False
        next_permissions = list(current.get("permissions") or [])
        if name is not None:
            title = name.strip()
            if not title:
                raise ValueError("角色名称不能为空")
            sets.append("name = ?")
            params.append(title)
        if description is not None:
            sets.append("description = ?")
            params.append(description.strip())
        if permissions is not None:
            next_permissions = normalize_permissions(permissions)
            sets.append("permissions_json = ?")
            params.append(json.dumps(next_permissions, ensure_ascii=False))
            invalidate_sessions = True
        if not sets:
            return current
        next_status = "active"
        self._ensure_keeps_full_admin_for_role_permissions(
            role_id=rid,
            next_permissions=next_permissions,
        )
        sets.append("updated_at = ?")
        params.append(_utc_now())
        params.append(rid)
        conn = db.get_connection()
        try:
            conn.execute(f"UPDATE auth_role SET {', '.join(sets)} WHERE role_id = ?", params)
            if invalidate_sessions:
                conn.execute(
                    "DELETE FROM auth_session WHERE user_id IN (SELECT user_id FROM auth_user WHERE role_id = ?)",
                    (rid,),
                )
            conn.commit()
        finally:
            conn.close()
        if invalidate_sessions:
            _cache_invalidate()
        return self.get_role(rid)

    def delete_role(self, role_id: str) -> bool:
        rid = role_id.strip()
        current = self.get_role(rid)
        if not current:
            return False
        conn = db.get_connection()
        try:
            bound = conn.execute(
                "SELECT COUNT(*) AS c FROM auth_user WHERE role_id = ?",
                (rid,),
            ).fetchone()
            count = int(bound["c"]) if bound else 0
            if count > 0:
                raise ValueError(f"仍有 {count} 个用户绑定该角色，请先调整用户角色")
            cur = conn.execute("DELETE FROM auth_role WHERE role_id = ?", (rid,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def _ensure_keeps_full_admin_for_role_permissions(
        self,
        *,
        role_id: str,
        next_permissions: list[str],
    ) -> None:
        if is_full_admin(status="active", permissions=next_permissions):
            return
        conn = db.get_connection()
        try:
            rows = conn.execute(
                "SELECT user_id, status, permissions_json, role_id FROM auth_user WHERE role_id = ?",
                (role_id.strip(),),
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            if str(row["status"]) != "active":
                continue
            was_full = is_full_admin(
                status="active",
                permissions=self._effective_permissions_from_row(row),
            )
            if not was_full:
                continue
            will_be_full = is_full_admin(status="active", permissions=next_permissions)
            if was_full and not will_be_full and self._count_full_admins(exclude_user_id=str(row["user_id"])) == 0:
                raise ValueError(_FULL_ADMIN_REQUIRED_MSG)

    def _count_users_on_role(self, role_id: str) -> int:
        conn = db.get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM auth_user WHERE role_id = ?",
                (role_id.strip(),),
            ).fetchone()
        finally:
            conn.close()
        return int(row["c"]) if row else 0

    def _count_full_admins(self, *, exclude_user_id: str | None = None) -> int:
        skip = (exclude_user_id or "").strip()
        count = 0
        for user in self.list_users():
            if skip and user["user_id"] == skip:
                continue
            if is_full_admin(status=str(user["status"]), permissions=user.get("permissions")):
                count += 1
        return count

    def _ensure_keeps_full_admin(
        self,
        *,
        user_id: str,
        next_status: str,
        next_permissions: list[str],
    ) -> None:
        current = self.get_user(user_id.strip())
        if not current:
            return
        was_full = is_full_admin(status=str(current["status"]), permissions=current.get("permissions"))
        will_be_full = is_full_admin(status=next_status, permissions=next_permissions)
        if was_full and not will_be_full and self._count_full_admins(exclude_user_id=user_id) == 0:
            raise ValueError(_FULL_ADMIN_REQUIRED_MSG)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        conn = db.get_connection()
        try:
            row = conn.execute("SELECT * FROM auth_user WHERE user_id = ?", (user_id.strip(),)).fetchone()
        finally:
            conn.close()
        return self._row_to_user(row) if row else None

    def get_user_by_account(self, account: str) -> dict[str, Any] | None:
        acct = account.strip().lower()
        conn = db.get_connection()
        try:
            row = conn.execute("SELECT * FROM auth_user WHERE account = ?", (acct,)).fetchone()
        finally:
            conn.close()
        return self._row_to_user(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        conn = db.get_connection()
        try:
            rows = conn.execute("SELECT * FROM auth_user ORDER BY account").fetchall()
        finally:
            conn.close()
        return [self._row_to_user(r) for r in rows]

    def login(self, account: str, password: str) -> dict[str, Any]:
        acct = account.strip().lower()
        if not acct or not password:
            raise ValueError("账号或密码不能为空")
        conn = db.get_connection()
        try:
            row = conn.execute("SELECT * FROM auth_user WHERE account = ?", (acct,)).fetchone()
            if not row:
                raise ValueError("账号或密码错误")
            if str(row["status"]) != "active":
                raise ValueError("账号已停用")
            if str(row["password"]) != password:
                raise ValueError("账号或密码错误")
            user = self._row_to_user(row)
            token = secrets.token_urlsafe(32)
            now = _utc_now()
            expires = (datetime.now(timezone.utc) + timedelta(hours=self.session_ttl_hours)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            conn.execute(
                "INSERT INTO auth_session (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token, user["user_id"], expires, now),
            )
            conn.commit()
        finally:
            conn.close()
        return {"token": token, "user": user}

    def logout(self, token: str) -> bool:
        key = token.strip()
        conn = db.get_connection()
        try:
            cur = conn.execute("DELETE FROM auth_session WHERE token = ?", (key,))
            conn.commit()
            ok = cur.rowcount > 0
        finally:
            conn.close()
        if ok:
            _cache_invalidate(key)
        return ok

    def resolve_token(self, token: str | None) -> dict[str, Any] | None:
        if not token or not token.strip():
            return None
        key = token.strip()
        cached = _cache_get(key)
        if cached is not _TOKEN_CACHE_MISS:
            return cached
        with _token_resolve_lock:
            cached = _cache_get(key)
            if cached is not _TOKEN_CACHE_MISS:
                return cached
            user = self._resolve_token_db(key)
            _cache_set(key, user)
            return user

    def _resolve_token_db(self, token: str) -> dict[str, Any] | None:
        conn = db.get_connection()
        try:
            session = conn.execute(
                """
SELECT s.token, s.expires_at, u.*
FROM auth_session s
JOIN auth_user u ON u.user_id = s.user_id
WHERE s.token = ?
""",
                (token,),
            ).fetchone()
        finally:
            conn.close()
        if not session:
            return None
        expires = _parse_utc(str(session["expires_at"]))
        if expires and expires < datetime.now(timezone.utc):
            self.logout(token)
            return None
        return self._row_to_user(session)

    def create_user(
        self,
        *,
        user_id: str | None = None,
        account: str,
        name: str,
        password: str,
        permissions: list[str] | None = None,
        status: str = "active",
        role_id: str | None = None,
    ) -> dict[str, Any]:
        acct = account.strip().lower()
        if status not in ("active", "disabled"):
            raise ValueError("status 须为 active | disabled")
        if len(password) < 4:
            raise ValueError("密码至少 4 位")
        rid_role = (role_id or "").strip() or None
        if rid_role and not self.get_role(rid_role):
            raise ValueError("角色不存在")
        if rid_role:
            perms: list[str] = []
        else:
            perms = normalize_permissions(
                list(permissions) if permissions is not None else list(DEFAULT_USER_PERMISSIONS),
            )
        uid = (user_id or "").strip() or f"u-{secrets.token_hex(6)}"
        now = _utc_now()
        conn = db.get_connection()
        try:
            conn.execute(
                """
INSERT INTO auth_user (
    user_id, account, name, status, password, role_id, permissions_json, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                (
                    uid,
                    acct,
                    name.strip(),
                    status,
                    password,
                    rid_role,
                    json.dumps(perms, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.commit()
        except Exception as e:
            if is_integrity_error(e):
                conn.rollback()
                raise ValueError("账号已存在") from e
            raise
        finally:
            conn.close()
        return self.get_user(uid) or {}

    def update_user(
        self,
        user_id: str,
        *,
        name: str | None = None,
        status: str | None = None,
        password: str | None = None,
        permissions: list[str] | None = None,
        role_id: str | None | object = _UNSET,
    ) -> dict[str, Any] | None:
        uid = user_id.strip()
        current = self.get_user(uid)
        if not current:
            return None
        sets: list[str] = []
        params: list[Any] = []
        invalidate_sessions = False
        next_status = str(current["status"])
        next_role_id = current.get("role_id")
        next_permissions = list(current.get("permissions") or [])
        if name is not None:
            sets.append("name = ?")
            params.append(name.strip())
        if status is not None:
            if status not in ("active", "disabled"):
                raise ValueError("status 须为 active | disabled")
            next_status = status
            sets.append("status = ?")
            params.append(status)
        if password is not None:
            if len(password) < 4:
                raise ValueError("密码至少 4 位")
            sets.append("password = ?")
            params.append(password)
            invalidate_sessions = True
        if role_id is not _UNSET:
            rid_role = None if role_id is None else (str(role_id).strip() or None)
            if rid_role and not self.get_role(rid_role):
                raise ValueError("角色不存在")
            next_role_id = rid_role
            sets.append("role_id = ?")
            params.append(rid_role)
            if rid_role:
                next_permissions = normalize_permissions(
                    (self.get_role(rid_role) or {}).get("permissions") or [],
                )
                sets.append("permissions_json = ?")
                params.append(json.dumps([], ensure_ascii=False))
            else:
                next_permissions = normalize_permissions(list(DEFAULT_USER_PERMISSIONS))
                sets.append("permissions_json = ?")
                params.append(json.dumps(next_permissions, ensure_ascii=False))
            invalidate_sessions = True
        if permissions is not None:
            if next_role_id or current.get("role_id"):
                raise ValueError("该用户已绑定角色，请修改角色权限或在用户侧更换角色")
            next_permissions = normalize_permissions(permissions)
            sets.append("permissions_json = ?")
            params.append(json.dumps(next_permissions, ensure_ascii=False))
            invalidate_sessions = True
        if not sets:
            return current
        self._ensure_keeps_full_admin(
            user_id=uid,
            next_status=next_status,
            next_permissions=next_permissions,
        )
        sets.append("updated_at = ?")
        params.append(_utc_now())
        params.append(uid)
        conn = db.get_connection()
        try:
            conn.execute(f"UPDATE auth_user SET {', '.join(sets)} WHERE user_id = ?", params)
            if invalidate_sessions:
                conn.execute("DELETE FROM auth_session WHERE user_id = ?", (uid,))
            conn.commit()
        finally:
            conn.close()
        if invalidate_sessions:
            _cache_invalidate()
        return self.get_user(uid)

    def delete_user(self, user_id: str) -> bool:
        uid = user_id.strip()
        current = self.get_user(uid)
        if not current:
            return False
        if is_full_admin(status=str(current["status"]), permissions=current.get("permissions")):
            if self._count_full_admins(exclude_user_id=uid) == 0:
                raise ValueError(_FULL_ADMIN_REQUIRED_MSG)
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM auth_session WHERE user_id = ?", (uid,))
            cur = conn.execute("DELETE FROM auth_user WHERE user_id = ?", (uid,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def seed_builtin(self) -> int:
        path = _builtin_seed_path()
        if not path.is_file():
            return 0
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return 0
        inserted = 0
        for item in raw:
            if not isinstance(item, dict):
                continue
            uid = str(item.get("user_id") or "").strip()
            acct = str(item.get("account") or "").strip().lower()
            if not uid or not acct:
                continue
            if self.get_user(uid):
                continue
            password = str(item.get("password") or "demo1234")
            perms_raw = item.get("permissions")
            perms = normalize_permissions(perms_raw if isinstance(perms_raw, list) else None)
            try:
                self.create_user(
                    user_id=uid,
                    account=acct,
                    name=str(item.get("name") or acct),
                    password=password,
                    permissions=perms,
                    status=str(item.get("status") or "active"),
                )
                inserted += 1
            except ValueError:
                continue
        return inserted
