"""巡检业务 CRUD。"""

from __future__ import annotations

import json
import uuid

from inspection_platform.app.mysql_compat import is_integrity_error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _builtin_seed_path() -> Path:
    return Path(__file__).resolve().parent / "builtin_seed.json"


class InspectionWorkService:
    def ensure_ready(self) -> None:
        """表结构在应用 lifespan 中 init_db()；请求路径勿重复初始化。"""

    def validate_equipment_ids(self, equipment_ids: list[str]) -> None:
        from inspection_platform.equipment.service import EquipmentService

        eq_svc = EquipmentService()
        eq_svc.ensure_ready()
        seen: set[str] = set()
        for raw in equipment_ids:
            eid = str(raw).strip()
            if not eid:
                raise ValueError("equipment_set 中存在空的 equipment_id")
            if eid in seen:
                continue
            seen.add(eid)
            if not eq_svc.get(eid):
                raise ValueError(f"设备 {eid} 不存在")

    def derive_region_ids(self, equipment_ids: list[str]) -> list[str]:
        from inspection_platform.equipment.service import EquipmentService

        eq_svc = EquipmentService()
        eq_svc.ensure_ready()
        out: list[str] = []
        seen: set[str] = set()
        for raw in equipment_ids:
            eid = str(raw).strip()
            if not eid:
                continue
            rec = eq_svc.get(eid)
            if not rec:
                continue
            rid = str(rec.get("region_id") or "").strip()
            if rid and rid not in seen:
                seen.add(rid)
                out.append(rid)
        return out

    def raise_if_equipment_missing_region(self, equipment_ids: list[str]) -> None:
        from inspection_platform.equipment.service import EquipmentService

        eq_svc = EquipmentService()
        eq_svc.ensure_ready()
        missing: list[str] = []
        for raw in equipment_ids:
            eid = str(raw).strip()
            if not eid:
                continue
            rec = eq_svc.get(eid)
            if rec and not str(rec.get("region_id") or "").strip():
                missing.append(eid)
        if missing:
            labels = "、".join(missing[:5])
            extra = f" 等 {len(missing)} 台" if len(missing) > 5 else ""
            raise ValueError(
                f"设备 {labels}{extra} 未配置 region_id，请先在设备管理中指定所属区域"
            )

    def offline_works_by_rule(self, rule_id: str) -> int:
        rid = rule_id.strip()
        if not rid:
            return 0
        count = 0
        offset = 0
        limit = 500
        while True:
            items, total = self.list_all(limit=limit, offset=offset)
            for w in items:
                rule_set = w.get("rule_set") or []
                refs = {str(r.get("rule_id") or "").strip() for r in rule_set}
                if rid not in refs:
                    continue
                if w.get("work_status") == "offline":
                    continue
                updated = self.update(w["work_id"], work_status="offline")
                if updated:
                    count += 1
            offset += limit
            if offset >= total:
                break
        return count

    def _work_matches_region(self, work: dict[str, Any], region_id: str) -> bool:
        rid = region_id.strip()
        if not rid:
            return False
        region_ids = work.get("region_ids") or []
        if rid in region_ids:
            return True
        return str(work.get("region_id") or "") == rid

    def create(
        self,
        *,
        region_id: str,
        name: str,
        desc: str,
        rule_set: list[dict[str, Any]],
        algorithm_set: list[dict[str, Any]],
        equipment_set: list[dict[str, Any]],
        work_id: str | None = None,
        region_ids: list[str] | None = None,
        schedule_mode: str = "manual",
        schedule_interval: str | None = None,
        schedule_times: str | None = None,
        source: str = "manual",
        equipment_algo_params: dict[str, Any] | None = None,
        work_status: str = "online",
    ) -> dict[str, Any]:
        self.ensure_ready()
        wid = (work_id or "").strip() or uuid.uuid4().hex
        rids = [str(x).strip() for x in (region_ids or []) if str(x).strip()]
        primary = (region_id or "").strip() or (rids[0] if rids else "")
        if not primary:
            raise ValueError("region_id 不能为空（可由 equipment_set 推导）")
        if not rids:
            rids = [primary]
        st = (work_status or "online").strip() or "online"
        if st not in ("online", "offline"):
            raise ValueError("work_status 须为 online 或 offline")
        now = _utc_now()
        conn = db.get_connection()
        try:
            conn.execute(
                """
INSERT INTO inspection_work (
    work_id, region_id, region_ids_json, name, `desc`, rule_set_json, algorithm_set_json,
    equipment_set_json, equipment_algo_params_json, work_status,
    schedule_mode, schedule_interval, schedule_times, source, created_at, updated_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                (
                    wid,
                    primary,
                    json.dumps(rids, ensure_ascii=False),
                    name.strip(),
                    desc or "",
                    json.dumps(rule_set, ensure_ascii=False),
                    json.dumps(algorithm_set, ensure_ascii=False),
                    json.dumps(equipment_set, ensure_ascii=False),
                    json.dumps(equipment_algo_params or {}, ensure_ascii=False),
                    st,
                    (schedule_mode or "manual").strip() or "manual",
                    schedule_interval,
                    schedule_times,
                    (source or "manual").strip() or "manual",
                    now,
                    now,
                ),
            )
            conn.commit()
        except Exception as e:
            if is_integrity_error(e):
                conn.rollback()
                raise ValueError("work_id 已存在") from e
            raise
        finally:
            conn.close()
        return self.get(wid) or {}

    def get(self, work_id: str) -> dict[str, Any] | None:
        self.ensure_ready()
        conn = db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM inspection_work WHERE work_id = ?",
                (work_id.strip(),),
            ).fetchone()
        finally:
            conn.close()
        return db.row_to_api(row) if row else None

    def list_by_region(self, region_id: str, *, limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        self.ensure_ready()
        items, _ = self.list_all(limit=500, offset=0)
        matched = [w for w in items if self._work_matches_region(w, region_id)]
        total = len(matched)
        limit = max(1, min(500, limit))
        offset = max(0, offset)
        page = matched[offset : offset + limit]
        return page, total

    def list_all(self, *, limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        self.ensure_ready()
        limit = max(1, min(500, limit))
        offset = max(0, offset)
        conn = db.get_connection()
        try:
            total = int(conn.execute("SELECT COUNT(*) AS c FROM inspection_work").fetchone()["c"])
            rows = conn.execute(
                "SELECT * FROM inspection_work ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        finally:
            conn.close()
        return [db.row_to_api(r) for r in rows], total

    def equipment_is_referenced(self, equipment_id: str) -> bool:
        eid = equipment_id.strip()
        if not eid:
            return False
        items, _ = self.list_by_equipment(eid, limit=1, offset=0)
        return len(items) > 0

    def refresh_work_snapshots(
        self,
        *,
        rule_set: list[dict[str, Any]],
        algorithm_set: list[dict[str, Any]],
        spec_svc: Any,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """上线前从规范/算法库按 id 刷新 rule_set、algorithm_set 中的名称与说明快照。"""
        from inspection_platform.algorithm.service import AlgorithmService

        algo_svc = AlgorithmService()
        algo_svc.ensure_ready()

        refreshed_rules: list[dict[str, Any]] = []
        for item in rule_set:
            row = dict(item)
            rid = str(row.get("rule_id") or "").strip()
            if rid:
                try:
                    src = spec_svc.get_rule(rid)
                except KeyError:
                    src = None
                if src:
                    row["name"] = str(src.get("name") or row.get("name") or "")
                    row["desc"] = str(src.get("desc") or row.get("desc") or "")
                    row["level"] = str(src.get("level") or row.get("level") or "")
                    if src.get("requirements") is not None:
                        row["requirements"] = str(src.get("requirements") or "")
                    if src.get("source") is not None:
                        row["source"] = str(src.get("source") or "")
            refreshed_rules.append(row)

        refreshed_algos: list[dict[str, Any]] = []
        for item in algorithm_set:
            row = dict(item)
            aid = str(row.get("algorithm_id") or "").strip()
            if aid:
                src = algo_svc.get(aid)
                if src:
                    row["name"] = str(src.get("name") or row.get("name") or "")
                    row["desc"] = str(src.get("desc") or row.get("desc") or "")
                    row["health"] = str(src.get("health") or row.get("health") or "unknown")
                    if src.get("link") is not None:
                        row["link"] = str(src.get("link") or "")
            refreshed_algos.append(row)

        return refreshed_rules, refreshed_algos

    def seed_builtin(self, *, replace_all: bool = False) -> int:
        self.ensure_ready()
        path = _builtin_seed_path()
        if not path.is_file():
            raise ValueError("builtin_seed.json 不存在")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("builtin_seed.json 须为 JSON 数组")
        conn = db.get_connection()
        inserted = 0
        try:
            if replace_all:
                conn.execute("DELETE FROM inspection_work")
            now = _utc_now()
            for item in raw:
                if not isinstance(item, dict):
                    continue
                wid = str(item.get("work_id") or "").strip()
                if not wid:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM inspection_work WHERE work_id = ?",
                    (wid,),
                ).fetchone()
                if exists:
                    continue
                region_ids = item.get("region_ids") or []
                if not isinstance(region_ids, list):
                    region_ids = []
                region_ids = [str(x).strip() for x in region_ids if str(x).strip()]
                primary = str(item.get("region_id") or "").strip() or (region_ids[0] if region_ids else "")
                if not primary:
                    continue
                if not region_ids:
                    region_ids = [primary]
                st = str(item.get("work_status") or "online").strip() or "online"
                conn.execute(
                    """
INSERT INTO inspection_work (
    work_id, region_id, region_ids_json, name, `desc`, rule_set_json, algorithm_set_json,
    equipment_set_json, equipment_algo_params_json, work_status,
    schedule_mode, schedule_interval, schedule_times, source, created_at, updated_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                    (
                        wid,
                        primary,
                        json.dumps(region_ids, ensure_ascii=False),
                        str(item.get("name") or wid),
                        str(item.get("desc") or ""),
                        json.dumps(item.get("rule_set") or [], ensure_ascii=False),
                        json.dumps(item.get("algorithm_set") or [], ensure_ascii=False),
                        json.dumps(item.get("equipment_set") or [], ensure_ascii=False),
                        json.dumps(item.get("equipment_algo_params") or {}, ensure_ascii=False),
                        st,
                        str(item.get("schedule_mode") or "manual").strip() or "manual",
                        item.get("schedule_interval"),
                        item.get("schedule_times"),
                        str(item.get("source") or "manual").strip() or "manual",
                        now,
                        now,
                    ),
                )
                inserted += 1
            conn.commit()
        finally:
            conn.close()
        return inserted

    def list_by_equipment(
        self,
        equipment_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        self.ensure_ready()
        eid = equipment_id.strip()
        items, _ = self.list_all(limit=500, offset=0)
        matched = [
            w
            for w in items
            if any(str(e.get("equipment_id") or "") == eid for e in (w.get("equipment_set") or []))
        ]
        total = len(matched)
        limit = max(1, min(500, limit))
        offset = max(0, offset)
        page = matched[offset : offset + limit]
        return page, total

    def delete(self, work_id: str) -> bool:
        self.ensure_ready()
        conn = db.get_connection()
        try:
            cur = conn.execute("DELETE FROM inspection_work WHERE work_id = ?", (work_id.strip(),))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def update(
        self,
        work_id: str,
        *,
        region_id: str | None = None,
        region_ids: list[str] | None = None,
        name: str | None = None,
        desc: str | None = None,
        rule_set: list[dict[str, Any]] | None = None,
        algorithm_set: list[dict[str, Any]] | None = None,
        equipment_set: list[dict[str, Any]] | None = None,
        schedule_mode: str | None = None,
        schedule_interval: str | None = None,
        schedule_times: str | None = None,
        source: str | None = None,
        equipment_algo_params: dict[str, Any] | None = None,
        work_status: str | None = None,
    ) -> dict[str, Any] | None:
        self.ensure_ready()
        wid = work_id.strip()
        existing = self.get(wid)
        if not existing:
            return None
        fields: list[str] = []
        params: list[Any] = []
        if region_id is not None:
            fields.append("region_id = ?")
            params.append(region_id.strip())
        if region_ids is not None:
            rids = [str(x).strip() for x in region_ids if str(x).strip()]
            fields.append("region_ids_json = ?")
            params.append(json.dumps(rids, ensure_ascii=False))
            if region_id is None and rids:
                fields.append("region_id = ?")
                params.append(rids[0])
        if name is not None:
            fields.append("name = ?")
            params.append(name.strip())
        if desc is not None:
            fields.append("`desc` = ?")
            params.append(desc)
        if rule_set is not None:
            fields.append("rule_set_json = ?")
            params.append(json.dumps(rule_set, ensure_ascii=False))
        if algorithm_set is not None:
            fields.append("algorithm_set_json = ?")
            params.append(json.dumps(algorithm_set, ensure_ascii=False))
        if equipment_set is not None:
            fields.append("equipment_set_json = ?")
            params.append(json.dumps(equipment_set, ensure_ascii=False))
        if equipment_algo_params is not None:
            fields.append("equipment_algo_params_json = ?")
            params.append(json.dumps(equipment_algo_params, ensure_ascii=False))
        if schedule_mode is not None:
            fields.append("schedule_mode = ?")
            params.append(schedule_mode.strip() or "manual")
        if schedule_interval is not None:
            fields.append("schedule_interval = ?")
            params.append(schedule_interval)
        if schedule_times is not None:
            fields.append("schedule_times = ?")
            params.append(schedule_times)
        if source is not None:
            fields.append("source = ?")
            params.append(source.strip() or "manual")
        if work_status is not None:
            st = work_status.strip() or "online"
            if st not in ("online", "offline"):
                raise ValueError("work_status 须为 online 或 offline")
            fields.append("work_status = ?")
            params.append(st)
        if not fields:
            return existing
        fields.append("updated_at = ?")
        params.append(_utc_now())
        params.append(wid)
        conn = db.get_connection()
        try:
            conn.execute(
                f"UPDATE inspection_work SET {', '.join(fields)} WHERE work_id = ?",
                params,
            )
            conn.commit()
        finally:
            conn.close()
        return self.get(wid)
