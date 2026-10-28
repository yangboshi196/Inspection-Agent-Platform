"""日志管理 HTTP API。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Query

from inspection_platform.logs.service import LogManagementService

router = APIRouter(prefix="/api/logs", tags=["logs"])


@lru_cache
def get_log_service() -> LogManagementService:
    return LogManagementService()


@router.get("/sources", summary="日志源列表")
def list_log_sources() -> dict[str, Any]:
    items = get_log_service().list_sources()
    return {"items": items}


@router.get("/categories", summary="日志分类")
def list_log_categories() -> dict[str, Any]:
    items = get_log_service().list_categories()
    return {"items": items}


@router.get("/entries", summary="查询日志条目")
def query_log_entries(
    source: str = Query(default="platform", description="platform | business | hermes-*"),
    level: str | None = Query(default=None, description="DEBUG | INFO | WARNING | ERROR | ALL"),
    category: str | None = Query(default=None, description="platform | business | algorithm | auth"),
    logger_prefix: str | None = Query(default=None, description="logger 前缀过滤"),
    q: str | None = Query(default=None, description="关键词"),
    limit: int = Query(default=200, ge=1, le=500),
    group: bool = Query(default=False, description="聚合相似错误"),
) -> dict[str, Any]:
    return get_log_service().query_entries(
        source=source,
        level=level,
        category=category,
        logger_prefix=logger_prefix,
        q=q,
        limit=limit,
        group=group,
    )


@router.get("/stats", summary="日志看板统计")
def log_dashboard_stats(
    hours: int = Query(default=24, ge=1, le=168, description="统计时间窗口（小时）"),
) -> dict[str, Any]:
    return get_log_service().dashboard_stats(hours=hours)
