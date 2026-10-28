"""平台统一日志：文件轮转 + 控制台输出。"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from inspection_platform.app.config import get_settings, repo_root

_CONFIGURED = False

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

BUSINESS_LOGGER_PREFIXES = (
    "inspection_platform.inspection_work",
    "inspection_platform.inspection_event",
    "inspection_platform.algorithm.vaio_client",
    "inspection_platform.routes.inspection_work",
    "inspection_platform.routes.inspection_event",
)


class _BusinessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name or ""
        return any(name == p or name.startswith(p + ".") for p in BUSINESS_LOGGER_PREFIXES)


def logs_dir() -> Path:
    d = get_settings().data_path / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def platform_log_path() -> Path:
    return logs_dir() / "platform.log"


def business_log_path() -> Path:
    return logs_dir() / "business.log"


def dev_platform_log_path() -> Path:
    return repo_root() / ".run" / "platform.log"


def setup_platform_logging(level: str | None = None) -> None:
    """初始化 root 日志；重复调用无副作用。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    lvl_name = (level or __import__("os").environ.get("SIA_LOG_LEVEL", "INFO")).upper()
    root_level = getattr(logging, lvl_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(root_level)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # 避免 uvicorn reload 重复挂载 handler
    if not root.handlers:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.setLevel(root_level)
        root.addHandler(console)

    platform_path = str(platform_log_path())
    business_path = str(business_log_path())
    existing_paths = set()
    for h in root.handlers:
        if isinstance(h, logging.handlers.RotatingFileHandler):
            existing_paths.add(getattr(h, "baseFilename", ""))

    if platform_path not in existing_paths:
        platform_handler = logging.handlers.RotatingFileHandler(
            platform_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        platform_handler.setFormatter(formatter)
        platform_handler.setLevel(logging.DEBUG)
        root.addHandler(platform_handler)

    if business_path not in existing_paths:
        business_handler = logging.handlers.RotatingFileHandler(
            business_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        business_handler.setFormatter(formatter)
        business_handler.setLevel(logging.DEBUG)
        business_handler.addFilter(_BusinessLogFilter())
        root.addHandler(business_handler)

    logging.getLogger(__name__).info(
        "平台日志已初始化 platform=%s business=%s level=%s",
        platform_log_path(),
        business_log_path(),
        lvl_name,
    )
