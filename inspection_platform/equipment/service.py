"""设备 CRUD 与内置种子。"""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inspection_platform.app.config import get_settings

from . import db


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _simulate_video_max_bytes() -> int:
    return 100 * 1024 * 1024


def _safe_video_ext(original_filename: str) -> str:
    ext = Path(original_filename).suffix.lower()
    if ext in (".mp4", ".webm", ".mov", ".m4v", ".mkv"):
        return ext
    return ".mp4"


def _simulate_video_dir(equipment_id: str) -> Path:
    return get_settings().data_path / "equipment_simulate" / equipment_id.strip()


def _discover_simulate_relpath(equipment_id: str) -> str:
    """磁盘上已有模拟视频但 DB 未写 relpath 时的回退。"""
    root = _simulate_video_dir(equipment_id)
    if not root.is_dir():
        return ""
    eid = equipment_id.strip()
    for ext in (".mp4", ".webm", ".mov", ".m4v", ".mkv"):
        if (root / f"video{ext}").is_file():
            return f"equipment_simulate/{eid}/video{ext}"
    return ""


def _attach_simulate_video(row: dict[str, Any]) -> dict[str, Any]:
    """平台已停用本地模拟视频，统一使用 RTSP 实时流。"""
    row = dict(row)
    row["simulate_video_relpath"] = ""
    row["simulate_video_url"] = ""
    return row


def _builtin_seed_path() -> Path:
    return Path(__file__).resolve().parent / "builtin_seed.json"


