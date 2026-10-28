"""算法 CRUD、内置种子、模拟推理。"""

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


class AlgorithmService:
    def ensure_ready(self) -> None:
        """表结构在应用 lifespan 中 init_db()；请求路径勿重复初始化。"""

    def list_algorithms(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        health: str | None = None,
        q: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        self.ensure_ready()
        limit = max(1, min(500, limit))
        offset = max(0, offset)
        where: list[str] = []
        args: list[Any] = []
        if health and str(health).strip():
            where.append("health = ?")
            args.append(str(health).strip())
        if q and str(q).strip():
            where.append("(name LIKE ? OR `desc` LIKE ? OR algorithm_id LIKE ?)")
            pat = f"%{str(q).strip()}%"
            args.extend([pat, pat, pat])
        wh = (" WHERE " + " AND ".join(where)) if where else ""
        conn = db.get_connection()
        try:
            total = int(
                conn.execute(f"SELECT COUNT(*) AS c FROM algorithm{wh}", args).fetchone()["c"]
            )
            rows = conn.execute(
                f"SELECT * FROM algorithm{wh} ORDER BY algorithm_id LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
        finally:
            conn.close()
        return [db.row_to_api(r) for r in rows], total

    def get(self, algorithm_id: str) -> dict[str, Any] | None:
        self.ensure_ready()
        aid = algorithm_id.strip()
        conn = db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM algorithm WHERE algorithm_id = ?",
                (aid,),
            ).fetchone()
        finally:
            conn.close()
        return db.row_to_api(row) if row else None

    def create(
        self,
        *,
        algorithm_id: str | None,
        name: str,
        desc: str = "",
        link: str = "",
        schema: dict[str, Any] | None = None,
        health: str = "unknown",
    ) -> dict[str, Any]:
        self.ensure_ready()
        aid = (algorithm_id or "").strip() or f"algo_{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        schema_json = json.dumps(schema or {}, ensure_ascii=False)
        conn = db.get_connection()
        try:
            conn.execute(
                """
INSERT INTO algorithm (algorithm_id, name, `desc`, link, schema_json, health, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""",
                (aid, name.strip(), desc or "", link or "", schema_json, health or "unknown", now, now),
            )
            conn.commit()
        except Exception as e:
            if is_integrity_error(e):
                conn.rollback()
                raise ValueError("algorithm_id 已存在") from e
            raise
        finally:
            conn.close()
        got = self.get(aid)
        if not got:
            raise RuntimeError("insert failed")
        return got

    def update(
        self,
        algorithm_id: str,
        *,
        name: str | None = None,
        desc: str | None = None,
        link: str | None = None,
        schema: dict[str, Any] | None = None,
        health: str | None = None,
    ) -> dict[str, Any] | None:
        self.ensure_ready()
        aid = algorithm_id.strip()
        cur = self.get(aid)
        if not cur:
            return None
        n = cur["name"] if name is None else name
        d = cur["desc"] if desc is None else desc
        lnk = cur["link"] if link is None else link
        sch = cur["schema"] if schema is None else schema
        h = cur["health"] if health is None else health
        now = _utc_now()
        conn = db.get_connection()
        try:
            conn.execute(
                """
UPDATE algorithm SET name=?, `desc`=?, link=?, schema_json=?, health=?, updated_at=?
WHERE algorithm_id=?
""",
                (n, d, lnk, json.dumps(sch, ensure_ascii=False), h, now, aid),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get(aid)

    def delete(self, algorithm_id: str) -> bool:
        self.ensure_ready()
        aid = algorithm_id.strip()
        conn = db.get_connection()
        try:
            cur = conn.execute("DELETE FROM algorithm WHERE algorithm_id = ?", (aid,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def seed_builtin(self, *, replace_all: bool = False) -> int:
        """从包内 ``builtin_seed.json`` 导入；``replace_all`` 为真时先清空表。"""
        self.ensure_ready()
        path = _builtin_seed_path()
        if not path.is_file():
            raise FileNotFoundError(f"缺少内置种子文件: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("builtin_seed.json 须为 JSON 数组")
        now = _utc_now()
        conn = db.get_connection()
        try:
            if replace_all:
                conn.execute("DELETE FROM algorithm")
            n = 0
            for el in raw:
                if not isinstance(el, dict):
                    continue
                aid = str(el.get("algorithm_id") or "").strip()
                if not aid:
                    continue
                name = str(el.get("name") or "").strip() or aid
                desc = str(el.get("desc") or "")
                link = str(el.get("link") or f"/api/algorithm/invoke/{aid}")
                schema = el.get("schema") if isinstance(el.get("schema"), dict) else {}
                health = str(el.get("health") or "unknown").strip() or "unknown"
                sj = json.dumps(schema, ensure_ascii=False)
                conn.execute(
                    """
INSERT INTO algorithm (algorithm_id, name, `desc`, link, schema_json, health, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON DUPLICATE KEY UPDATE
  name=VALUES(name),
  `desc`=VALUES(`desc`),
  link=VALUES(link),
  schema_json=VALUES(schema_json),
  health=VALUES(health),
  updated_at=VALUES(updated_at)
""",
                    (aid, name, desc, link, sj, health, now, now),
                )
                n += 1
            conn.commit()
            return n
        finally:
            conn.close()

    def sync_from_vaio(self, items: list[dict[str, Any]], *, core_healthy: bool) -> dict[str, Any]:
        """将 vaio-analysis-core 算法目录 upsert 到 SQLite。"""
        self.ensure_ready()
        from .vaio_client import VAIO_MCP_TOOLS

        health = "healthy" if core_healthy else "degraded"
        now = _utc_now()
        synced = 0
        conn = db.get_connection()
        try:
            for el in items:
                if not isinstance(el, dict):
                    continue
                vaio_id = el.get("id")
                if vaio_id is None:
                    continue
                aid = f"vaio-{vaio_id}"
                name = str(el.get("name") or f"算法 {vaio_id}").strip()
                file_name = str(el.get("file") or "")
                desc = f"vaio 视频分析配方（{file_name or 'Algorithm_' + str(vaio_id) + '.json'}）。可通过 Hermes MCP 启动任务。"
                link = f"vaio://algorithms/{vaio_id}"
                schema = {
                    "vaio_id": vaio_id,
                    "file": file_name,
                    "source": "vaio-analysis-core",
                    "input": {"type": "video", "properties": {"video_url": {"type": "string"}}},
                    "mcp_server": "vaio_analysis",
                    "mcp_tools": VAIO_MCP_TOOLS,
                }
                sj = json.dumps(schema, ensure_ascii=False)
                conn.execute(
                    """
INSERT INTO algorithm (algorithm_id, name, `desc`, link, schema_json, health, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON DUPLICATE KEY UPDATE
  name=VALUES(name),
  `desc`=VALUES(`desc`),
  link=VALUES(link),
  schema_json=VALUES(schema_json),
  health=VALUES(health),
  updated_at=VALUES(updated_at)
""",
                    (aid, name, desc, link, sj, health, now, now),
                )
                synced += 1
            conn.commit()
        finally:
            conn.close()
        return {"synced": synced, "core_health": health}

    def mock_invoke(self, algorithm_id: str, body: dict[str, Any] | None) -> dict[str, Any]:
        """未接真实算法服务时的占位推理响应。"""
        cur = self.get(algorithm_id)
        if not cur:
            raise KeyError(algorithm_id)
        return {
            "algorithm_id": algorithm_id,
            "detected": False,
            "confidence": 0.0,
            "events": [],
            "echo": body or {},
            "note": "模拟推理：未连接真实算法服务，仅返回占位结构。",
        }
