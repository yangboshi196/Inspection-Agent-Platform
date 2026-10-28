"""知识库向量化入库：分阶段事件 + 失败补偿（Milvus 无事务时的最佳努力回滚）。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from agent_base.model_manager.manager import ModelManager
from agent_base.rag.embedded_chunk import EmbeddedChunk

from .chunk import chunk_text
from .extract import extract_plain_text
from .preprocess import govern_text


class VectorStoreLike(Protocol):
    def count_by_filters(self, filters: dict[str, Any]) -> int: ...
    def export_embedded_chunks_by_filters(self, filters: dict[str, Any]) -> list[EmbeddedChunk]: ...
    def delete_by_filters(self, filters: dict[str, Any]) -> int: ...
    def add_embedded_chunks(self, chunks: list[EmbeddedChunk], *, batch_size: int = 128) -> None: ...


@dataclass
class IngestEvent:
    phase: str
    ok: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"phase": self.phase, "ok": self.ok, "detail": self.detail}


@dataclass
class IngestPipelineState:
    kb_id: str
    doc_id: str
    filename: str
    fmt: str = ""
    plain: str = ""
    chunks: list[str] = field(default_factory=list)
    embedded: list[EmbeddedChunk] = field(default_factory=list)
    backup: list[EmbeddedChunk] = field(default_factory=list)
    events: list[IngestEvent] = field(default_factory=list)
    old_deleted: bool = False
    add_started: bool = False

    def log(self, phase: str, ok: bool, detail: str = "") -> None:
        self.events.append(IngestEvent(phase=phase, ok=ok, detail=detail))


def _embed_all_chunks(
    mm: ModelManager,
    *,
    chunks: list[str],
    embedding_model_name: str | None,
    kb_id: str,
    build_meta: Callable[[int, str], dict[str, Any]],
) -> list[EmbeddedChunk]:
    embedded: list[EmbeddedChunk] = []
    batch_sz = 32
    for off in range(0, len(chunks), batch_sz):
        part = chunks[off : off + batch_sz]
        try:
            from inspection_platform.deps import platform_embed_texts

            vectors = platform_embed_texts(
                part,
                model_name=embedding_model_name,
                metadata={"stage": "knowledge_ingest", "kb_id": kb_id},
            )
        except Exception as e:
            raise ValueError(
                "向量化失败：请确认硅基流动 API Key 或本地模型可用"
                f" 详情：{e}"
            ) from e
        for j, (text, vec) in enumerate(zip(part, vectors, strict=True)):
            i = off + j
            meta = build_meta(i, text)
            cid = str(meta.get("chunk_id") or f"chunk:{i}")
            embedded.append(
                EmbeddedChunk(
                    chunk_id=cid,
                    text=text,
                    vector=[float(x) for x in vec],
                    meta=meta,
                )
            )
    return embedded


async def _embed_all_chunks_async(
    mm: ModelManager,
    *,
    chunks: list[str],
    embedding_model_name: str | None,
    kb_id: str,
    build_meta: Callable[[int, str], dict[str, Any]],
) -> list[EmbeddedChunk]:
    """全量分片一次异步向量化（硅基流动多 batch 并发）。"""
    del mm
    if not chunks:
        return []
    try:
        from inspection_platform.deps import platform_embed_texts_async

        vectors = await platform_embed_texts_async(
            chunks,
            model_name=embedding_model_name,
            metadata={"stage": "knowledge_ingest", "kb_id": kb_id},
        )
    except Exception as e:
        raise ValueError(f"向量化失败：{e}") from e
    embedded: list[EmbeddedChunk] = []
    for i, (text, vec) in enumerate(zip(chunks, vectors, strict=True)):
        meta = build_meta(i, text)
        cid = str(meta.get("chunk_id") or f"chunk:{i}")
        embedded.append(
            EmbeddedChunk(
                chunk_id=cid,
                text=text,
                vector=[float(x) for x in vec],
                meta=meta,
            )
        )
    return embedded


def run_ingest_pipeline(
    *,
    store: VectorStoreLike,
    mm: ModelManager,
    embedding_model_name: str | None,
    filename: str,
    content: bytes,
    kb_id: str,
    doc_id: str,
    library_sid: str | None,
    replace_existing: bool,
    max_chars: int,
    overlap: int,
) -> tuple[IngestPipelineState, dict[str, Any]]:
    """
    分阶段入库：

    1. extract — 纯本地
    2. embed — 纯内存，不写向量库
    3. backup — 替换前导出旧分片
    4. delete_old — 删除旧分片
    5. commit — 写入新分片

    任一步失败且已改动向量库时，尽力 restore backup。
    """
    state = IngestPipelineState(kb_id=kb_id, doc_id=doc_id, filename=filename)
    display_name = os.path.basename(filename) or filename

    try:
        state.fmt, state.plain = extract_plain_text(filename=filename, content=content)
        state.plain = govern_text(state.plain)
        state.chunks = chunk_text(state.plain, max_chars=max_chars, overlap=overlap)
        if not state.chunks:
            raise ValueError("no text extracted or all empty after chunking")
        state.log("extract", True, f"chunks={len(state.chunks)} format={state.fmt} governed=1")

        def build_meta(i: int, _text: str) -> dict[str, Any]:
            meta: dict[str, Any] = {
                "chunk_id": f"{doc_id}:{i}",
                "doc_id": doc_id,
                "kb_id": kb_id,
                "source": display_name,
                "chunk_index": i,
                "format": state.fmt,
            }
            if library_sid is not None:
                meta["source_doc_id"] = library_sid
            return meta

        from inspection_platform.embedding.backend import resolve_embedding_backend
        from inspection_platform.llm.async_runtime import run_async

        if resolve_embedding_backend() == "openai":
            state.embedded = run_async(
                _embed_all_chunks_async(
                    mm,
                    chunks=state.chunks,
                    embedding_model_name=embedding_model_name,
                    kb_id=kb_id,
                    build_meta=build_meta,
                )
            )
        else:
            state.embedded = _embed_all_chunks(
                mm,
                chunks=state.chunks,
                embedding_model_name=embedding_model_name,
                kb_id=kb_id,
                build_meta=build_meta,
            )
        state.log("embed", True, f"vectors={len(state.embedded)}")

        if replace_existing:
            previous_count = store.count_by_filters({"doc_id": doc_id})
            state.backup = store.export_embedded_chunks_by_filters({"doc_id": doc_id})
            if previous_count > 0 and len(state.backup) != previous_count:
                raise ValueError(
                    f"备份旧分片不完整：期望 {previous_count} 条，实际 {len(state.backup)} 条，已中止替换"
                )
            state.log("backup", True, f"previous_chunks={len(state.backup)}")

            deleted = store.delete_by_filters({"doc_id": doc_id})
            state.old_deleted = deleted > 0 or len(state.backup) > 0
            state.log("delete_old", True, f"removed={deleted}")

        try:
            state.add_started = True
            store.add_embedded_chunks(state.embedded)
        except Exception as add_err:
            raise ValueError(f"写入 Milvus 失败：{add_err}") from add_err
        state.log("commit", True, f"written={len(state.embedded)}")

        out: dict[str, Any] = {
            "kb_id": kb_id,
            "doc_id": doc_id,
            "source_name": display_name,
            "format": state.fmt,
            "chunks": len(state.embedded),
            "chars_total": len(state.plain),
            "ingest_events": [e.as_dict() for e in state.events],
        }
        if library_sid is not None:
            out["source_doc_id"] = library_sid
        return state, out

    except Exception as e:
        state.log("failed", False, str(e))
        if state.old_deleted or state.add_started:
            try:
                store.delete_by_filters({"doc_id": doc_id})
            except Exception as re:
                state.log("cleanup_partial", False, str(re))

        if state.backup:
            try:
                store.add_embedded_chunks(state.backup)
                state.log("rollback", True, f"restored={len(state.backup)}")
            except Exception as re:
                state.log("rollback", False, str(re))
                raise ValueError(
                    f"向量化入库失败且无法恢复旧索引：{e}；回滚错误：{re}"
                ) from re
        elif state.old_deleted:
            state.log("rollback", False, "old_index_removed_and_no_backup")

        if isinstance(e, ValueError):
            raise
        raise ValueError(f"向量化入库失败：{e}") from e
