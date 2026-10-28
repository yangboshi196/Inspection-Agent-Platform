"""SQLAlchemy 引擎、会话与 sqlite 兼容连接（便于域服务渐进迁移）。"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker

from inspection_platform.app.config import get_settings
from inspection_platform.app.models.base import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_db_initialized = False
_init_lock = threading.Lock()


def _engine_connect_args(url: str) -> dict[str, Any]:
    """缩短 MySQL 连接/读超时，避免鉴权占满线程池导致 /api/* 集体挂起。"""
    lower = url.lower()
    if "pymysql" in lower or lower.startswith("mysql"):
        return {
            "connect_timeout": int(os.environ.get("SIA_DB_CONNECT_TIMEOUT", "5")),
            "read_timeout": int(os.environ.get("SIA_DB_READ_TIMEOUT", "15")),
            "write_timeout": int(os.environ.get("SIA_DB_WRITE_TIMEOUT", "15")),
        }
    return {}


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        url = settings.sqlalchemy_url
        connect_args = _engine_connect_args(url)
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=int(os.environ.get("SIA_DB_POOL_SIZE", "10")),
            max_overflow=int(os.environ.get("SIA_DB_POOL_OVERFLOW", "20")),
            connect_args=connect_args,
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：请求级 ORM Session。"""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """应用 lifespan 启动时调用一次；勿在请求/鉴权路径重复执行。"""
    global _db_initialized
    if _db_initialized:
        return
    with _init_lock:
        if _db_initialized:
            return
        import inspection_platform.app.models  # noqa: F401 — 注册全部 ORM 表

        engine = get_engine()
        Base.metadata.create_all(bind=engine)
        _migrate_mysql_columns(engine)
        _migrate_auth_user_role_id(engine)
        _slim_work_report_template_binding(engine)
        _drop_report_template_outline(engine)
        _db_initialized = True


def _drop_report_template_outline(engine: Engine) -> None:
    """将 outline 残留合并到 content 后删除 outline 列。"""
    if engine.dialect.name != "mysql":
        return
    from sqlalchemy import inspect

    insp = inspect(engine)
    if "report_template" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("report_template")}
    if "outline" not in cols:
        return
    with engine.begin() as conn:
        if "content" in cols:
            conn.execute(
                text(
                    """
UPDATE report_template
SET content = outline
WHERE (content IS NULL OR TRIM(content) = '')
  AND outline IS NOT NULL AND TRIM(outline) != ''
"""
                )
            )
        conn.execute(text("ALTER TABLE `report_template` DROP COLUMN `outline`"))


def warmup_db_pool() -> None:
    """启动时探测 MySQL，避免首请求在鉴权里长时间阻塞。"""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("数据库连接预热失败: %s", exc)


def _migrate_mysql_columns(engine: Engine) -> None:
    """对已存在的 MySQL 表执行 ADD COLUMN（create_all 不会追加新列）。"""
    if engine.dialect.name != "mysql":
        return
    from sqlalchemy import inspect

    alters: dict[str, list[tuple[str, str]]] = {
        "inspection_work": [
            ("equipment_algo_params_json", "VARCHAR(8192) NOT NULL DEFAULT '{}'"),
            ("schedule_mode", "VARCHAR(32) NOT NULL DEFAULT 'manual'"),
            ("schedule_interval", "VARCHAR(64) NULL"),
            ("schedule_times", "VARCHAR(256) NULL"),
            ("source", "VARCHAR(32) NOT NULL DEFAULT 'manual'"),
        ],
        "spec_rule": [
            ("recommended_regions_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("region_reasoning", "TEXT NOT NULL DEFAULT ''"),
        ],
        "equipment": [
            ("simulate_video_relpath", "VARCHAR(512) NOT NULL DEFAULT ''"),
        ],
        "inspection_event": [
            ("detection_json", "TEXT NOT NULL DEFAULT ''"),
        ],
        "work_report_template_binding": [
            ("enabled", "INTEGER NOT NULL DEFAULT 0"),
        ],
        "report_template": [
            ("description", "VARCHAR(2000) NOT NULL DEFAULT ''"),
            ("content", "TEXT NULL"),
            ("storage_relpath", "VARCHAR(512) NOT NULL DEFAULT ''"),
        ],
        "auth_user": [
            ("role_id", "VARCHAR(64) NULL"),
        ],
    }
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, columns in alters.items():
            if table not in insp.get_table_names():
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for col_name, col_def in columns:
                if col_name in existing:
                    continue
                conn.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{col_name}` {col_def}"))


def _migrate_auth_user_role_id(engine: Engine) -> None:
    """为 auth_user 追加 role_id（SQLite / 非 MySQL 路径）。"""
    from sqlalchemy import inspect

    dialect = engine.dialect.name
    if dialect == "mysql":
        return
    insp = inspect(engine)
    if "auth_user" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("auth_user")}
    if "role_id" in existing:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE auth_user ADD COLUMN role_id VARCHAR(64)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_auth_user_role ON auth_user (role_id)"))


def _slim_work_report_template_binding(engine: Engine) -> None:
    """绑定表仅保留 work_id / enabled / template_id / 时间戳，删除历史内嵌模版列。"""
    from sqlalchemy import inspect

    from inspection_platform.report.migrate_unified_template import migrate_legacy_binding_templates

    insp = inspect(engine)
    if "work_report_template_binding" not in insp.get_table_names():
        return
    legacy_cols = ("template_name", "filename", "storage_relpath", "content")
    existing = {c["name"] for c in insp.get_columns("work_report_template_binding")}
    to_drop = [c for c in legacy_cols if c in existing]
    if not to_drop:
        return
    migrate_legacy_binding_templates()
    dialect = engine.dialect.name
    with engine.begin() as conn:
        for col in to_drop:
            if dialect == "mysql":
                conn.execute(text(f"ALTER TABLE `work_report_template_binding` DROP COLUMN `{col}`"))
            elif dialect == "sqlite":
                conn.execute(text(f"ALTER TABLE work_report_template_binding DROP COLUMN {col}"))


def _positional_sql(sql: str, params: tuple[Any, ...] | dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    if isinstance(params, dict):
        return text(sql), params
    if not params:
        return text(sql), {}
    parts = sql.split("?")
    if len(parts) != len(params) + 1:
        return text(sql), {}
    named: dict[str, Any] = {}
    out = parts[0]
    for i, (part, val) in enumerate(zip(parts[1:], params)):
        key = f"p{i}"
        named[key] = val
        out += f":{key}" + part
    return text(out), named


class CompatResult:
    """将 SQLAlchemy Result 包装为 fetchone/fetchall 返回 mapping 风格行。"""

    def __init__(self, result: Any) -> None:
        self._result = result

    @property
    def rowcount(self) -> int:
        return int(getattr(self._result, "rowcount", -1) or -1)

    def _wrap_row(self, row: Any) -> Any:
        if row is None:
            return None
        mapping = getattr(row, "_mapping", None)
        if mapping is not None:
            return mapping
        if hasattr(row, "keys") and callable(row.keys):
            return row
        return row

    def fetchone(self) -> Any:
        return self._wrap_row(self._result.fetchone())

    def fetchall(self) -> list[Any]:
        return [self._wrap_row(r) for r in self._result.fetchall()]


class CompatConnection:
    """兼容旧 sqlite3 风格 `conn.execute(sql, params)` 的 SQLAlchemy 包装。"""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> CompatResult:
        stmt, bound = _positional_sql(sql, params)
        return CompatResult(self._conn.execute(stmt, bound))

    def executescript(self, sql: str) -> None:
        for stmt in re.split(r";\s*\n", sql.strip()):
            s = stmt.strip()
            if s:
                self._conn.execute(text(s))

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> CompatConnection:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def get_connection() -> CompatConnection:
    """域服务层兼容入口：返回可 positional 绑定的连接（调用方须 commit/close）。"""
    return CompatConnection(get_engine().connect())


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def row_to_dict(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)
