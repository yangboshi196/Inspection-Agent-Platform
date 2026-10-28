"""知识库：多格式文档抽取、分块、经 ``ModelManager`` 向量化并写入 Chroma。"""

from .ingest_service import KnowledgeIngestService

__all__ = ["KnowledgeIngestService"]
