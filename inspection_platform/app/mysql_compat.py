"""MySQL 与 SQLAlchemy Row 兼容辅助。"""

from __future__ import annotations

from typing import Any


def row_keys(row: Any) -> set[str]:
    """兼容 sqlite3.Row 与 SQLAlchemy Row 的列名集合。"""
    if row is None:
        return set()
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return set(mapping.keys())
    keys = getattr(row, "keys", None)
    if callable(keys):
        return set(keys())
    return set()


def row_get(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def is_integrity_error(exc: BaseException) -> bool:
    """兼容 sqlite3 / SQLAlchemy / PyMySQL 唯一键冲突。"""
    import sqlite3

    try:
        from sqlalchemy.exc import IntegrityError
    except ImportError:
        IntegrityError = ()  # type: ignore[misc, assignment]

    if isinstance(exc, (sqlite3.IntegrityError, IntegrityError)):
        return True
    orig = getattr(exc, "orig", None)
    if orig is not None and orig is not exc:
        return is_integrity_error(orig)
    try:
        import pymysql.err

        if isinstance(orig, pymysql.err.IntegrityError):
            return True
    except ImportError:
        pass
    return False
