"""region 元数据：独立 SQLite（表 region），与 document 无任何库级耦合。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .region_db import REGION_TABLE, get_region_connection


def _builtin_seed_path() -> Path:
    return Path(__file__).resolve().parent / "builtin_region_seed.json"


@dataclass
class RegionMetaRecord:
    id: str
    name: str
    desc: str
    parent_id: str
    sort_order: int
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "desc": self.desc,
            "parent_id": self.parent_id,
            "sort_order": self.sort_order,
            "created_at": self.created_at,
        }


def _row_to_record(row: sqlite3.Row) -> RegionMetaRecord:
    return RegionMetaRecord(
        id=str(row["id"]),
        name=str(row["name"] or ""),
        desc=str(row["desc"] or ""),
        parent_id=str(row["parent_id"] or ""),
        sort_order=int(row["sort_order"] or 0),
        created_at=str(row["created_at"]),
    )


class RegionMetaService:
    def ensure_ready(self) -> None:
        """region 表在 lifespan init_region_db 中初始化；请求路径无需重复 bootstrap。"""
        return None

    def create(
        self,
        *,
        id: str,
        name: str = "",
        desc: str = "",
        parent_id: str = "",
        sort_order: int = 0,
    ) -> dict[str, Any]:
        """仅插入；已存在则抛 ValueError（由路由转为 409）。"""
        rid = id.strip()
        if not rid:
            raise ValueError("id is required")
        if len(rid) > 256:
            raise ValueError("id too long (max 256)")
        nm = (name or "").strip()
        if len(nm) > 512:
            raise ValueError("name too long (max 512)")
        dc = (desc or "").strip()
        if len(dc) > 2048:
            raise ValueError("desc too long (max 2048)")
        pid = (parent_id or "").strip()
        if pid and pid == rid:
            raise ValueError("parent_id cannot equal id")
        if pid:
            try:
                self.get(pid)
            except KeyError as e:
                raise ValueError("parent region not found") from e
        now = datetime.now(timezone.utc).isoformat()
        conn = get_region_connection()
        try:
            cur = conn.execute(f"SELECT 1 FROM {REGION_TABLE} WHERE id = ?", (rid,))
            if cur.fetchone() is not None:
                raise ValueError("region id already exists")
            conn.execute(
                f"""
                INSERT INTO {REGION_TABLE} (id, name, `desc`, parent_id, sort_order, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (rid, nm, dc, pid, int(sort_order), now),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get(rid).as_dict()

    def update(
        self,
        id: str,
        *,
        name: str | None = None,
        desc: str | None = None,
        parent_id: str | None = None,
        sort_order: int | None = None,
    ) -> dict[str, Any]:
        """更新 name / desc / parent_id / sort_order；至少提供一个字段。"""
        rid = id.strip()
        if not rid:
            raise ValueError("id is required")
        if name is None and desc is None and parent_id is None and sort_order is None:
            raise ValueError("at least one field is required")
        rec = self.get(rid)
        nm = rec.name if name is None else (name or "").strip()
        dc = rec.desc if desc is None else (desc or "").strip()
        pid = rec.parent_id if parent_id is None else (parent_id or "").strip()
        order = rec.sort_order if sort_order is None else int(sort_order)
        if len(nm) > 512:
            raise ValueError("name too long (max 512)")
        if len(dc) > 2048:
            raise ValueError("desc too long (max 2048)")
        if pid == rid:
            raise ValueError("parent_id cannot equal id")
        if pid:
            try:
                self.get(pid)
            except KeyError as e:
                raise ValueError("parent region not found") from e
        conn = get_region_connection()
        try:
            cur = conn.execute(
                f"UPDATE {REGION_TABLE} SET name = ?, `desc` = ?, parent_id = ?, sort_order = ? WHERE id = ?",
                (nm, dc, pid, order, rid),
            )
            if cur.rowcount == 0:
                raise KeyError(rid)
            conn.commit()
        finally:
            conn.close()
        return self.get(rid).as_dict()

    def list_regions(self) -> list[dict[str, Any]]:
        conn = get_region_connection()
        try:
            cur = conn.execute(
                f"""
                SELECT id, name, `desc`, parent_id, sort_order, created_at
                FROM {REGION_TABLE}
                ORDER BY sort_order ASC, name ASC, id ASC
                """
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        return [_row_to_record(r).as_dict() for r in rows]

    def count_children(self, id: str) -> int:
        conn = get_region_connection()
        try:
            cur = conn.execute(
                f"SELECT COUNT(1) AS cnt FROM {REGION_TABLE} WHERE parent_id = ?",
                (id.strip(),),
            )
            row = cur.fetchone()
        finally:
            conn.close()
        return int(row["cnt"] if row else 0)

    def get(self, id: str) -> RegionMetaRecord:
        conn = get_region_connection()
        try:
            cur = conn.execute(
                f"SELECT id, name, `desc`, parent_id, sort_order, created_at FROM {REGION_TABLE} WHERE id = ?",
                (id.strip(),),
            )
            row = cur.fetchone()
        finally:
            conn.close()
        if row is None:
            raise KeyError(id)
        return _row_to_record(row)

    def delete(self, id: str) -> None:
        rid = id.strip()
        if self.count_children(rid) > 0:
            raise ValueError("请先删除所有子区域")
        conn = get_region_connection()
        try:
            cur = conn.execute(f"DELETE FROM {REGION_TABLE} WHERE id = ?", (rid,))
            conn.commit()
            if cur.rowcount == 0:
                raise KeyError(rid)
        finally:
            conn.close()

    def seed_builtin(self, *, replace_all: bool = False) -> int:
        """从 ``builtin_region_seed.json`` 导入区域；``replace_all`` 为真时先清空表。"""
        path = _builtin_seed_path()
        if not path.is_file():
            raise FileNotFoundError(f"缺少内置种子文件: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("builtin_region_seed.json 须为 JSON 数组")
        rows = [el for el in raw if isinstance(el, dict) and str(el.get("id") or "").strip()]
        rows.sort(
            key=lambda r: (
                0 if not str(r.get("parent_id") or "").strip() else 1,
                int(r.get("sort_order") or 0),
                str(r.get("id") or ""),
            ),
        )
        now = datetime.now(timezone.utc).isoformat()
        conn = get_region_connection()
        try:
            if replace_all:
                conn.execute(f"DELETE FROM {REGION_TABLE}")
            n = 0
            for el in rows:
                rid = str(el.get("id") or "").strip()
                nm = str(el.get("name") or "").strip() or rid
                dc = str(el.get("desc") or "").strip()
                pid = str(el.get("parent_id") or "").strip()
                order = int(el.get("sort_order") or 0)
                conn.execute(
                    f"""
                    INSERT INTO {REGION_TABLE} (id, name, `desc`, parent_id, sort_order, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON DUPLICATE KEY UPDATE
                      name=VALUES(name),
                      `desc`=VALUES(`desc`),
                      parent_id=VALUES(parent_id),
                      sort_order=VALUES(sort_order)
                    """,
                    (rid, nm, dc, pid, order, now),
                )
                n += 1
            conn.commit()
            return n
        finally:
            conn.close()
