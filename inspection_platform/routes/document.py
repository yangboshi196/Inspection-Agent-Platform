"""文档 HTTP API（元数据 SQLite + 原文磁盘）。"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from inspection_platform.document.errors import DocumentInUseError
from inspection_platform.document.service import DocumentService

router = APIRouter(prefix="/api/document", tags=["document"])

DocumentIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=64,
        description="文档主键：SQLite document 表 id（与入库响应 id 一致，一般为 32 位 hex）。",
    ),
]


@lru_cache
def get_document_service() -> DocumentService:
    svc = DocumentService()
    svc.ensure_ready()  # 仅创建文件目录，不 init_db
    return svc


def _document_list_limit(limit: str | None = Query(default=None, description="本页条数，空串等同默认 100。")) -> int:
    if limit is None or not str(limit).strip():
        return 100
    try:
        return max(1, min(500, int(str(limit).strip(), 10)))
    except ValueError:
        return 100


def _document_list_offset(offset: str | None = Query(default=None, description="分页偏移，空串等同 0。")) -> int:
    if offset is None or not str(offset).strip():
        return 0
    try:
        return max(0, int(str(offset).strip(), 10))
    except ValueError:
        return 0


def _document_list_full(full: str | None = Query(default=None, description="是否返回完整行；空串等同 false。")) -> bool:
    if full is None or not str(full).strip():
        return False
    return str(full).strip().lower() in ("1", "true", "yes", "on")


class DocumentPatchBody(BaseModel):
    doc_type: str | None = Field(default=None, max_length=256)
    name: str | None = Field(default=None, max_length=512)


@router.post("/", summary="上传文档原文")
async def upload_document(
    file: UploadFile = File(..., description="上传文件二进制内容。"),
    doc_type: str = Form(..., description="文档类别/来源标签，必填。"),
    name: str | None = Form(default=None, description="展示用文件名；不传则使用上传文件的原始文件名。"),
) -> dict:
    svc = get_document_service()
    raw = await file.read()
    try:
        return svc.store(
            file_content=raw,
            original_filename=file.filename or "unnamed",
            doc_type=doc_type.strip(),
            name=name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/", summary="快速浏览文档库")
def list_document(
    limit: Annotated[int, Depends(_document_list_limit)],
    offset: Annotated[int, Depends(_document_list_offset)],
    full: Annotated[bool, Depends(_document_list_full)],
    doc_type: str | None = Query(default=None, description="按 doc_type 精确筛选。"),
) -> list[dict]:
    svc = get_document_service()
    dt = (doc_type or "").strip() or None
    return svc.list_document(doc_type=dt, limit=limit, offset=offset, brief=not full)


@router.get("/{doc_id}/download", summary="下载文档原文")
def download_document(doc_id: DocumentIdPath) -> FileResponse:
    svc = get_document_service()
    try:
        path = svc.resolve_path(doc_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="document not found") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file missing on disk")
    mt = svc.guess_media_type(doc_id)
    rec = svc.get_by_id(doc_id)
    return FileResponse(path, media_type=mt, filename=rec.name)


@router.get("/{doc_id}", summary="获取文档元数据")
def get_document(doc_id: DocumentIdPath) -> dict:
    svc = get_document_service()
    try:
        return svc._record_to_api(svc.get_by_id(doc_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="document not found") from None


@router.patch("/{doc_id}", summary="更新文档元数据")
def patch_document(doc_id: DocumentIdPath, body: DocumentPatchBody) -> dict:
    if body.doc_type is None and body.name is None:
        raise HTTPException(
            status_code=400,
            detail="at least one of doc_type, name is required",
        )
    svc = get_document_service()
    try:
        return svc.update_metadata(doc_id, doc_type=body.doc_type, name=body.name)
    except KeyError:
        raise HTTPException(status_code=404, detail="document not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/{doc_id}", status_code=204, response_class=Response, summary="删除文档")
def delete_document(doc_id: DocumentIdPath) -> Response:
    svc = get_document_service()
    try:
        svc.delete(doc_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="document not found") from None
    except DocumentInUseError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(e),
                "doc_id": e.doc_id,
                "rule_count": e.rule_count,
            },
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return Response(status_code=204)