class EquipmentService:
    def ensure_ready(self) -> None:
        """表结构在应用 lifespan 中 init_db()；请求路径勿重复初始化。"""

    def create(
        self,
        *,
        equipment_id: str | None,
        kind: str,
        name: str,
        region_id: str = "",
        description: str = "",
        platform_name: str = "",
        platform_address: str = "",
        thumbnail: str = "",
        data_type: str = "",
        unit: str = "",
        online: bool = True,
    ) -> dict[str, Any]:
        self.ensure_ready()
        eid = (equipment_id or "").strip() or f"eq-{uuid.uuid4().hex[:10]}"
        k = kind.strip().lower()
        if k not in ("camera", "sensor"):
            raise ValueError("kind 须为 camera 或 sensor")
        now = _utc_now()
        conn = db.get_connection()
        try:
            conn.execute(
                """
INSERT INTO equipment (
    id, kind, name, region_id, description,
    platform_name, platform_address, thumbnail, data_type, unit, online,
    created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                (
                    eid,
                    k,
                    name.strip(),
                    region_id.strip(),
                    description or "",
                    platform_name or "",
                    platform_address or "",
                    thumbnail or "",
                    data_type or "",
                    unit or "",
                    1 if online else 0,
                    now,
                    now,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            conn.rollback()
            raise ValueError("设备 id 已存在") from e
        finally:
            conn.close()
        return self.get(eid) or {}

    def get(self, equipment_id: str) -> dict[str, Any] | None:
        self.ensure_ready()
        conn = db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM equipment WHERE id = ?",
                (equipment_id.strip(),),
            ).fetchone()
        finally:
            conn.close()
        return _attach_simulate_video(db.row_to_api(row)) if row else None

    def list_equipment(
        self,
        *,
        kind: str | None = None,
        region_id: str | None = None,
        region_ids: list[str] | None = None,
        online: bool | None = None,
        q: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        self.ensure_ready()
        limit = max(1, min(500, limit))
        offset = max(0, offset)
        where: list[str] = []
        params: list[Any] = []
        if kind:
            where.append("kind = ?")
            params.append(kind.strip().lower())
        if region_ids:
            ids = [rid.strip() for rid in region_ids if rid and rid.strip()]
            if ids:
                placeholders = ", ".join("?" for _ in ids)
                where.append(f"region_id IN ({placeholders})")
                params.extend(ids)
        elif region_id:
            where.append("region_id = ?")
            params.append(region_id.strip())
        if online is not None:
            where.append("online = ?")
            params.append(1 if online else 0)
        if q and q.strip():
            where.append("(id LIKE ? OR name LIKE ? OR description LIKE ?)")
            pat = f"%{q.strip()}%"
            params.extend([pat, pat, pat])
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        conn = db.get_connection()
        try:
            total = int(
                conn.execute(f"SELECT COUNT(*) AS c FROM equipment {clause}", params).fetchone()["c"]
            )
            rows = conn.execute(
                f"SELECT * FROM equipment {clause} ORDER BY kind, name LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        finally:
            conn.close()
        return [_attach_simulate_video(db.row_to_api(r)) for r in rows], total

    def update(self, equipment_id: str, **fields: Any) -> dict[str, Any] | None:
        self.ensure_ready()
        eid = equipment_id.strip()
        if not self.get(eid):
            return None
        mapping = {
            "name": "name",
            "kind": "kind",
            "region_id": "region_id",
            "description": "description",
            "platform_name": "platform_name",
            "platform_address": "platform_address",
            "thumbnail": "thumbnail",
            "data_type": "data_type",
            "unit": "unit",
            "online": "online",
            "simulate_video_relpath": "simulate_video_relpath",
        }
        sets: list[str] = []
        params: list[Any] = []
        for key, col in mapping.items():
            if key not in fields or fields[key] is None:
                continue
            val = fields[key]
            if key == "kind":
                k = str(val).strip().lower()
                if k not in ("camera", "sensor"):
                    raise ValueError("kind 须为 camera 或 sensor")
                val = k
            elif key == "online":
                val = 1 if bool(val) else 0
            elif key in (
                "name",
                "region_id",
                "description",
                "platform_name",
                "platform_address",
                "thumbnail",
                "data_type",
                "unit",
                "simulate_video_relpath",
            ):
                val = str(val)
            sets.append(f"{col} = ?")
            params.append(val)
        if not sets:
            return self.get(eid)
        sets.append("updated_at = ?")
        params.append(_utc_now())
        params.append(eid)
        conn = db.get_connection()
        try:
            conn.execute(f"UPDATE equipment SET {', '.join(sets)} WHERE id = ?", params)
            conn.commit()
        finally:
            conn.close()
        return self.get(eid)

    def delete(self, equipment_id: str) -> bool:
        self.ensure_ready()
        eid = equipment_id.strip()
        from inspection_platform.inspection_work.service import InspectionWorkService

        iw = InspectionWorkService()
        iw.ensure_ready()
        if iw.equipment_is_referenced(eid):
            raise ValueError(f"设备 {eid} 已被巡检业务引用，无法删除")
        self._remove_simulate_video_files(eid)
        conn = db.get_connection()
        try:
            cur = conn.execute("DELETE FROM equipment WHERE id = ?", (eid,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def delete_by_region_id(self, region_id: str) -> int:
        """删除指定区域内的全部设备（含传感器读数），用于区域删除级联。"""
        self.ensure_ready()
        rid = region_id.strip()
        conn = db.get_connection()
        try:
            rows = conn.execute(
                "SELECT id FROM equipment WHERE region_id = ?",
                (rid,),
            ).fetchall()
            for row in rows:
                self._remove_simulate_video_files(str(row["id"]))
            conn.execute(
                """
                DELETE FROM sensor_reading
                WHERE equipment_id IN (SELECT id FROM equipment WHERE region_id = ?)
                """,
                (rid,),
            )
            cur = conn.execute("DELETE FROM equipment WHERE region_id = ?", (rid,))
            conn.commit()
            return int(cur.rowcount)
        finally:
            conn.close()

    def batch_import(
        self,
        rows: list[dict[str, Any]],
        *,
        skip_existing: bool = True,
    ) -> dict[str, Any]:
        """按行批量创建设备；用于 CSV/JSON 导入。"""
        inserted = 0
        skipped = 0
        errors: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            name = str(row.get("name") or "").strip()
            if not name:
                errors.append({"row": index, "error": "设备名称不能为空"})
                continue
            kind = str(row.get("kind") or "camera").strip().lower()
            if kind not in ("camera", "sensor"):
                errors.append({"row": index, "error": "类型须为 camera、sensor 或 摄像头、传感器"})
                continue
            region_id = str(row.get("region_id") or "").strip()
            description = str(row.get("description") or "").strip()
            equipment_id = str(row.get("id") or "").strip() or None
            try:
                if equipment_id and self.get(equipment_id):
                    if skip_existing:
                        skipped += 1
                        continue
                    errors.append({"row": index, "error": f"设备 id {equipment_id} 已存在"})
                    continue
                self.create(
                    equipment_id=equipment_id,
                    kind=kind,
                    name=name,
                    region_id=region_id,
                    description=description,
                )
                inserted += 1
            except ValueError as e:
                errors.append({"row": index, "error": str(e)})
        return {"inserted": inserted, "skipped": skipped, "errors": errors}

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
                conn.execute("DELETE FROM equipment")
            now = _utc_now()
            for item in raw:
                if not isinstance(item, dict):
                    continue
                eid = str(item.get("id") or "").strip()
                if not eid:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM equipment WHERE id = ?",
                    (eid,),
                ).fetchone()
                if exists:
                    continue
                conn.execute(
                    """
INSERT INTO equipment (
    id, kind, name, region_id, description,
    platform_name, platform_address, thumbnail, data_type, unit, online,
    created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                    (
                        eid,
                        str(item.get("kind") or "camera").strip().lower(),
                        str(item.get("name") or eid),
                        str(item.get("region_id") or ""),
                        str(item.get("description") or ""),
                        str(item.get("platform_name") or ""),
                        str(item.get("platform_address") or ""),
                        str(item.get("thumbnail") or ""),
                        str(item.get("data_type") or ""),
                        str(item.get("unit") or ""),
                        1 if item.get("online", True) else 0,
                        now,
                        now,
                    ),
                )
                inserted += 1
            conn.commit()
        finally:
            conn.close()
        return inserted

    def list_readings(
        self,
        equipment_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        self.ensure_ready()
        eid = equipment_id.strip()
        conn = db.get_connection()
        try:
            total = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM sensor_reading WHERE equipment_id = ?",
                    (eid,),
                ).fetchone()["c"]
            )
            if total == 0:
                self._seed_demo_readings(conn, eid)
                conn.commit()
                total = int(
                    conn.execute(
                        "SELECT COUNT(*) AS c FROM sensor_reading WHERE equipment_id = ?",
                        (eid,),
                    ).fetchone()["c"]
                )
            limit = max(1, min(500, limit))
            offset = max(0, offset)
            rows = conn.execute(
                """
SELECT * FROM sensor_reading
WHERE equipment_id = ?
ORDER BY recorded_at DESC
LIMIT ? OFFSET ?
""",
                (eid, limit, offset),
            ).fetchall()
        finally:
            conn.close()
        return [db.reading_row_to_api(r) for r in rows], total

    def _seed_demo_readings(self, conn: sqlite3.Connection, equipment_id: str) -> None:
        row = conn.execute(
            "SELECT id, kind FROM equipment WHERE id = ?",
            (equipment_id,),
        ).fetchone()
        if not row or str(row["kind"]) != "sensor":
            return
        exists = conn.execute(
            "SELECT 1 FROM sensor_reading WHERE equipment_id = ? LIMIT 1",
            (equipment_id,),
        ).fetchone()
        if exists:
            return
        now = _utc_now()
        base_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        samples = [
            (f"{base_day} 08:00", 24.2, "normal"),
            (f"{base_day} 09:00", 25.1, "normal"),
            (f"{base_day} 10:00", 28.6, "warning"),
            (f"{base_day} 11:00", 31.2, "critical"),
            (f"{base_day} 12:00", 27.4, "warning"),
            (f"{base_day} 13:00", 25.0, "normal"),
        ]
        for recorded_at, value, status in samples:
            conn.execute(
                """
INSERT INTO sensor_reading (equipment_id, recorded_at, value, status, created_at)
VALUES (?, ?, ?, ?, ?)
""",
                (equipment_id, recorded_at, value, status, now),
            )

    def _remove_simulate_video_files(self, equipment_id: str) -> None:
        root = _simulate_video_dir(equipment_id)
        if root.is_dir():
            shutil.rmtree(root, ignore_errors=True)

    def resolve_simulate_video_path(self, equipment_id: str) -> Path | None:
        row = self.get(equipment_id)
        if not row:
            return None
        rel = str(row.get("simulate_video_relpath") or "").strip()
        if not rel:
            rel = _discover_simulate_relpath(equipment_id)
        if not rel:
            return None
        data_root = get_settings().data_path.resolve()
        path = (data_root / rel).resolve()
        try:
            path.relative_to(data_root)
        except ValueError:
            return None
        if path.is_file():
            return path
        return None

    def save_simulate_video(
        self,
        equipment_id: str,
        *,
        filename: str,
        content: bytes,
    ) -> dict[str, Any]:
        raise ValueError("平台已停用本地模拟视频，请在设备接入中配置 RTSP 地址")

    def clear_simulate_video(self, equipment_id: str) -> dict[str, Any] | None:
        eid = equipment_id.strip()
        row = self.get(eid)
        if not row:
            return None
        if str(row.get("kind") or "") != "camera":
            raise ValueError("仅摄像头支持模拟适配视频")
        self._remove_simulate_video_files(eid)
        return self.update(eid, simulate_video_relpath="")
