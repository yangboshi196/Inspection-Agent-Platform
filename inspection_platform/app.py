"""
平台应用入口（兼容旧 import 路径）。

新入口：``inspection_platform.app.main:app``
"""

from inspection_platform.app.main import app

__all__ = ["app"]
