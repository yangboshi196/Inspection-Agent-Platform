"""知识库：从文档库选择并向量化入库，以及检索。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response
from pydantic import BaseModel, Field

from inspection_platform.deps import get_knowledge_ingest_service

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

KbIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=64,
        description="知识库分区 ID。与入库 ingest 时的 kb_id 一致；不同分区对应 Milvus 不同 collection。",
    ),
]
KnowledgeDocIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=128,
        description=(
            "Milvus 逻辑文档 id；从文档库向量化时与 document 表主键一致。"
            "未绑文档库的历史数据可能为 kb_id+文件名 哈希。"
        ),
    ),
]


class KnowledgeIngestBody(BaseModel):
    document_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="文档库 SQLite 主键（须先 POST /api/document 上传）；向量化读取磁盘原文。",
    )
    kb_id: str = Field(
        default="default",
        max_length=64,
        description="知识库分区 ID；同一 kb 下不同 document 数据隔离。",
    )
    replace: bool = Field(
        default=True,
        description="为 true 时，写入前先删除该 document 在 Milvus 中的已有分块。",
    )
    max_chars: int = Field(default=900, ge=200, le=4000, description="分块最大字符数。")
    overlap: int = Field(default=120, ge=0, le=500, description="相邻块重叠字符数。")


class KnowledgeQueryBody(BaseModel):
    kb_id: str = Field(
        default="default",
        max_length=64,
        description="要检索的知识库分区 ID，须与入库时一致。",
    )
    query: str = Field(
        ...,
        min_length=1,
        max_length=8000,
        description="自然语言问句；将向量化后在同库分块中做相似度检索。",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="返回相似分块条数上限（按相似度截断）。",
    )
    doc_id: str | None = Field(
        default=None,
        description="可选。仅在 metadata.doc_id 等于该值的分块内检索（通常即 document.id）。",
    )
    source_doc_id: str | None = Field(
        default=None,
        max_length=256,
        description="可选。仅在 metadata.source_doc_id 等于该值的分块内检索（与 document.id 一致）。",
    )


@router.post(
    "/cleanup-orphans",
    summary="清理无文档关联的孤儿向量分片",
    description="扫描所有知识库 collection，删除 metadata.doc_id 不在文档库 SQLite 的分片。",
)
def cleanup_orphan_knowledge_chunks() -> dict:
    return get_knowledge_ingest_service().cleanup_orphan_chunks()


@router.post(
    "/ingest",
    summary="从文档库选择并向量化",
    description=(
        "不接收文件上传。须先在 /api/document 将文件写入 SQLite 与磁盘，"
        "再传入 document_id 完成分块与嵌入写入 Milvus。"
        "入库采用分阶段事件流水线：先完整 embedding，再备份/替换旧分片；失败时尽力回滚。"
    ),
)
def ingest_from_document_library(body: KnowledgeIngestBody) -> dict:
    try:
        return get_knowledge_ingest_service().ingest_from_document(
            document_id=body.document_id,
            kb_id=body.kb_id.strip() or "default",
            replace_existing=body.replace,
            max_chars=body.max_chars,
            overlap=body.overlap,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        msg = str(e)
        if "Milvus" in msg or "19530" in msg:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"向量库不可用：{msg}。请检查 Milvus 服务（MILVUS_HOST / MILVUS_PORT）后重启平台。"
                ),
            ) from e
        raise HTTPException(status_code=500, detail=f"向量化入库失败：{msg}") from e


@router.post(
    "/query",
    summary="知识库向量检索",
    description="对指定 kb 做查询向量化后，在 Milvus 中检索最相近文本分块。",
)
def query_knowledge(body: KnowledgeQueryBody) -> list[dict]:
    flt: dict[str, str] | None = None
    if body.doc_id or body.source_doc_id:
        flt = {}
        if body.doc_id:
            flt["doc_id"] = body.doc_id.strip()
        if body.source_doc_id:
            flt["source_doc_id"] = body.source_doc_id.strip()
    try:
        return get_knowledge_ingest_service().query(
            kb_id=body.kb_id.strip() or "default",
            query=body.query,
            top_k=body.top_k,
            filters=flt,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get(
    "/{kb_id}/documents",
    summary="列出知识库已向量化的文档",
    description="按 Milvus metadata 聚合；含 source_doc_id 时可与文档库 id 对照。",
)
def list_knowledge_documents(kb_id: KbIdPath) -> list[dict]:
    return get_knowledge_ingest_service().list_documents(kb_id=kb_id.strip() or "default")


@router.get(
    "/{kb_id}/stats",
    summary="知识库统计",
    description="返回该分区当前向量分块总数等信息。",
)
def knowledge_stats(kb_id: KbIdPath) -> dict:
    return get_knowledge_ingest_service().stats(kb_id=kb_id.strip() or "default")


@router.delete(
    "/{kb_id}/documents/{doc_id}",
    status_code=204,
    response_class=Response,
    summary="删除知识库某逻辑文档向量",
    description=(
        "按 doc_id 删除 Milvus 中该文档全部分块；不删除文档库 SQLite 记录，"
        "不影响已发布规范条目（规范引用 doc_id 仍有效，可重新向量化后再次抽取）。"
    ),
)
def delete_knowledge_document(kb_id: KbIdPath, doc_id: KnowledgeDocIdPath) -> Response:
    n = get_knowledge_ingest_service().delete_document(kb_id=kb_id.strip() or "default", doc_id=doc_id)
    if n <= 0:
        raise HTTPException(status_code=404, detail="document not found or already deleted")
    return Response(status_code=204)
