"""规则识别：按文档分片逐条抽取（每片一条），不经语义检索。"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Iterator
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Callable

from pydantic import BaseModel, Field

from agent_base.llm.errors import LLMError
from agent_base.model_manager.manager import ModelManager

from .agent_roles import RULE_ENTITY_RECOGNIZER, build_chat_request, build_rule_entity_user_message

from .levels import infer_level
from .preflight import preflight_extract_documents
from .recommender import recommend_for_rule, recommend_for_rule_async
from .service import SpecificationService

_MAX_DOCS = 1
_DEFAULT_WORKERS = 4


def _extract_workers() -> int:
    raw = os.environ.get("SIA_SPEC_EXTRACT_WORKERS", str(_DEFAULT_WORKERS)).strip()
    try:
        n = int(raw)
    except ValueError:
        n = _DEFAULT_WORKERS
    return max(1, min(n, 16))


class ExtractedRuleItem(BaseModel):
    name: str = Field(..., min_length=1, max_length=512)
    desc: str = Field("", max_length=8000)
    source: str = Field("", max_length=512)
    requirements: str = Field("", max_length=32000)
    algorithm_guidance: str = Field("", max_length=8000)


def _parse_json_array(content: str) -> list[Any]:
    s = (content or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.IGNORECASE)
    if m:
        s = m.group(1).strip()
    start = s.find("[")
    end = s.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("模型输出中未找到 JSON 数组")
    return json.loads(s[start : end + 1])


def _list_chunks_for_document(
    mm: ModelManager,
    *,
    kb_id: str,
    doc_ids: list[str],
    embedding_model_name: str | None,
) -> list[dict[str, Any]]:
    from inspection_platform.knowledge.ingest_service import KnowledgeIngestService

    kb = (kb_id or "default").strip() or "default"
    ks = KnowledgeIngestService(mm, embedding_model_name=embedding_model_name)
    docs = [d.strip() for d in doc_ids if d and str(d).strip()][:_MAX_DOCS]
    if not docs:
        raise ValueError(
            "doc_ids 不能为空；请传入已向量化文档的 document id（与 Milvus metadata.doc_id 一致）。"
        )

    chunks: list[dict[str, Any]] = []
    for did in docs:
        rows = ks.list_document_chunks(kb_id=kb, doc_id=did)
        if not rows:
            raise ValueError(
                f"文档 {did} 在知识库 kb_id={kb!r} 中无分片；请先 POST /api/knowledge/ingest"
            )
        chunks.extend(rows)
    return chunks


def _fallback_rule_from_chunk(
    *,
    text: str,
    source: str,
    chunk_index: int,
) -> ExtractedRuleItem:
    lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
    name_src = lines[0] if lines else f"文档分片 {chunk_index + 1}"
    name = name_src[:40] if len(name_src) > 40 else name_src
    req = (text or "").strip()
    if not req:
        req = "未在摘录中出现量化指标"
    return ExtractedRuleItem(
        name=name,
        desc="",
        source=source,
        requirements=req[:32000],
        algorithm_guidance="",
    )


async def _extract_one_rule_from_chunk_async(
    *,
    kb_id: str,
    topic: str,
    chunk_text: str,
    chunk_index: int,
    doc_id: str,
    model_name: str | None,
) -> ExtractedRuleItem | None:
    context = (
        f"### 文档分片 doc_id={doc_id} chunk_index={chunk_index}\n"
        + (chunk_text or "").strip()
    )
    user = build_rule_entity_user_message(
        kb_id=kb_id,
        topic=topic,
        max_rules=1,
        context=context,
        per_chunk=True,
    )
    req = build_chat_request(RULE_ENTITY_RECOGNIZER, user_content=user, model_name=model_name)
    from inspection_platform.deps import platform_call_chat_async

    resp = await platform_call_chat_async(req, model_name=model_name)
    raw_list = _parse_json_array(resp.content)
    for el in raw_list[:1]:
        if not isinstance(el, dict):
            continue
        try:
            return ExtractedRuleItem.model_validate(el)
        except Exception:
            continue
    return None


def _extract_one_rule_from_chunk(
    *,
    kb_id: str,
    topic: str,
    chunk_text: str,
    chunk_index: int,
    doc_id: str,
    model_name: str | None,
) -> ExtractedRuleItem | None:
    context = (
        f"### 文档分片 doc_id={doc_id} chunk_index={chunk_index}\n"
        + (chunk_text or "").strip()
    )
    user = build_rule_entity_user_message(
        kb_id=kb_id,
        topic=topic,
        max_rules=1,
        context=context,
        per_chunk=True,
    )
    req = build_chat_request(RULE_ENTITY_RECOGNIZER, user_content=user, model_name=model_name)
    from inspection_platform.deps import platform_call_chat

    resp = platform_call_chat(req, model_name=model_name)
    raw_list = _parse_json_array(resp.content)
    for el in raw_list[:1]:
        if not isinstance(el, dict):
            continue
        try:
            return ExtractedRuleItem.model_validate(el)
        except Exception:
            continue
    return None


async def _process_single_chunk_async(
    *,
    row: dict[str, Any],
    kb_eff: str,
    topic: str,
    backend_doc_id: str,
    doc_name: str,
    model_name: str | None,
    svc: SpecificationService,
    persist: bool,
) -> dict[str, Any]:
    chunk_text = str(row.get("text") or "").strip()
    chunk_index = int(row.get("chunk_index") or 0)
    chunk_id = str(row.get("chunk_id") or "")
    warnings: list[str] = []

    if not chunk_text:
        return {
            "type": "chunk_skipped",
            "chunk_index": chunk_index,
            "chunk_id": chunk_id,
            "warnings": [f"分片 {chunk_id or chunk_index} 为空，已跳过"],
        }

    item: ExtractedRuleItem | None = None
    try:
        item = await _extract_one_rule_from_chunk_async(
            kb_id=kb_eff,
            topic=topic,
            chunk_text=chunk_text,
            chunk_index=chunk_index,
            doc_id=backend_doc_id,
            model_name=model_name,
        )
    except (LLMError, ValueError, json.JSONDecodeError) as e:
        warnings.append(f"分片 {chunk_index} LLM 失败，使用原文兜底: {e}")

    if item is None:
        item = _fallback_rule_from_chunk(
            text=chunk_text,
            source=doc_name,
            chunk_index=chunk_index,
        )

    lv = infer_level(
        name=item.name,
        desc=item.desc,
        requirements=item.requirements,
        source=item.source,
    )
    rec = await recommend_for_rule_async(
        name=item.name,
        desc=item.desc,
        requirements=item.requirements,
        model_name=model_name,
        algorithm_guidance=item.algorithm_guidance or "",
    )
    if rec.get("error"):
        warnings.append(str(rec["error"]))
    algorithm_reasoning = (
        str(rec.get("algorithm_reasoning") or "").strip()
        or (item.algorithm_guidance or "").strip()
    )
    region_reasoning = str(rec.get("region_reasoning") or "").strip()
    rule_row = {
        "name": item.name,
        "desc": item.desc,
        "source": item.source or doc_name,
        "requirements": item.requirements,
        "level": lv,
        "recommended_regions": rec.get("region_ids") or [],
        "recommended_algorithms": rec.get("algorithm_ids") or [],
        "algorithm_reasoning": algorithm_reasoning,
        "region_reasoning": region_reasoning,
    }
    trace = {
        "doc_id": backend_doc_id,
        "document_name": doc_name,
        "chunk_id": chunk_id,
        "chunk_index": chunk_index,
        "kb_id": kb_eff,
    }
    rule_id = ""
    persisted_rule: dict[str, Any] | None = None
    if persist:

        def _persist() -> dict[str, Any]:
            return svc.create_rule(
                name=rule_row["name"],
                desc=rule_row["desc"],
                source=rule_row["source"],
                requirements=rule_row["requirements"],
                doc_id=backend_doc_id,
                level=rule_row["level"],
                recommended_regions=rule_row["recommended_regions"],
                recommended_algorithms=rule_row["recommended_algorithms"],
                algorithm_reasoning=rule_row["algorithm_reasoning"],
                region_reasoning=rule_row["region_reasoning"],
                source_trace=trace,
            )

        persisted_rule = await asyncio.to_thread(_persist)
        rule_id = str(persisted_rule.get("rule_id") or "")

    return {
        "type": "rule_created",
        "chunk_index": chunk_index,
        "chunk_id": chunk_id,
        "rule_id": rule_id,
        "rule": persisted_rule or rule_row,
        "warnings": warnings,
    }


def _process_single_chunk(
    *,
    row: dict[str, Any],
    kb_eff: str,
    topic: str,
    backend_doc_id: str,
    doc_name: str,
    model_name: str | None,
    svc: SpecificationService,
    persist: bool,
) -> dict[str, Any]:
    chunk_text = str(row.get("text") or "").strip()
    chunk_index = int(row.get("chunk_index") or 0)
    chunk_id = str(row.get("chunk_id") or "")
    warnings: list[str] = []

    if not chunk_text:
        return {
            "type": "chunk_skipped",
            "chunk_index": chunk_index,
            "chunk_id": chunk_id,
            "warnings": [f"分片 {chunk_id or chunk_index} 为空，已跳过"],
        }

    item: ExtractedRuleItem | None = None
    try:
        item = _extract_one_rule_from_chunk(
            kb_id=kb_eff,
            topic=topic,
            chunk_text=chunk_text,
            chunk_index=chunk_index,
            doc_id=backend_doc_id,
            model_name=model_name,
        )
    except (LLMError, ValueError, json.JSONDecodeError) as e:
        warnings.append(f"分片 {chunk_index} LLM 失败，使用原文兜底: {e}")

    if item is None:
        item = _fallback_rule_from_chunk(
            text=chunk_text,
            source=doc_name,
            chunk_index=chunk_index,
        )

    lv = infer_level(
        name=item.name,
        desc=item.desc,
        requirements=item.requirements,
        source=item.source,
    )
    rec = recommend_for_rule(
        name=item.name,
        desc=item.desc,
        requirements=item.requirements,
        model_name=model_name,
        algorithm_guidance=item.algorithm_guidance or "",
    )
    if rec.get("error"):
        warnings.append(str(rec["error"]))
    algorithm_reasoning = (
        str(rec.get("algorithm_reasoning") or "").strip()
        or (item.algorithm_guidance or "").strip()
    )
    region_reasoning = str(rec.get("region_reasoning") or "").strip()
    rule_row = {
        "name": item.name,
        "desc": item.desc,
        "source": item.source or doc_name,
        "requirements": item.requirements,
        "doc_id": backend_doc_id,
        "level": lv,
        "recommended_regions": rec.get("region_ids") or [],
        "recommended_algorithms": rec.get("algorithm_ids") or [],
        "region_reasoning": region_reasoning,
        "algorithm_reasoning": algorithm_reasoning,
    }
    trace: dict[str, Any] = {
        "doc_id": backend_doc_id,
        "kb_id": kb_eff,
        "extract_topic": topic or "",
        "chunk_id": chunk_id,
        "chunk_index": chunk_index,
        "extraction_mode": "per_chunk",
    }
    if doc_name:
        trace["document_name"] = doc_name

    rule_id: str | None = None
    persisted_rule: dict[str, Any] | None = None
    if persist:
        persisted_rule = svc.create_rule(
            name=rule_row["name"],
            desc=rule_row["desc"],
            source=rule_row["source"],
            requirements=rule_row["requirements"],
            doc_id=backend_doc_id,
            level=rule_row["level"],
            recommended_regions=rule_row["recommended_regions"],
            recommended_algorithms=rule_row["recommended_algorithms"],
            algorithm_reasoning=rule_row["algorithm_reasoning"],
            region_reasoning=rule_row["region_reasoning"],
            source_trace=trace,
        )
        rule_id = str(persisted_rule.get("rule_id") or "")

    return {
        "type": "rule_created",
        "chunk_index": chunk_index,
        "chunk_id": chunk_id,
        "rule_id": rule_id,
        "rule": persisted_rule or rule_row,
        "warnings": warnings,
    }


def _run_chunk_async_in_thread(
    *,
    row: dict[str, Any],
    kb_eff: str,
    topic: str,
    backend_doc_id: str,
    doc_name: str,
    model_name: str | None,
    svc: SpecificationService,
    persist: bool,
) -> dict[str, Any]:
    """线程池 worker：在线程内 asyncio.run 执行异步 API 调用。"""
    from inspection_platform.llm.async_runtime import run_async

    async def _job() -> dict[str, Any]:
        try:
            return await _process_single_chunk_async(
                row=row,
                kb_eff=kb_eff,
                topic=topic,
                backend_doc_id=backend_doc_id,
                doc_name=doc_name,
                model_name=model_name,
                svc=svc,
                persist=persist,
            )
        except Exception as e:
            return {
                "type": "chunk_failed",
                "detail": str(e),
                "chunk_index": int(row.get("chunk_index") or 0),
                "chunk_id": str(row.get("chunk_id") or ""),
                "warnings": [str(e)],
            }

    return run_async(_job())


def extract_rules_iter(
    *,
    svc: SpecificationService,
    mm: ModelManager,
    doc_ids: list[str],
    topic: str,
    max_rules: int | None = None,
    model_name: str | None = None,
    persist: bool = False,
    kb_id: str = "default",
    re_extract: bool = False,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    preflight: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    del max_rules  # 已废弃：按分片全量抽取

    kb_eff = (kb_id or "default").strip() or "default"
    docs = [d.strip() for d in doc_ids if d and str(d).strip()]
    if len(docs) > 1:
        raise ValueError("暂不支持多文档同时抽取，请仅传入一个 doc_id")
    if not docs:
        raise ValueError("doc_ids 不能为空")

    from inspection_platform.deps import platform_embedding_model_name

    emb_name = platform_embedding_model_name()
    if preflight is None:
        preflight = preflight_extract_documents(
            kb_id=kb_eff,
            doc_ids=docs,
            model_manager=mm,
            embedding_model_name=emb_name,
        )
    if not preflight["ready"]:
        raise ValueError("抽取预检未通过：" + "；".join(preflight["messages"]))

    doc_name_by_id = {
        str(d["doc_id"]): str(d.get("document_name") or "")
        for d in preflight.get("documents") or []
    }
    backend_doc_id = docs[0]
    svc.assert_doc_extractable(backend_doc_id, re_extract=re_extract)

    chunk_rows = _list_chunks_for_document(
        mm,
        kb_id=kb_eff,
        doc_ids=docs,
        embedding_model_name=emb_name,
    )
    doc_name = doc_name_by_id.get(backend_doc_id, "")

    cleared_drafts = 0
    if persist and re_extract:
        cleared_drafts = svc.delete_draft_rules_for_doc(backend_doc_id)

    workers = min(_extract_workers(), max(1, len(chunk_rows)))
    yield {
        "type": "extract_start",
        "chunks_total": len(chunk_rows),
        "workers": workers,
        "cleared_draft_count": cleared_drafts,
        "preflight": preflight,
    }

    created_ids: list[str] = []
    out_rules: list[dict[str, Any]] = []
    all_warnings: list[str] = []
    done_count = 0

    def _emit(ev: dict[str, Any]) -> None:
        if on_event:
            on_event(ev)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="spec-extract") as pool:
        futures = [
            pool.submit(
                _run_chunk_async_in_thread,
                row=row,
                kb_eff=kb_eff,
                topic=topic,
                backend_doc_id=backend_doc_id,
                doc_name=doc_name,
                model_name=model_name,
                svc=svc,
                persist=persist,
            )
            for row in chunk_rows
        ]
        pending = set(futures)
        while pending:
            done_set, pending = wait(pending, timeout=12.0, return_when=FIRST_COMPLETED)
            if not done_set:
                heartbeat = {
                    "type": "extract_heartbeat",
                    "done_count": done_count,
                    "chunks_total": len(chunk_rows),
                    "detail": "首批分片 LLM 抽取+推荐中（线程池+AsyncOpenAI）",
                }
                _emit(heartbeat)
                yield heartbeat
                continue
            for fut in done_set:
                try:
                    ev = fut.result()
                except Exception as e:
                    done_count += 1
                    ev = {
                        "type": "chunk_failed",
                        "detail": str(e),
                        "done_count": done_count,
                        "chunks_total": len(chunk_rows),
                        "warnings": [str(e)],
                    }
                    all_warnings.append(str(e))
                else:
                    done_count += 1
                    if ev.get("type") == "rule_created":
                        rid = str(ev.get("rule_id") or "").strip()
                        if rid:
                            created_ids.append(rid)
                        rule = ev.get("rule")
                        if isinstance(rule, dict):
                            out_rules.append(rule)
                    for w in ev.get("warnings") or []:
                        all_warnings.append(str(w))
                    ev["done_count"] = done_count
                    ev["chunks_total"] = len(chunk_rows)
                _emit(ev)
                yield ev

    yield {
        "type": "extract_done",
        "kb_id": kb_eff,
        "preflight": preflight,
        "rules": out_rules,
        "created_rule_ids": created_ids,
        "persisted": persist,
        "re_extract": re_extract,
        "cleared_draft_count": cleared_drafts,
        "warnings": all_warnings,
        "chunks_processed": done_count,
        "extraction_mode": "per_chunk",
    }


def extract_rules(
    *,
    svc: SpecificationService,
    mm: ModelManager,
    doc_ids: list[str],
    topic: str,
    max_rules: int | None = None,
    model_name: str | None = None,
    persist: bool = False,
    kb_id: str = "default",
    re_extract: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] | None = None
    for ev in extract_rules_iter(
        svc=svc,
        mm=mm,
        doc_ids=doc_ids,
        topic=topic,
        max_rules=max_rules,
        model_name=model_name,
        persist=persist,
        kb_id=kb_id,
        re_extract=re_extract,
    ):
        if ev.get("type") == "extract_done":
            result = ev
    if result is None:
        return {
            "kb_id": kb_id,
            "preflight": {},
            "rules": [],
            "created_rule_ids": [],
            "persisted": persist,
            "re_extract": re_extract,
            "warnings": [],
            "chunks_processed": 0,
            "extraction_mode": "per_chunk",
            "note": "未执行抽取。",
        }
    return result
