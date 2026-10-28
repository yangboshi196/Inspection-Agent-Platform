"""报告模版 / 计划 / 巡检报告表结构。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .config import report_db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS report_template (
    template_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    filename TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    storage_relpath TEXT NOT NULL DEFAULT '',
    uploaded_at TEXT NOT NULL DEFAULT '',
    size_label TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_plan (
    plan_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    frequency TEXT NOT NULL DEFAULT 'daily',
    work_ids_json TEXT NOT NULL DEFAULT '[]',
    content_prompt TEXT NOT NULL DEFAULT '',
    template_id TEXT,
    weekday INTEGER,
    month_day INTEGER,
    generate_time TEXT NOT NULL DEFAULT '08:00',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inspection_report (
    report_id TEXT PRIMARY KEY,
    plan_id TEXT,
    plan_name TEXT,
    title TEXT NOT NULL,
    period TEXT NOT NULL DEFAULT '',
    frequency TEXT NOT NULL DEFAULT 'weekly',
    work_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft',
    source TEXT NOT NULL DEFAULT 'manual',
    content_prompt TEXT NOT NULL DEFAULT '',
    template_id TEXT,
    template_name TEXT,
    summary TEXT NOT NULL DEFAULT '',
    sections_json TEXT NOT NULL DEFAULT '[]',
    full_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_report_plan_frequency ON report_plan(frequency);
CREATE INDEX IF NOT EXISTS idx_inspection_report_status ON inspection_report(status);
CREATE INDEX IF NOT EXISTS idx_inspection_report_updated ON inspection_report(updated_at DESC);

CREATE TABLE IF NOT EXISTS work_report_template_binding (
    work_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    template_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def get_connection():
    from inspection_platform.app.database import get_connection as _gc

    return _gc()


def init_db() -> None:
    from inspection_platform.app.database import init_db as _init_tables

    _init_tables()


def db_path() -> Path:
    return report_db_path()


def _loads_list(raw: str) -> list[Any]:
    try:
        val = json.loads(raw or "[]")
        return val if isinstance(val, list) else []
    except json.JSONDecodeError:
        return []


def template_row_to_api(r: sqlite3.Row) -> dict[str, Any]:
    from .template_schema import template_row_to_api as _row_to_api

    return _row_to_api(r)


def plan_row_to_api(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "plan_id": str(r["plan_id"]),
        "name": str(r["name"]),
        "enabled": bool(int(r["enabled"])),
        "frequency": str(r["frequency"]),
        "work_ids": [str(x) for x in _loads_list(str(r["work_ids_json"]))],
        "content_prompt": str(r["content_prompt"] or ""),
        "template_id": str(r["template_id"]) if r["template_id"] else None,
        "weekday": int(r["weekday"]) if r["weekday"] is not None else None,
        "month_day": int(r["month_day"]) if r["month_day"] is not None else None,
        "generate_time": str(r["generate_time"] or "08:00"),
        "created_at": str(r["created_at"]),
        "updated_at": str(r["updated_at"]),
    }


def report_row_to_api(r: sqlite3.Row) -> dict[str, Any]:
    sections = _loads_list(str(r["sections_json"]))
    if not isinstance(sections, list):
        sections = []
    return {
        "report_id": str(r["report_id"]),
        "plan_id": str(r["plan_id"]) if r["plan_id"] else None,
        "plan_name": str(r["plan_name"]) if r["plan_name"] else None,
        "title": str(r["title"]),
        "period": str(r["period"] or ""),
        "frequency": str(r["frequency"]),
        "work_ids": [str(x) for x in _loads_list(str(r["work_ids_json"]))],
        "status": str(r["status"]),
        "source": str(r["source"]),
        "content_prompt": str(r["content_prompt"] or ""),
        "template_id": str(r["template_id"]) if r["template_id"] else None,
        "template_name": str(r["template_name"]) if r["template_name"] else None,
        "summary": str(r["summary"] or ""),
        "sections": sections,
        "full_text": str(r["full_text"] or ""),
        "created_at": str(r["created_at"]),
        "updated_at": str(r["updated_at"]),
    }


def work_template_binding_row_to_api(r: sqlite3.Row, template: dict[str, Any] | None = None) -> dict[str, Any]:
    enabled_raw = r["enabled"] if "enabled" in r.keys() else 0
    tid = str(r["template_id"] or "")
    tpl = template or {}
    storage = str(tpl.get("storage_relpath") or "")
    return {
        "work_id": str(r["work_id"]),
        "enabled": bool(int(enabled_raw or 0)),
        "template_id": tid,
        "template": tpl if tpl else None,
        "template_name": str(tpl.get("name") or ""),
        "filename": str(tpl.get("filename") or ""),
        "storage_relpath": storage,
        "storage_dir": storage.rsplit("/", 1)[0] if storage else "",
        "content": str(tpl.get("content") or ""),
        "created_at": str(r["created_at"]),
        "updated_at": str(r["updated_at"]),
    }
