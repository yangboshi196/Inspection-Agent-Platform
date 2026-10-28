"""巡检事件 CRUD、看板统计、巡检业务运行态。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from inspection_platform.document.region_meta import RegionMetaService
from inspection_platform.equipment.service import EquipmentService
from inspection_platform.equipment.stream_url import normalize_stream_url
from inspection_platform.inspection_work.service import InspectionWorkService

from . import db
from .evidence import (
    attach_rtsp_snapshot_to_event,
    remove_evidence_files,
    snapshot_data_url,
    snapshot_file,
)

_WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_WEEKDAY_SUN_SAT = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]


def _snapshot_judgment_aligned(parsed: dict[str, Any]) -> bool:
    return str(parsed.get("judgment_source") or "") in ("snapshot_llm", "vaio_alert_frame")


def _resolution_detail_from_detection_payload(
    parsed: dict[str, Any],
    *,
    prior_detail: str = "",
) -> str | None:
    """从 detection_json 推导应展示的判定说明。"""
    prior = prior_detail.strip()
    if parsed.get("snapshot_mismatch"):
        note = str(parsed.get("judgment_note") or "抓拍与检测未对齐").strip()
        if prior and prior != note and not prior.startswith(note):
            return f"{note}（原判定：{prior[:200]}）"
        return note
    desc = str(parsed.get("llm_description") or "").strip()
    if desc:
        return desc[:500]
    return None

def _calendar_week_sun_sat(reference: datetime) -> tuple[datetime, datetime]:
    """含 reference 的自然周：周日 00:00 至周六（同日历日）。"""
    ref_day = reference.date()
    days_since_sunday = (reference.weekday() + 1) % 7
    sun = ref_day - timedelta(days=days_since_sunday)
    sat = sun + timedelta(days=6)
    return (
        datetime.combine(sun, datetime.min.time()).replace(tzinfo=timezone.utc),
        datetime.combine(sat, datetime.min.time()).replace(tzinfo=timezone.utc),
    )


def _utc_now() -> str:
    from inspection_platform.timeutil import utc_now_iso

    return utc_now_iso()


def _builtin_seed_path() -> Path:
    return Path(__file__).resolve().parent / "builtin_seed.json"


def _parse_occurred_day(occurred_at: str) -> str:
    s = (occurred_at or "").strip()
    if len(s) >= 10:
        return s[:10]
    return s


def _parse_occurred_hour(occurred_at: str) -> int:
    s = (occurred_at or "").strip()
    if len(s) >= 13 and s[10] in ("T", " ", ":"):
        try:
            return max(0, min(23, int(s[11:13])))
        except ValueError:
            pass
    return 0


def _parse_seed_datetime(s: str) -> datetime | None:
    s = (s or "").strip()
    if len(s) >= 19:
        try:
            return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    if len(s) >= 16:
        try:
            return datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            pass
    if len(s) >= 10:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            pass
    return None


def _format_seed_datetime(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _seed_reference_day(rows: list[Any]) -> datetime.date:
    dates: list[datetime.date] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        for key in ("occurred_at", "reported_at", "handled_at"):
            dt = _parse_seed_datetime(str(raw.get(key) or ""))
            if dt:
                dates.append(dt.date())
    if dates:
        return max(dates)
    return datetime.now(timezone.utc).date()


def _shift_seed_datetime(raw: str, *, ref_day: datetime.date, today: datetime.date) -> str:
    dt = _parse_seed_datetime(raw)
    if not dt:
        return raw
    days_ago = (ref_day - dt.date()).days
    target = today - timedelta(days=days_ago)
    shifted = datetime.combine(target, dt.time())
    return _format_seed_datetime(shifted)


class InspectionEventService:
    def ensure_ready(self) -> None:
        """表结构在应用 lifespan 中 init_db()；请求路径勿重复初始化。"""

    def seed_builtin(self) -> int:
        self.ensure_ready()
        path = _builtin_seed_path()
        if not path.is_file():
            return 0
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            return 0
        now = _utc_now()
        ref_day = _seed_reference_day(rows)
        today = datetime.now(timezone.utc).date()
        inserted = 0
        conn = db.get_connection()
        try:
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                eid = str(raw.get("event_id") or "").strip()
                if not eid:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM inspection_event WHERE event_id = ?",
                    (eid,),
                ).fetchone()
                if exists:
                    continue
                occurred_at = _shift_seed_datetime(
                    str(raw.get("occurred_at") or now),
                    ref_day=ref_day,
                    today=today,
                )
                reported_raw = str(raw.get("reported_at") or "")
                reported_at = (
                    _shift_seed_datetime(reported_raw, ref_day=ref_day, today=today)
                    if reported_raw
                    else ""
                )
                handled_raw = str(raw.get("handled_at") or "")
                handled_at = (
                    _shift_seed_datetime(handled_raw, ref_day=ref_day, today=today)
                    if handled_raw
                    else ""
                )
                conn.execute(
                    """
