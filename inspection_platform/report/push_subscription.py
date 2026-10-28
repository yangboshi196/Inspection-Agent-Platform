"""用户 ↔ 巡检业务 报告推送订阅（管理端配置，用户看板按订阅筛选报告）。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from inspection_platform.app.database import get_connection


def _display_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _loads_work_ids(raw: str) -> list[str]:
    try:
        val = json.loads(raw or "[]")
        if not isinstance(val, list):
            return []
        return [str(x).strip() for x in val if str(x).strip()]
    except json.JSONDecodeError:
        return []


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


class ReportPushSubscriptionService:
    """报告推送订阅：每用户一行，work_ids_json 存储订阅的业务 id 列表。"""

    def list_subscriptions(self) -> dict[str, list[str]]:
        """user_id -> work_ids"""
        conn = get_connection()
        try:
            rows = conn.execute("SELECT user_id, work_ids_json FROM user_report_push_subscription").fetchall()
        finally:
            conn.close()
        out: dict[str, list[str]] = {}
        for row in rows:
            uid = str(row["user_id"])
            out[uid] = _loads_work_ids(str(row["work_ids_json"] or ""))
        return out

    def get_work_ids_for_user(self, user_id: str) -> list[str]:
        uid = user_id.strip()
        if not uid:
            return []
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT work_ids_json FROM user_report_push_subscription WHERE user_id = ?",
                (uid,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return []
        return _loads_work_ids(str(row["work_ids_json"] or ""))

    def save_subscriptions(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """批量保存；items: [{ user_id, work_ids }]"""
        from inspection_platform.auth.service import AuthService
        from inspection_platform.inspection_work.service import InspectionWorkService

        auth = AuthService()
        users = {str(u["user_id"]): u for u in auth.list_users()}

        work_svc = InspectionWorkService()
        work_svc.ensure_ready()
        works, _ = work_svc.list_all(limit=500, offset=0)
        valid_work_ids = {str(w.get("work_id") or "") for w in works}

        now = _display_now()
        saved: list[dict[str, Any]] = []

        for item in items:
            uid = str(item.get("user_id") or "").strip()
            if not uid or uid not in users:
                raise ValueError(f"用户 {uid or '(空)'} 不存在")
            work_ids = _unique_work_ids(list(item.get("work_ids") or []))
            unknown = [w for w in work_ids if w not in valid_work_ids]
            if unknown:
                raise ValueError(f"用户 {users[uid].get('name') or uid} 订阅了不存在的业务：{', '.join(unknown[:3])}")

            conn = get_connection()
            try:
                if work_ids:
                    conn.execute(
                        """
INSERT INTO user_report_push_subscription (user_id, work_ids_json, created_at, updated_at)
VALUES (?, ?, ?, ?)
ON DUPLICATE KEY UPDATE
    work_ids_json = VALUES(work_ids_json),
    updated_at = VALUES(updated_at)
""",
                        (uid, json.dumps(work_ids, ensure_ascii=False), now, now),
                    )
                else:
                    conn.execute(
                        "DELETE FROM user_report_push_subscription WHERE user_id = ?",
                        (uid,),
                    )
                conn.commit()
            finally:
                conn.close()
            saved.append({"user_id": uid, "work_ids": work_ids})

        return saved

    @staticmethod
    def report_matches_work_ids(report_work_ids: list[str], subscribed: set[str]) -> bool:
        if not subscribed:
            return False
        return any(wid in subscribed for wid in report_work_ids if wid)
