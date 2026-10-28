"""报告模块启动期一次性初始化（迁移 / 去重），请求路径勿重复执行。"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_ready = False


def bootstrap_report_module(*, force: bool = False) -> None:
    """在应用 lifespan 中调用；线程安全、幂等。"""
    global _ready
    if _ready and not force:
        return
    with _lock:
        if _ready and not force:
            return
        from .dedupe_templates import dedupe_report_templates
        from .migrate_unified_template import migrate_legacy_binding_templates

        try:
            migrate_legacy_binding_templates()
            dedupe_report_templates()
            _ready = True
            logger.info("report module bootstrap complete")
        except Exception:
            logger.exception("report module bootstrap failed")
            raise


def ensure_report_ready() -> None:
    """请求路径轻量入口：若启动未完成则补跑一次（带锁）。"""
    bootstrap_report_module()
