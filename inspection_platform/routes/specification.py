"""规范管理 HTTP API。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Path, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from inspection_platform.deps import (
    get_model_manager,
    get_specification_service,
    platform_embedding_model_name,
)
from inspection_platform.specification.extractor import extract_rules
from inspection_platform.specification.preflight import preflight_extract_documents
from inspection_platform.specification.spec_pipeline import (
    iter_spec_extract_pipeline,
    run_spec_extract_pipeline,
)

router = APIRouter(prefix="/api/spec", tags=["specification"])

SpecRuleIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=64,
        description="规范规则主键：SQLite 表 spec_rule 的 rule_id；发布后会写入规则向量库。",
    ),
]


class SpecRuleExtractBody(BaseModel):
    kb_id: str = Field(
        default="default",
        max_length=64,
        description="知识库分区 id；须先对文档库中的 document_id 执行 POST /api/knowledge/ingest 向量化。",
    )
    doc_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=12,
        description=(
            "须显式指定至少一个已向量化文档：元素为 Milvus metadata 中的 doc_id"
            "（与 POST /api/knowledge/ingest 的 document_id、文档库主键一致）。"
        ),
    )
    topic: str = Field(default="", max_length=2000)
    max_rules: int | None = Field(
        default=None,
        ge=1,
        description="已废弃：抽取改为按分片逐条产出，不再使用该上限。",
    )
    model_name: str | None = Field(default=None)
    persist: bool = Field(default=False)
    re_extract: bool = Field(
        default=False,
        description=(
            "为 true 时允许对已抽取文档再次抽取：先清除该 doc 下全部草稿规则，"
            "已发布条目保留；须 persist=true。"
        ),
    )

    @field_validator("doc_ids", mode="before")
    @classmethod
    def _doc_ids_allow_single_str(cls, v: object) -> object:
        if isinstance(v, str):
            s = v.strip()
            return [s] if s else []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return v


_EXTRACT_OPENAPI_EXAMPLES: dict[str, dict[str, object]] = {
    "single_document": {
        "summary": "单文档抽取（推荐）",
        "value": {
            "kb_id": "default",
            "doc_ids": ["替换为已向量化文档的 UUID"],
            "topic": "安全生产 现场管理",
            "persist": True,
        },
    },
}


@router.post(
    "/rules/extract",
    summary="从知识库文档抽取规范实体（规则）",
    description=(
        "从知识库 Milvus 检索分片；persist=true 时写入全局规则草稿。"
        "默认同一 doc_id 仅允许抽取一次；re_extract=true 时清除该文档草稿后重抽。"
    ),
)
def extract_spec_rules(
    body: Annotated[
        SpecRuleExtractBody,
        Body(openapi_examples=_EXTRACT_OPENAPI_EXAMPLES),
    ],
) -> dict:
    try:
        return extract_rules(
            svc=get_specification_service(),
            mm=get_model_manager(),
            doc_ids=body.doc_ids,
            topic=body.topic,
            max_rules=body.max_rules,
            model_name=body.model_name,
            persist=body.persist,
            kb_id=body.kb_id,
            re_extract=body.re_extract,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


class SpecRuleExtractPipelineBody(SpecRuleExtractBody):
    goal: str = Field(
        default="",
        max_length=2000,
        description="用户业务目标；为空时用 topic 或默认文案。对应 Skill 流水线 goal。",
    )


@router.post(
    "/rules/extract/pipeline",
    summary="规范抽取流水线（预检→抽取→推荐确认→审核）",
    description=(
        "Web 轻量流水线：预检、按分片规范抽取+区域/算法推荐、推荐确认、合规审核。"
        "每个向量化分片产出一条规范条目，不经语义检索，不设 max_rules 上限。"
    ),
)
def extract_spec_rules_pipeline(
    body: Annotated[
        SpecRuleExtractPipelineBody,
        Body(openapi_examples=_EXTRACT_OPENAPI_EXAMPLES),
    ],
) -> dict:
    try:
        return run_spec_extract_pipeline(
            svc=get_specification_service(),
            mm=get_model_manager(),
            doc_ids=body.doc_ids,
            kb_id=body.kb_id,
            goal=body.goal,
            topic=body.topic,
            max_rules=body.max_rules,
            model_name=body.model_name,
            persist=body.persist,
            re_extract=body.re_extract,
            embedding_model_name=platform_embedding_model_name(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post(
    "/rules/extract/pipeline/stream",
    summary="规范抽取流水线（SSE 流式，分片完成即入库）",
    description=(
        "Server-Sent Events：每个分片抽取+推荐完成后立即写入 spec_rule，"
        "前端可边收边展示。最后阶段含推荐确认与合规审核。"
    ),
)
def extract_spec_rules_pipeline_stream(
    body: Annotated[
        SpecRuleExtractPipelineBody,
        Body(openapi_examples=_EXTRACT_OPENAPI_EXAMPLES),
    ],
) -> StreamingResponse:
    import json
    from collections.abc import Iterator

    def gen() -> Iterator[str]:
        try:
            for ev in iter_spec_extract_pipeline(
                svc=get_specification_service(),
                mm=get_model_manager(),
                doc_ids=body.doc_ids,
                kb_id=body.kb_id,
                goal=body.goal,
                topic=body.topic,
                max_rules=body.max_rules,
                model_name=body.model_name,
                persist=body.persist,
                re_extract=body.re_extract,
                embedding_model_name=platform_embedding_model_name(),
            ):
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        except ValueError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
        except RuntimeError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'流水线异常: {e}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class SpecExtractPreflightBody(BaseModel):
    kb_id: str = Field(default="default", max_length=64)
    doc_ids: list[str] = Field(..., min_length=1, max_length=12)

    @field_validator("doc_ids", mode="before")
    @classmethod
    def _doc_ids_allow_single_str(cls, v: object) -> object:
        if isinstance(v, str):
            s = v.strip()
            return [s] if s else []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return v


@router.post("/rules/extract/preflight", summary="抽取前预检（文档存在、已向量化）")
def extract_spec_preflight(body: SpecExtractPreflightBody) -> dict:
    return preflight_extract_documents(
        kb_id=body.kb_id,
        doc_ids=body.doc_ids,
        model_manager=get_model_manager(),
        embedding_model_name=platform_embedding_model_name(),
    )


class SpecRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=512)
    desc: str = Field(default="", max_length=8000)
    source: str = Field(default="", max_length=512)
    requirements: str = Field(default="", max_length=32000)
    doc_id: str | None = Field(default=None, max_length=64)
    level: str | None = Field(default=None)
    recommended_algorithms: list[str] | None = Field(default=None)
    recommended_regions: list[str] | None = Field(default=None)
    algorithm_reasoning: str = Field(default="", max_length=8000)
    region_reasoning: str = Field(default="", max_length=8000)
    source_trace: dict | None = Field(default=None, description="来源追溯信息（doc_id、document_name 等）")


class SpecRulePatch(BaseModel):
    name: str | None = Field(default=None, max_length=512)
    desc: str | None = Field(default=None)
    source: str | None = Field(default=None, max_length=512)
    requirements: str | None = Field(default=None)
    level: str | None = Field(default=None)
    doc_id: str | None = Field(default=None)
    status: str | None = Field(default=None)
    recommended_algorithms: list[str] | None = Field(default=None)
    recommended_regions: list[str] | None = Field(default=None)
    algorithm_reasoning: str | None = Field(default=None)
    region_reasoning: str | None = Field(default=None)
    source_trace: dict | None = Field(default=None)


class SpecRulesQueryBody(BaseModel):
    query: str = Field(..., min_length=1, max_length=8000)
    top_k: int = Field(default=5, ge=1, le=30)


@router.get("/stats", summary="规范库统计")
def spec_stats() -> dict:
    return get_specification_service().stats()


@router.post("/rules/rebuild-vectors", summary="重建全部已发布规则向量")
def rebuild_spec_rule_vectors() -> dict:
    try:
        return get_specification_service().rebuild_published_vectors()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/query/rules", summary="已发布规范规则向量检索")
def query_spec_rules(body: SpecRulesQueryBody) -> list[dict]:
    try:
        return get_specification_service().query_rules(query=body.query, top_k=body.top_k)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/rules", summary="列出规范规则")
def list_spec_rules(
    status: str | None = Query(default=None, description="draft / published"),
) -> list[dict]:
    st = (status or "").strip() or None
    return get_specification_service().list_rules(status=st)


@router.post("/rules", summary="手动创建规范规则", status_code=201)
def create_spec_rule(body: SpecRuleCreate) -> dict:
    try:
        return get_specification_service().create_rule(
            name=body.name,
            desc=body.desc,
            source=body.source,
            requirements=body.requirements,
            doc_id=body.doc_id,
            level=body.level,
            recommended_algorithms=body.recommended_algorithms,
            recommended_regions=body.recommended_regions,
            algorithm_reasoning=body.algorithm_reasoning,
            region_reasoning=body.region_reasoning,
            source_trace=body.source_trace,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/rules/{rule_id}", summary="获取单条规范规则")
def get_spec_rule(rule_id: SpecRuleIdPath) -> dict:
    try:
        return get_specification_service().get_rule(rule_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="rule not found") from None


@router.get("/rules/{rule_id}/publish-readiness", summary="发布就绪检查")
def get_publish_readiness(rule_id: SpecRuleIdPath) -> dict:
    try:
        return get_specification_service().publish_readiness(rule_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="rule not found") from None


@router.patch("/rules/{rule_id}", summary="更新规范规则")
def patch_spec_rule(rule_id: SpecRuleIdPath, body: SpecRulePatch) -> dict:
    try:
        return get_specification_service().update_rule(
            rule_id,
            name=body.name,
            desc=body.desc,
            source=body.source,
            requirements=body.requirements,
            level=body.level,
            doc_id=body.doc_id,
            status=body.status,
            recommended_algorithms=body.recommended_algorithms,
            recommended_regions=body.recommended_regions,
            algorithm_reasoning=body.algorithm_reasoning,
            region_reasoning=body.region_reasoning,
            source_trace=body.source_trace,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="rule not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/rules/{rule_id}/publish", summary="发布规范规则")
def publish_spec_rule(rule_id: SpecRuleIdPath) -> dict:
    try:
        return get_specification_service().publish_rule(rule_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="rule not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"发布服务异常：{e}") from e


@router.delete(
    "/rules/{rule_id}",
    status_code=204,
    response_class=Response,
    summary="删除规范规则",
)
def delete_spec_rule(rule_id: SpecRuleIdPath) -> Response:
    try:
        get_specification_service().delete_rule(rule_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="rule not found") from None
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return Response(status_code=204)
