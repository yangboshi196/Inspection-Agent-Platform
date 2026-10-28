"""文档与 region：各自独立 SQLite；无交叉初始化与无内嵌表迁移。"""

from .db import init_db
from .region_db import init_region_db, region_db_path
from .region_meta import RegionMetaRecord, RegionMetaService
from .service import DocumentRecord, DocumentService

__all__ = [
    "DocumentService",
    "DocumentRecord",
    "RegionMetaService",
    "RegionMetaRecord",
    "init_db",
    "init_region_db",
    "region_db_path",
]