INSERT INTO inspection_event (
    event_id, kind, title, source_name, work_id, work_name,
    region_id, region_name, equipment_id, algorithm_name, rule_name,
    status, value_num, threshold_text, snapshot_gradient,
    occurred_at, reported_at, handler, handled_at,
    resolution_outcome, resolution_detail, detection_json, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                    (
                        eid,
                        str(raw.get("kind") or "video").strip(),
                        str(raw.get("title") or "").strip(),
                        str(raw.get("source_name") or ""),
                        str(raw.get("work_id") or ""),
                        str(raw.get("work_name") or ""),
                        str(raw.get("region_id") or ""),
                        str(raw.get("region_name") or ""),
                        str(raw.get("equipment_id") or ""),
                        str(raw.get("algorithm_name") or ""),
                        str(raw.get("rule_name") or ""),
                        str(raw.get("status") or "pending"),
                        raw.get("value_num"),
                        str(raw.get("threshold_text") or ""),
                        str(raw.get("snapshot_gradient") or ""),
                        occurred_at,
                        reported_at,
                        str(raw.get("handler") or ""),
                        handled_at,
                        str(raw.get("resolution_outcome") or ""),
                        str(raw.get("resolution_detail") or ""),
                        str(raw.get("detection_json") or ""),
                        now,
                        now,
                    ),
                )
                inserted += 1
            conn.commit()
        finally:
            conn.close()
        return inserted

    def create(
        self,
        *,
        event_id: str | None = None,
        kind: str,
        title: str,
        source_name: str = "",
        work_id: str = "",
        work_name: str = "",
        region_id: str = "",
        region_name: str = "",
        equipment_id: str = "",
        algorithm_name: str = "",
        rule_name: str = "",
        status: str = "pending",
        value_num: float | None = None,
        threshold_text: str = "",
        snapshot_gradient: str = "",
        occurred_at: str | None = None,
        reported_at: str = "",
        handler: str = "",
        handled_at: str = "",
        resolution_outcome: str = "",
        resolution_detail: str = "",
        detection_json: str = "",
    ) -> dict[str, Any]:
        self.ensure_ready()
        eid = (event_id or "").strip() or f"ev-{uuid.uuid4().hex[:12]}"
        k = kind.strip().lower()
        if k not in ("video", "sensor"):
            raise ValueError("kind 须为 video 或 sensor")
        if not title.strip():
            raise ValueError("title 不能为空")
        st = (status or "pending").strip()
        if st not in ("pending", "processing", "resolved", "ignored"):
            raise ValueError("status must be pending, processing, resolved, or ignored")
        now = _utc_now()
        occurred = (occurred_at or "").strip() or now
        conn = db.get_connection()
        try:
            conn.execute(
                """
INSERT INTO inspection_event (
    event_id, kind, title, source_name, work_id, work_name,
    region_id, region_name, equipment_id, algorithm_name, rule_name,
    status, value_num, threshold_text, snapshot_gradient,
    occurred_at, reported_at, handler, handled_at,
    resolution_outcome, resolution_detail, detection_json, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                (
                    eid,
                    k,
                    title.strip(),
                    source_name or "",
                    work_id or "",
                    work_name or "",
                    region_id or "",
                    region_name or "",
                    equipment_id or "",
                    algorithm_name or "",
                    rule_name or "",
                    st,
                    value_num,
                    threshold_text or "",
                    snapshot_gradient or "",
                    occurred,
                    reported_at or "",
                    handler or "",
                    handled_at or "",
                    resolution_outcome or "",
                    resolution_detail or "",
                    detection_json or "",
                    now,
                    now,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            conn.rollback()
            raise ValueError("event_id 已存在") from e
        finally:
            conn.close()
        row = self.get(eid)
        if not row:
            raise RuntimeError("创建事件后读取失败")
        return row

    def get(self, event_id: str, *, refill_boxes: bool = True) -> dict[str, Any] | None:
        self.ensure_ready()
        conn = db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM inspection_event WHERE event_id = ?",
                (event_id.strip(),),
            ).fetchone()
        finally:
            conn.close()
        return self._enrich_event(
            db.row_to_api(row) if row else None,
            refill_boxes=refill_boxes,
        )

    def _enrich_event(
        self,
        row: dict[str, Any] | None,
        *,
        refill_boxes: bool = False,
    ) -> dict[str, Any] | None:
        if not row:
            return None
        out = dict(row)
        event_id = str(out.get("event_id") or "").strip()
        detection_raw = str(out.get("detection_json") or "").strip()
        detection: dict[str, Any] = {}
        if detection_raw:
            try:
                parsed = json.loads(detection_raw)
                if isinstance(parsed, dict):
                    detection = parsed
            except json.JSONDecodeError:
                detection = {}

        media_video = str(detection.get("evidence_video_url") or "").strip()
        media_snapshot = str(detection.get("snapshot_url") or "").strip()
        if not media_snapshot and event_id and snapshot_file(event_id).is_file():
            media_snapshot = snapshot_data_url(event_id)

        eid = str(out.get("equipment_id") or "").strip()
        equipment_online = False
        has_rtsp = False
        if eid:
            equip = EquipmentService()
            equip.ensure_ready()
            eq = equip.get(eid)
            if eq:
                equipment_online = bool(eq.get("online"))
                platform_addr = str(eq.get("platform_address") or "").strip()
                has_rtsp = bool(normalize_stream_url(platform_addr))
                if has_rtsp:
                    out["media_live_flv_url"] = (
                        f"/api/equipment/{eid}/live/webrtc/embed?stream=main&quality=hd"
                    )
                    out["media_live_snapshot_url"] = (
                        f"/api/equipment/{eid}/live/snapshot?stream=main&quality=hd"
                    )
                    media_video = ""

        out["media_video_url"] = media_video
        out["media_snapshot_url"] = media_snapshot
        out["media_has_rtsp"] = has_rtsp
        out["equipment_online"] = equipment_online
        if refill_boxes:
            out = self._maybe_refill_detection_boxes(out)
        return out

    def _apply_resolution_from_detection(
        self,
        event_id: str,
        row: dict[str, Any],
        parsed: dict[str, Any],
    ) -> dict[str, Any]:
        detail = _resolution_detail_from_detection_payload(
            parsed,
            prior_detail=str(row.get("resolution_detail") or ""),
        )
        if detail is None or detail == str(row.get("resolution_detail") or "").strip():
            return row
        updated = self.update(event_id, resolution_detail=detail)
        return updated if updated else row

    def _maybe_refill_detection_boxes(self, row: dict[str, Any]) -> dict[str, Any]:
        """单条读取时：有抓拍但无 boxes 则尝试 LLM 补框（避免详情页空白）。"""
        if str(row.get("kind") or "") != "video":
            return row
        event_id = str(row.get("event_id") or "").strip()
        algo_name = str(row.get("algorithm_name") or "").strip()
        dj = str(row.get("detection_json") or "")
        if not event_id:
            return row
        try:
            parsed = json.loads(dj) if dj.strip() else {}
            if (
                isinstance(parsed, dict)
                and parsed.get("boxes")
                and parsed.get("snapshot_aligned")
                and parsed.get("judgment_source") in ("snapshot_llm", "vaio_alert_frame")
                and not parsed.get("snapshot_mismatch")
            ):
                return row
        except json.JSONDecodeError:
            pass
        equipment_id = str(row.get("equipment_id") or "").strip()
        if not snapshot_file(event_id).is_file() and equipment_id:
            from inspection_platform.inspection_event.evidence import repair_snapshot_from_rtsp

            dj = repair_snapshot_from_rtsp(event_id, equipment_id, dj)
        if not snapshot_file(event_id).is_file():
            return row
        try:
            parsed = json.loads(dj) if dj.strip() else {}
            if (
                isinstance(parsed, dict)
                and parsed.get("boxes")
                and parsed.get("snapshot_aligned")
                and parsed.get("judgment_source") in ("snapshot_llm", "vaio_alert_frame")
                and not parsed.get("snapshot_mismatch")
            ):
                return row
        except json.JSONDecodeError:
            pass
        from inspection_platform.inspection_work.runner import (
            _detecttype_from_algo_name,
            refill_event_detection_boxes,
        )

        detecttype = _detecttype_from_algo_name(algo_name)
        try:
            parsed = json.loads(dj) if dj.strip() else {}
            if isinstance(parsed, dict) and equipment_id:
                parsed["equipment_id"] = equipment_id
                dj = json.dumps(parsed, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
        new_dj = refill_event_detection_boxes(
            event_id,
            dj,
            detecttype=detecttype,
            params={},
            force_snapshot_align=True,
        )
        try:
            parsed_new = json.loads(new_dj) if new_dj.strip() else {}
        except json.JSONDecodeError:
            return row
        if not isinstance(parsed_new, dict):
            return row
        got_boxes = bool(parsed_new.get("boxes"))
        snapshot_mismatch = bool(parsed_new.get("snapshot_mismatch"))
        snapshot_aligned_ok = _snapshot_judgment_aligned(parsed_new)
        if new_dj == dj and not snapshot_mismatch and not snapshot_aligned_ok:
            return row
        if not got_boxes and not snapshot_mismatch:
            return row
        updated = self.update_detection_json(event_id, new_dj)
        out = updated if updated else {**row, "detection_json": new_dj}
        if isinstance(parsed_new, dict):
            out = self._apply_resolution_from_detection(event_id, out, parsed_new)
        return out

    def sync_video_event_media(self, *, limit: int = 80) -> dict[str, Any]:
        """为缺少取证抓拍的视频事件从 RTSP 补同步单帧（以服务器侧设备配置为准）。"""
        self.ensure_ready()
        limit = max(1, min(500, int(limit)))
        equip = EquipmentService()
        equip.ensure_ready()
        conn = db.get_connection()
        try:
            rows = conn.execute(
                """
SELECT event_id, equipment_id, detection_json FROM inspection_event
WHERE kind = 'video' AND equipment_id IS NOT NULL AND equipment_id != ''
ORDER BY occurred_at DESC LIMIT ?
""",
                (limit,),
            ).fetchall()
        finally:
            conn.close()

        updated = 0
        skipped = 0
        failed = 0
        for row in rows:
            event_id = str(row["event_id"] or "").strip()
            equipment_id = str(row["equipment_id"] or "").strip()
            if not event_id or not equipment_id:
                skipped += 1
                continue
            eq = equip.get(equipment_id)
            if not eq:
                skipped += 1
                continue
            rtsp = normalize_stream_url(str(eq.get("platform_address") or ""))
            if not rtsp:
                skipped += 1
                continue
            dj = str(row["detection_json"] or "")
            try:
                parsed = json.loads(dj) if dj.strip() else {}
                has_url = isinstance(parsed, dict) and str(parsed.get("snapshot_url") or "").strip()
            except json.JSONDecodeError:
                has_url = False
            if has_url and snapshot_file(event_id).is_file():
                skipped += 1
                continue
            try:
                new_dj = attach_rtsp_snapshot_to_event(event_id, dj, rtsp)
            except Exception:
                failed += 1
                continue
            if new_dj == dj:
                failed += 1
                continue
            conn = db.get_connection()
            try:
                conn.execute(
                    "UPDATE inspection_event SET detection_json = ?, updated_at = ? WHERE event_id = ?",
                    (new_dj, _utc_now(), event_id),
                )
                conn.commit()
                updated += 1
            finally:
                conn.close()

        return {"updated": updated, "skipped": skipped, "failed": failed, "scanned": len(rows)}

    def clear_all(self) -> int:
        """清空全部巡检事件及取证文件。"""
        self.ensure_ready()
        conn = db.get_connection()
        try:
            rows = conn.execute("SELECT event_id FROM inspection_event").fetchall()
            event_ids = [str(r["event_id"]) for r in rows if r["event_id"]]
            conn.execute("DELETE FROM inspection_event")
            conn.commit()
        finally:
            conn.close()
        for eid in event_ids:
            remove_evidence_files(eid)
        return len(event_ids)

    def sync_detection_boxes(self, *, limit: int = 80) -> dict[str, Any]:
        """为已有事件补全 detection_json 中的检测框（与服务器抓拍对齐）。"""
        from inspection_platform.inspection_event.evidence import (
            repair_snapshot_from_rtsp,
            snapshot_file,
        )
        from inspection_platform.inspection_work.runner import (
            _detecttype_from_algo_name,
            refill_event_detection_boxes,
        )

        self.ensure_ready()
        limit = max(1, min(300, int(limit)))
        conn = db.get_connection()
        try:
            rows = conn.execute(
                """
SELECT event_id, algorithm_name, detection_json, equipment_id, resolution_detail FROM inspection_event
WHERE kind = 'video'
ORDER BY occurred_at DESC LIMIT ?
""",
                (limit,),
            ).fetchall()
        finally:
            conn.close()

        updated = 0
        skipped = 0
        failed = 0
        for row in rows:
            event_id = str(row["event_id"] or "").strip()
            algo_name = str(row["algorithm_name"] or "").strip()
            equipment_id = str(row["equipment_id"] or "").strip()
            dj = str(row["detection_json"] or "")
            if not event_id:
                skipped += 1
                continue
            try:
                parsed = json.loads(dj) if dj.strip() else {}
                needs_realign = False
                if isinstance(parsed, dict):
                    fm = parsed.get("frame_ms")
                    try:
                        if fm is not None and int(fm) > 3_600_000:
                            needs_realign = True
                    except (TypeError, ValueError):
                        pass
                    vts = parsed.get("video_time_sec")
                    try:
                        if vts is not None and float(vts) > 3600:
                            needs_realign = True
                    except (TypeError, ValueError):
                        pass
                    sp = snapshot_file(event_id)
                    if sp.is_file():
                        from inspection_platform.inspection_event.evidence import _jpeg_dimensions

                        sw, sh = _jpeg_dimensions(sp)
                        if (
                            int(parsed.get("source_width") or 0) != sw
                            or int(parsed.get("source_height") or 0) != sh
                        ):
                            needs_realign = True
                    if (
                        not needs_realign
                        and parsed.get("boxes")
                        and parsed.get("snapshot_aligned")
                        and parsed.get("judgment_source") in ("snapshot_llm", "vaio_alert_frame")
                        and not parsed.get("snapshot_mismatch")
                    ):
                        skipped += 1
                        continue
                    if needs_realign and isinstance(parsed, dict):
                        parsed["boxes"] = []
                        parsed.pop("snapshot_aligned", None)
                        parsed.pop("frame_ms", None)
                        parsed.pop("video_time_sec", None)
                        dj = json.dumps(parsed, ensure_ascii=False)
            except json.JSONDecodeError:
                pass
            if not snapshot_file(event_id).is_file() and equipment_id:
                dj = repair_snapshot_from_rtsp(event_id, equipment_id, dj)
            if not snapshot_file(event_id).is_file():
                skipped += 1
                continue
            detecttype = _detecttype_from_algo_name(algo_name)
            try:
                parsed = json.loads(dj) if dj.strip() else {}
                if isinstance(parsed, dict) and equipment_id:
                    parsed["equipment_id"] = equipment_id
                    dj = json.dumps(parsed, ensure_ascii=False)
            except json.JSONDecodeError:
                pass
            new_dj = refill_event_detection_boxes(
                event_id,
                dj,
                detecttype=detecttype,
                params={},
                force_snapshot_align=True,
            )
            try:
                parsed_new = json.loads(new_dj) if new_dj.strip() else {}
                got_boxes = isinstance(parsed_new, dict) and bool(parsed_new.get("boxes"))
            except json.JSONDecodeError:
                got_boxes = False
            if new_dj == dj and not got_boxes and not (
                isinstance(parsed_new, dict) and parsed_new.get("snapshot_mismatch")
            ):
                failed += 1
                continue
            detail = None
            if isinstance(parsed_new, dict):
                detail = _resolution_detail_from_detection_payload(
                    parsed_new,
                    prior_detail=str(row["resolution_detail"] or ""),
                )
            conn = db.get_connection()
            try:
                conn.execute(
                    "UPDATE inspection_event SET detection_json = ?, updated_at = ? WHERE event_id = ?",
                    (new_dj, _utc_now(), event_id),
                )
                if detail is not None:
                    conn.execute(
                        "UPDATE inspection_event SET resolution_detail = ? WHERE event_id = ?",
                        (detail, event_id),
                    )
                conn.commit()
                updated += 1
            finally:
                conn.close()

        return {
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
            "scanned": len(rows),
        }

    def update_detection_json(self, event_id: str, detection_json: str) -> dict[str, Any] | None:
        self.ensure_ready()
        eid = event_id.strip()
        existing = self.get(eid, refill_boxes=False)
        if not existing:
            return None
        now = _utc_now()
        conn = db.get_connection()
        try:
            conn.execute(
                "UPDATE inspection_event SET detection_json = ?, updated_at = ? WHERE event_id = ?",
                (detection_json or "", now, eid),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get(eid, refill_boxes=False)

    def list_events(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        work_id: str | None = None,
        region_id: str | None = None,
        q: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        self.ensure_ready()
        limit = max(1, min(500, limit))
        offset = max(0, offset)
        where: list[str] = []
        args: list[Any] = []
        if kind and kind.strip():
            where.append("kind = ?")
            args.append(kind.strip())
        if status and status.strip():
            where.append("status = ?")
            args.append(status.strip())
        if work_id and work_id.strip():
            where.append("work_id = ?")
            args.append(work_id.strip())
        if region_id and region_id.strip():
            where.append("region_id = ?")
            args.append(region_id.strip())
        if q and q.strip():
            pat = f"%{q.strip()}%"
            where.append(
                "(title LIKE ? OR source_name LIKE ? OR work_name LIKE ? OR region_name LIKE ?)"
            )
            args.extend([pat, pat, pat, pat])
        wh = (" WHERE " + " AND ".join(where)) if where else ""
        conn = db.get_connection()
        try:
            total = int(
                conn.execute(f"SELECT COUNT(*) AS c FROM inspection_event{wh}", args).fetchone()["c"]
            )
            rows = conn.execute(
                f"SELECT * FROM inspection_event{wh} ORDER BY occurred_at DESC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
        finally:
            conn.close()
        return [self._enrich_event(db.row_to_api(r), refill_boxes=False) for r in rows if r], total

    def update(
        self,
        event_id: str,
        *,
        status: str | None = None,
        handler: str | None = None,
        handled_at: str | None = None,
        resolution_outcome: str | None = None,
        resolution_detail: str | None = None,
    ) -> dict[str, Any] | None:
        self.ensure_ready()
        eid = event_id.strip()
        existing = self.get(eid)
        if not existing:
            return None
        st = existing["status"] if status is None else status.strip()
        if st not in ("pending", "processing", "resolved", "ignored"):
            raise ValueError("status must be pending, processing, resolved, or ignored")
        now = _utc_now()
        conn = db.get_connection()
        try:
            conn.execute(
                """
UPDATE inspection_event SET
    status = ?, handler = ?, handled_at = ?,
    resolution_outcome = ?, resolution_detail = ?, updated_at = ?
WHERE event_id = ?
""",
                (
                    st,
                    existing["handler"] if handler is None else handler,
                    existing["handled_at"] if handled_at is None else handled_at,
                    existing["resolution_outcome"] if resolution_outcome is None else resolution_outcome,
                    existing["resolution_detail"] if resolution_detail is None else resolution_detail,
                    now,
                    eid,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get(eid)

    def delete(self, event_id: str) -> bool:
        self.ensure_ready()
        eid = event_id.strip()
        conn = db.get_connection()
        try:
            cur = conn.execute(
                "DELETE FROM inspection_event WHERE event_id = ?",
                (eid,),
            )
            conn.commit()
            deleted = cur.rowcount > 0
        finally:
            conn.close()
        if deleted:
            remove_evidence_files(eid)
        return deleted

    def dashboard_stats(
        self,
        *,
        trend_days: int = 7,
        trend_group_by: str = "event_type",
        trend_status: str | None = None,
        trend_kind: str | None = None,
        trend_region_id: str | None = None,
        trend_date: str | None = None,
        weekly_work_id: str | None = None,
        weekly_risk_type: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_ready()
        conn = db.get_connection()
        try:
            total = int(conn.execute("SELECT COUNT(*) AS c FROM inspection_event").fetchone()["c"])
            pending = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM inspection_event WHERE status IN ('pending', 'processing')"
                ).fetchone()["c"]
            )
            today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM inspection_event WHERE occurred_at LIKE ?",
                    (f"{today_prefix}%",),
                ).fetchone()["c"]
            )
            yesterday_prefix = (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
                "%Y-%m-%d"
            )
            yesterday_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM inspection_event WHERE occurred_at LIKE ?",
                    (f"{yesterday_prefix}%",),
                ).fetchone()["c"]
            )
            anchor = self._trend_anchor_end(conn)
            week_ref = datetime.now(timezone.utc)
            week_start, week_end = _calendar_week_sun_sat(week_ref)
            weekly_trend_kpi = self._weekly_execution_trend(conn, week_ref=week_ref)
            weekly_trend = self._weekly_execution_trend(
                conn,
                week_ref=week_ref,
                work_id=weekly_work_id,
                risk_title=weekly_risk_type,
            )
            risk_type_options = self._distinct_event_titles(conn, anchor_end=anchor, span_days=30)
            filter_kw = dict(
                status=trend_status,
                kind=trend_kind,
                region_id=trend_region_id,
            )
            trend_field = self._trend_group_field(trend_group_by)
            day_pick = (trend_date or "").strip()[:10]
            if day_pick:
                days = 1
                granularity = "hour"
                trend_raw, trend_labels = self._trend_by_hour(
                    conn, trend_field, day=day_pick, **filter_kw
                )
                trend_by_type, _ = self._trend_by_hour(conn, "title", day=day_pick, **filter_kw)
                trend_by_region, _ = self._trend_by_hour(
                    conn, "region_name", day=day_pick, **filter_kw
                )
                trend_by_work, _ = self._trend_by_hour(conn, "work_name", day=day_pick, **filter_kw)
                day_events = self._events_on_day(conn, day=day_pick, **filter_kw)
                available_dates = self._available_event_dates(conn, anchor_end=anchor, span_days=30)
            else:
                days = max(7, min(30, int(trend_days)))
                granularity = "day"
                trend_kw = dict(days=days, **filter_kw)
                trend_raw, trend_labels = self._trend_by_field(
                    conn, trend_field, anchor_end=anchor, **trend_kw
                )
                trend_by_type, _ = self._trend_by_field(conn, "title", anchor_end=anchor, **trend_kw)
                trend_by_region, _ = self._trend_by_field(
                    conn, "region_name", anchor_end=anchor, **trend_kw
                )
                trend_by_work, _ = self._trend_by_field(conn, "work_name", anchor_end=anchor, **trend_kw)
                day_events = []
                available_dates = self._available_event_dates(
                    conn, anchor_end=anchor, span_days=days
                )
            week_alerts = sum(d["alerts"] for d in weekly_trend_kpi)
            week_resolved = sum(d["resolved"] for d in weekly_trend_kpi)
            prev_sun = week_start - timedelta(days=7)
            prev_week_alerts = int(
                conn.execute(
                    """
SELECT COUNT(*) AS c FROM inspection_event
WHERE occurred_at >= ? AND occurred_at < ?
""",
                    [
                        prev_sun.strftime("%Y-%m-%d"),
                        week_start.strftime("%Y-%m-%d"),
                    ],
                ).fetchone()["c"]
            )
            alert_delta = week_alerts - prev_week_alerts
        finally:
            conn.close()

        equip = EquipmentService()
        equip.ensure_ready()
        cameras, cam_total = equip.list_equipment(kind="camera", limit=1)
        sensors, sen_total = equip.list_equipment(kind="sensor", limit=1)
        _ = cameras, sensors

        rw = InspectionWorkService()
        rw.ensure_ready()
        works, work_total = rw.list_all(limit=1)

        return {
            "kpi": {
                "inspections_today": today_count,
                "inspections_delta": today_count - yesterday_count,
                "pending_events": pending,
                "alert_delta": alert_delta,
                "alerts_week": week_alerts,
                "resolved_week": week_resolved,
                "camera_count": cam_total,
                "sensor_count": sen_total,
                "device_total": cam_total + sen_total,
                "active_works": work_total,
                "event_total": total,
            },
            "weekly_trend": weekly_trend,
            "risk_type_options": risk_type_options,
            "weekly_meta": {
                "days": 7,
                "week_start": week_start.strftime("%Y-%m-%d"),
                "week_end": week_end.strftime("%Y-%m-%d"),
                "work_id": (weekly_work_id or "").strip() or None,
                "risk_type": (weekly_risk_type or "").strip() or None,
            },
            "event_trend_by_type": trend_by_type,
            "event_trend_by_region": trend_by_region,
            "event_trend_by_work": trend_by_work,
            "event_trend": trend_raw,
            "trend_labels": trend_labels,
            "trend_meta": {
                "days": days,
                "granularity": granularity,
                "group_by": trend_group_by,
                "status": trend_status or "all",
                "kind": trend_kind or "all",
                "region_id": (trend_region_id or "").strip() or None,
                "anchor_date": anchor.strftime("%Y-%m-%d"),
                "trend_date": day_pick or None,
            },
            "day_events": day_events,
            "available_dates": available_dates,
        }

    def _trend_anchor_end(self, conn: sqlite3.Connection) -> datetime:
        """趋势图时间轴终点：优先取库内最近事件日，避免演示数据日期与「今天」错位导致全 0。"""
        row = conn.execute("SELECT MAX(occurred_at) AS m FROM inspection_event").fetchone()
        if row and row["m"]:
            day = _parse_occurred_day(str(row["m"]))
            try:
                return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _trend_group_field(group_by: str) -> str:
        mapping = {
            "event_type": "title",
            "title": "title",
            "work": "work_name",
            "region": "region_name",
            "kind": "kind",
        }
        return mapping.get((group_by or "").strip(), "title")

    def _weekly_execution_trend(
        self,
        conn: sqlite3.Connection,
        *,
        week_ref: datetime | None = None,
        work_id: str | None = None,
        risk_title: str | None = None,
    ) -> list[dict[str, Any]]:
        """本周巡检执行：自然周周日—周六，巡检次数与告警/处置分开统计。"""
        ref = week_ref or datetime.now(timezone.utc)
        week_start, _ = _calendar_week_sun_sat(ref)
        out: list[dict[str, Any]] = []
        wid = (work_id or "").strip()
        risk = (risk_title or "").strip()
        for i in range(7):
            day = week_start + timedelta(days=i)
            prefix = day.strftime("%Y-%m-%d")
            md = f"{int(prefix[5:7])}月{int(prefix[8:10])}日"
            label = f"{md} {_WEEKDAY_SUN_SAT[i]}"
            clauses = ["occurred_at LIKE ?"]
            params: list[Any] = [f"{prefix}%"]
            if wid:
                clauses.append("work_id = ?")
                params.append(wid)
            if risk:
                clauses.append("title = ?")
                params.append(risk)
            where_sql = " AND ".join(clauses)
            alerts = int(
                conn.execute(
                    f"SELECT COUNT(*) AS c FROM inspection_event WHERE {where_sql}",
                    params,
                ).fetchone()["c"]
            )
            resolved = int(
                conn.execute(
                    f"SELECT COUNT(*) AS c FROM inspection_event WHERE {where_sql} AND status = 'resolved'",
                    params,
                ).fetchone()["c"]
            )
            active_works = int(
                conn.execute(
                    f"""
SELECT COUNT(DISTINCT work_id) AS c FROM inspection_event
WHERE {where_sql} AND work_id IS NOT NULL AND work_id != ''
""",
                    params,
                ).fetchone()["c"]
            )
            # 巡检执行次数：按当日活跃业务估算，与告警条数区分
            if wid:
                inspections = active_works * 8 + resolved * 2 + 4
            else:
                inspections = active_works * 8 + alerts * 2 + resolved * 2 + 6
            if alerts > 0 and inspections < alerts + resolved:
                inspections = alerts * 3 + resolved * 2 + 4
            out.append(
                {
                    "label": label,
                    "date": prefix,
                    "alerts": alerts,
                    "resolved": resolved,
                    "inspections": inspections,
                }
            )
        return out

    def _distinct_event_titles(
        self,
        conn: sqlite3.Connection,
        *,
        anchor_end: datetime,
        span_days: int = 30,
    ) -> list[str]:
        span = max(7, min(90, int(span_days)))
        start = (anchor_end - timedelta(days=span - 1)).strftime("%Y-%m-%d")
        end_ex = (anchor_end + timedelta(days=1)).strftime("%Y-%m-%d")
        rows = conn.execute(
            """
SELECT DISTINCT title AS t FROM inspection_event
WHERE occurred_at >= ? AND occurred_at < ? AND title IS NOT NULL AND title != ''
ORDER BY t ASC
""",
            (start, end_ex),
        ).fetchall()
        return [str(r["t"]) for r in rows if r["t"]]

    @staticmethod
    def _append_trend_filters(
        clauses: list[str],
        params: list[Any],
        *,
        status: str | None = None,
        kind: str | None = None,
        region_id: str | None = None,
    ) -> None:
        st = (status or "").strip()
        if st and st != "all":
            if st == "open":
                clauses.append("status IN ('pending', 'processing')")
            else:
                clauses.append("status = ?")
                params.append(st)
        kd = (kind or "").strip()
        if kd and kd != "all":
            clauses.append("kind = ?")
            params.append(kd)
        rid = (region_id or "").strip()
        if rid and rid != "all":
            clauses.append("region_id = ?")
            params.append(rid)

    def _available_event_dates(
        self,
        conn: sqlite3.Connection,
        *,
        anchor_end: datetime,
        span_days: int = 30,
    ) -> list[str]:
        start = (anchor_end - timedelta(days=max(1, span_days) - 1)).strftime("%Y-%m-%d")
        end_ex = (anchor_end + timedelta(days=1)).strftime("%Y-%m-%d")
        rows = conn.execute(
            """
SELECT DISTINCT substr(occurred_at, 1, 10) AS d FROM inspection_event
WHERE occurred_at >= ? AND occurred_at < ?
ORDER BY d DESC
""",
            (start, end_ex),
        ).fetchall()
        return [str(r["d"]) for r in rows if r["d"]]

    def _events_on_day(
        self,
        conn: sqlite3.Connection,
        *,
        day: str,
        status: str | None = None,
        kind: str | None = None,
        region_id: str | None = None,
    ) -> list[dict[str, Any]]:
        day = day.strip()[:10]
        try:
            next_day = (
                datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            ).strftime("%Y-%m-%d")
        except ValueError:
            return []
        clauses = ["occurred_at >= ?", "occurred_at < ?"]
        params: list[Any] = [f"{day} 00:00:00", f"{next_day} 00:00:00"]
        self._append_trend_filters(clauses, params, status=status, kind=kind, region_id=region_id)
        where_sql = " AND ".join(clauses)
        rows = conn.execute(
            f"""
SELECT event_id, title, occurred_at, reported_at, status, kind,
       region_name, work_name, source_name
FROM inspection_event
WHERE {where_sql}
ORDER BY occurred_at ASC
LIMIT 200
""",
            params,
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            occurred = str(row["occurred_at"] or "")
            out.append(
                {
                    "event_id": row["event_id"],
                    "title": row["title"],
                    "occurred_at": occurred,
                    "occurred_time": occurred[11:19] if len(occurred) >= 19 else occurred,
                    "reported_at": row["reported_at"],
                    "status": row["status"],
                    "kind": row["kind"],
                    "region_name": row["region_name"],
                    "work_name": row["work_name"],
                    "source_name": row["source_name"],
                }
            )
        return out

    def _trend_by_hour(
        self,
        conn: sqlite3.Connection,
        field: str,
        *,
        day: str,
        status: str | None = None,
        kind: str | None = None,
        region_id: str | None = None,
    ) -> tuple[dict[str, list[int]], list[str]]:
        if field not in ("title", "region_name", "work_name", "kind"):
            return {}, []
        day = day.strip()[:10]
        try:
            next_day = (
                datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            ).strftime("%Y-%m-%d")
        except ValueError:
            return {}, []
        hours = 24
        labels = [f"{h:02d}:00" for h in range(hours)]
        clauses = ["occurred_at >= ?", "occurred_at < ?"]
        params: list[Any] = [f"{day} 00:00:00", f"{next_day} 00:00:00"]
        self._append_trend_filters(clauses, params, status=status, kind=kind, region_id=region_id)
        where_sql = " AND ".join(clauses)
        rows = conn.execute(
            f"""
SELECT {field} AS group_key, occurred_at FROM inspection_event
WHERE {where_sql}
""",
            params,
        ).fetchall()
        counts: dict[str, list[int]] = {}
        for row in rows:
            key = str(row["group_key"] or "其他").strip() or "其他"
            hour = _parse_occurred_hour(str(row["occurred_at"]))
            if key not in counts:
                counts[key] = [0] * hours
            counts[key][hour] += 1
        return counts, labels

    def _trend_by_field(
        self,
        conn: sqlite3.Connection,
        field: str,
        *,
        days: int = 7,
        status: str | None = None,
        kind: str | None = None,
        region_id: str | None = None,
        anchor_end: datetime | None = None,
    ) -> tuple[dict[str, list[int]], list[str]]:
        if field not in ("title", "region_name", "work_name", "kind"):
            return {}, []
        end = anchor_end or datetime.now(timezone.utc)
        day_prefixes = [
            (end - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)
        ]
        range_start = (end - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        clauses = ["occurred_at >= ?", "occurred_at < ?"]
        range_end_exclusive = (end + timedelta(days=1)).strftime("%Y-%m-%d")
        params: list[Any] = [range_start, range_end_exclusive]
        self._append_trend_filters(clauses, params, status=status, kind=kind, region_id=region_id)
        where_sql = " AND ".join(clauses)
        rows = conn.execute(
            f"""
SELECT {field} AS group_key, occurred_at FROM inspection_event
WHERE {where_sql}
""",
            params,
        ).fetchall()
        counts: dict[str, list[int]] = {}
        for row in rows:
            key = str(row["group_key"] or "其他").strip() or "其他"
            day = _parse_occurred_day(str(row["occurred_at"]))
            if key not in counts:
                counts[key] = [0] * days
            try:
                idx = day_prefixes.index(day)
            except ValueError:
                continue
            counts[key][idx] += 1
        labels = [f"{d[5:7]}-{d[8:10]}" for d in day_prefixes]
        return counts, labels

    def list_work_runtime(self) -> list[dict[str, Any]]:
        self.ensure_ready()
        rw = InspectionWorkService()
        rw.ensure_ready()
        works, _ = rw.list_all(limit=500)
        region_names = self._region_name_map()
        conn = db.get_connection()
        try:
            out: list[dict[str, Any]] = []
            for work in works:
                wid = work["work_id"]
                pending = int(
                    conn.execute(
                        """
SELECT COUNT(*) AS c FROM inspection_event
WHERE work_id = ? AND status IN ('pending', 'processing')
""",
                        (wid,),
                    ).fetchone()["c"]
                )
                alerts_7d = int(
                    conn.execute(
                        """
SELECT COUNT(*) AS c FROM inspection_event
WHERE work_id = ? AND occurred_at >= ?
""",
                        (wid, (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")),
                    ).fetchone()["c"]
                )
                resolved_7d = int(
                    conn.execute(
                        """
SELECT COUNT(*) AS c FROM inspection_event
WHERE work_id = ? AND status = 'resolved' AND occurred_at >= ?
""",
                        (wid, (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")),
                    ).fetchone()["c"]
                )
                mode = work.get("schedule_mode") or "manual"
                if mode == "manual" and pending == 0 and alerts_7d == 0:
                    health = "idle"
                elif pending >= 3:
                    health = "critical"
                elif pending >= 1:
                    health = "warning"
                else:
                    health = "healthy"
                compliance = max(60, min(99, 96 - alerts_7d * 4))
                region_id = work.get("region_id") or ""
                region_name = region_names.get(region_id, region_id)
                last_row = conn.execute(
                    """
SELECT occurred_at FROM inspection_event WHERE work_id = ?
ORDER BY occurred_at DESC LIMIT 1
""",
                    (wid,),
                ).fetchone()
                last_run = str(last_row["occurred_at"]) if last_row else work.get("updated_at", "")
                next_run = (
                    str(work.get("schedule_interval") or "每10秒")
                    if mode == "continuous"
                    else "手动触发"
                    if mode == "manual"
                    else work.get("schedule_interval") or work.get("schedule_times") or "—"
                )
                rate = 100 if alerts_7d == 0 else round(resolved_7d / alerts_7d * 100)
                out.append(
                    {
                        "work_id": wid,
                        "name": work.get("name") or wid,
                        "region_id": region_id,
                        "region_name": region_name,
                        "schedule_mode": mode,
                        "health": health,
                        "last_run": last_run,
                        "next_run": next_run,
                        "compliance": compliance,
                        "alerts_7d": alerts_7d,
                        "alert_resolution_rate": min(100, rate),
                        "pending_events": pending,
                    }
                )
            return out
        finally:
            conn.close()

    def _region_name_map(self) -> dict[str, str]:
        svc = RegionMetaService()
        svc.ensure_ready()
        try:
            rows = svc.list_regions()
        except Exception:
            return {}
        return {str(r["id"]): str(r.get("name") or r["id"]) for r in rows}
