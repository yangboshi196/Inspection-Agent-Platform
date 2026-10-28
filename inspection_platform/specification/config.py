"""规范模块：SQLite（规则元数据）路径。

规范**原文**走文档库与 ``POST /api/knowledge/ingest``；规则向量存 Milvus collection ``spec_rules``。

环境变量（新名优先，括号内为兼容旧名）::

    SIA_SPEC_SQLITE_PATH  (SPECIFICATION_DB_PATH)
    SIA_SPEC_FILES_ROOT   (SPEC_FILES_ROOT)  # 历史变量，当前实现未使用
"""

from __future__ import annotations

from pathlib import Path

from inspection_platform.envutil import env_first


def spec_db_path() -> Path:
    env = env_first("SIA_SPEC_SQLITE_PATH", "SPECIFICATION_DB_PATH")
    if env:
        return Path(env).expanduser().resolve()
    root = Path(__file__).resolve().parents[2]
    return (root / "data" / "specification.db").resolve()


def spec_files_root() -> Path:
    env = env_first("SIA_SPEC_FILES_ROOT", "SPEC_FILES_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    root = Path(__file__).resolve().parents[2]
    return (root / "data" / "spec_files").resolve()
