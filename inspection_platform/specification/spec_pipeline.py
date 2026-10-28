"""规范抽取多角色流水线（与 Hermes sia-spec-pipeline Skill 步骤一致）。"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from agent_base.llm.errors import LLMError
from agent_base.model_manager.manager import ModelManager

from .agent_roles import SPEC_COMPLIANCE_REVIEWER, build_chat_request
from .extractor import extract_rules, extract_rules_iter
from .preflight import preflight_extract_documents
from .service import SpecificationService

_PIPELINE_STAGES = (
    "preflight",
    "extract",
    "recommend_verify",
    "review",
)


@dataclass
class PipelineEvent:
    phase: str
    ok: bool
    detail: str = ""
    agent_id: str = ""
    skill: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "ok": self.ok,
            "detail": self.detail,
            "agent_id": self.agent_id,
            "skill": self.skill,
        }


@dataclass
class SpecPipelineState:
    kb_id: str
    doc_ids: list[str]
    goal: str
    events: list[PipelineEvent] = field(default_factory=list)

    def log(
        self,
        phase: str,
        ok: bool,
        detail: str = "",
        *,
        agent_id: str = "",
        skill: str = "",
    ) -> None:
        self.events.append(
            PipelineEvent(
                phase=phase,
                ok=ok,
                detail=detail,
                agent_id=agent_id,
                skill=skill,
            )
        )


def _parse_json_object(content: str) -> dict[str, Any]:
    s = (content or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.IGNORECASE)
    if m:
        s = m.group(1).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型输出中未找到 JSON 对象")
    return json.loads(s[start : end + 1])


def _call_role_json(
    role,
    user_content: str,
    *,
    model_name: str | None,
) -> dict[str, Any]:
    from inspection_platform.llm.async_runtime import run_async
    from inspection_platform.llm.openai_client import is_openai_api_configured

    req = build_chat_request(role, user_content=user_content, model_name=model_name)
    if is_openai_api_configured():
        from inspection_platform.deps import platform_call_chat_async

        resp = run_async(platform_call_chat_async(req, model_name=model_name))
    else:
        from inspection_platform.deps import platform_call_chat

        resp = platform_call_chat(req, model_name=model_name)
    return _parse_json_object(resp.content)


def _default_plan(*, goal: str, doc_name: str) -> dict[str, Any]:
    return {
        "scope": doc_name or goal or "单文档规范抽取",
        "risks": [],
        "deliverables": ["草稿规范条目（含区域/算法推荐）"],
        "notes": "按文档分片逐条抽取，不经语义检索",
    }


def _default_strategy(*, topic: str) -> dict[str, Any]:
    return {
        "topic": topic.strip() or "法规 制度 安全 管理",
        "extract_focus": ["义务", "禁止", "量化指标"],
        "acceptance_criteria": ["requirements 可核查"],
        "extraction_mode": "per_chunk",
    }


def _region_algo_ids(rule: dict[str, Any]) -> tuple[list[str], list[str]]:
    regions = rule.get("recommended_regions") or []
    algos = rule.get("recommended_algorithms") or []
    if not regions and rule.get("recommended_regions_json"):
        try:
            regions = json.loads(str(rule.get("recommended_regions_json") or "[]"))
        except Exception:
            regions = []
    if not algos and rule.get("recommended_algorithms_json"):
        try:
            algos = json.loads(str(rule.get("recommended_algorithms_json") or "[]"))
        except Exception:
            algos = []
    return [str(x) for x in regions if str(x).strip()], [str(x) for x in algos if str(x).strip()]


_REVIEW_LLM_MAX_RULES = 20
_REVIEW_SKIP_LLM_THRESHOLD = 40


def _rule_review_snapshot(rule: dict[str, Any]) -> dict[str, Any]:
    regs, algos = _region_algo_ids(rule)
    return {
        "rule_id": rule.get("rule_id"),
        "name": rule.get("name"),
        "desc": (rule.get("desc") or "")[:400],
        "requirements": (rule.get("requirements") or "")[:800],
        "recommended_regions": regs,
        "recommended_algorithms": algos,
        "region_reasoning": (rule.get("region_reasoning") or "")[:400],
        "algorithm_reasoning": (rule.get("algorithm_reasoning") or "")[:400],
    }


def _build_review_user_payload(
    *,
    pipeline_context: dict[str, Any],
    rules_for_review: list[dict[str, Any]],
    recommend_block: dict[str, Any],
) -> dict[str, Any]:
    total = len(rules_for_review)
    sample = [_rule_review_snapshot(r) for r in rules_for_review[:_REVIEW_LLM_MAX_RULES]]
    return {
        "review_scope": {
            "total_rules": total,
            "sampled_rules": len(sample),
            "note": (
                f"仅抽样前 {len(sample)} 条供审核；全量 {total} 条已入库为草稿。"
                if total > len(sample)
                else "全量条目如下。"
            ),
        },
        "recommend_verify": recommend_block,
        "pipeline_goal": pipeline_context.get("goal"),
        "rules_sample": sample,
    }


def _execute_review_phase(
    *,
    svc: SpecificationService,
    created_ids: list[str],
    pipeline_context: dict[str, Any],
    recommend_block: dict[str, Any],
    model_name: str | None,
) -> tuple[dict[str, Any], bool, str]:
    """合规审核：返回 (review_block, ok, log_detail)。"""
    rules_for_review: list[dict[str, Any]] = []
    for rid in created_ids:
        try:
            rules_for_review.append(svc.get_rule(rid))
        except KeyError:
            continue

    total = len(rules_for_review)
    if total == 0:
        block = {
            "approved_rule_ids": [],
            "rejected_rule_ids": [],
            "issues": [],
            "summary": "无草稿条目，跳过合规审核",
        }
        return block, True, block["summary"]

    if total > _REVIEW_SKIP_LLM_THRESHOLD:
        block = {
            "approved_rule_ids": created_ids,
            "rejected_rule_ids": [],
            "issues": [],
            "summary": (
                f"共 {total} 条草稿已入库；批量抽取跳过 LLM 合规审核"
                f"（空区域 {recommend_block.get('empty_region_count', 0)}、"
                f"空算法 {recommend_block.get('empty_algorithm_count', 0)}，建议人工抽查）"
            ),
        }
        return block, True, block["summary"][:160]

    try:
        review_user = json.dumps(
            _build_review_user_payload(
                pipeline_context=pipeline_context,
                rules_for_review=rules_for_review,
                recommend_block=recommend_block,
            ),
            ensure_ascii=False,
            indent=2,
        )
        raw_review = _call_role_json(SPEC_COMPLIANCE_REVIEWER, review_user, model_name=model_name)
        if "review" in raw_review and isinstance(raw_review["review"], dict):
            review_block = raw_review["review"]
        elif "approved_rule_ids" in raw_review:
            review_block = raw_review
        else:
            review_block = {
                "approved_rule_ids": created_ids,
                "rejected_rule_ids": [],
                "issues": [],
                "summary": "审核模型未返回结构化结果，默认通过",
            }
        detail = str(review_block.get("summary") or "")[:160]
        return review_block, True, detail
    except (LLMError, ValueError, json.JSONDecodeError) as e:
        review_block = {
            "approved_rule_ids": created_ids,
            "rejected_rule_ids": [],
            "issues": [{"rule_id": "", "severity": "warn", "message": f"审核跳过: {e}"}],
            "summary": "审核未执行，草稿已入库",
        }
        return review_block, False, str(e)
    except Exception as e:
        review_block = {
            "approved_rule_ids": created_ids,
            "rejected_rule_ids": [],
            "issues": [{"rule_id": "", "severity": "warn", "message": f"审核异常跳过: {e}"}],
            "summary": "审核阶段异常，草稿已入库",
        }
        return review_block, False, str(e)


def run_spec_extract_pipeline(
    *,
    svc: SpecificationService,
    mm: ModelManager,
    doc_ids: list[str],
    kb_id: str = "default",
    goal: str = "",
    topic: str = "",
    max_rules: int | None = None,
    persist: bool = True,
    re_extract: bool = False,
    model_name: str | None = None,
    embedding_model_name: str | None = None,
) -> dict[str, Any]:
    """
    Web 平台轻量流水线：预检 → 抽取（含推荐）→ 推荐确认 → 合规审核。
    topic / 分片遍历由请求参数指定，不调用项目经理、产品经理 LLM。
    每个向量化分片产出一条规范条目，不设 max_rules 上限。
    """
    kb = (kb_id or "default").strip() or "default"
    docs = [d.strip() for d in doc_ids if d and str(d).strip()]
    if len(docs) > 1:
        raise ValueError("流水线暂不支持多文档，请仅传入一个 doc_id")
    if not docs:
        raise ValueError("doc_ids 不能为空")

    state = SpecPipelineState(kb_id=kb, doc_ids=docs, goal=(goal or topic or "规范条目抽取").strip())
    pipeline_context: dict[str, Any] = {
        "version": 1,
        "step": "init",
        "kb_id": kb,
        "doc_ids": docs,
        "goal": state.goal,
        "stages": list(_PIPELINE_STAGES),
    }

    # ── 0. preflight ──
    preflight = preflight_extract_documents(
        kb_id=kb,
        doc_ids=docs,
        model_manager=mm,
        embedding_model_name=embedding_model_name,
    )
    doc_name = ""
    for row in preflight.get("documents") or []:
        doc_name = str(row.get("document_name") or "")
    if not preflight.get("ready"):
        state.log("preflight", False, "；".join(preflight.get("messages") or []))
        raise ValueError("流水线预检未通过：" + "；".join(preflight.get("messages") or []))
    state.log("preflight", True, f"chunks={sum(r.get('chunk_count', 0) for r in preflight.get('documents') or [])}")
    pipeline_context["step"] = "preflight_done"
    pipeline_context["preflight"] = preflight

    plan = _default_plan(goal=state.goal, doc_name=doc_name)
    strategy = _default_strategy(topic=topic or state.goal)
    topic_eff = str(strategy.get("topic") or topic or state.goal).strip()
    strategy["topic"] = topic_eff
    pipeline_context["plan"] = plan
    pipeline_context["strategy"] = strategy
    pipeline_context["step"] = "strategy_ready"

    # ── extract（含平台内抽取 + 推荐 Agent）──
    extract_out = extract_rules(
        svc=svc,
        mm=mm,
        doc_ids=docs,
        topic=topic_eff,
        model_name=model_name,
        persist=persist,
        kb_id=kb,
        re_extract=re_extract,
    )
    created_ids = list(extract_out.get("created_rule_ids") or [])
    rules_count = len(extract_out.get("rules") or [])
    extract_ok = rules_count > 0 or bool(extract_out.get("note"))
    state.log(
        "extract",
        extract_ok,
        f"rules={rules_count} created={len(created_ids)} chunks={extract_out.get('chunks_processed', 0)}",
        agent_id="spec_rule_entity_recognizer",
        skill="sia-spec-step-extract",
    )
    pipeline_context["extract"] = {
        "created_rule_ids": created_ids,
        "rules_count": rules_count,
        "warnings": extract_out.get("warnings") or [],
        "note": extract_out.get("note") or "",
    }
    pipeline_context["step"] = "extract_done"

    # ── 4. recommend_verify ──
    checked: list[str] = []
    empty_region = 0
    empty_algo = 0
    for rid in created_ids:
        try:
            rec = svc.get_rule(rid)
        except KeyError:
            continue
        checked.append(rid)
        regs, algos = _region_algo_ids(rec)
        if not regs:
            empty_region += 1
        if not algos:
            empty_algo += 1
    recommend_block = {
        "checked_rule_ids": checked,
        "empty_region_count": empty_region,
        "empty_algorithm_count": empty_algo,
        "remediation": [],
    }
    state.log(
        "recommend_verify",
        True,
        f"empty_region={empty_region} empty_algo={empty_algo}",
        agent_id="spec_region_algorithm_matcher",
        skill="sia-spec-step-recommend",
    )
    pipeline_context["recommend"] = recommend_block
    pipeline_context["step"] = "recommend_done"

    # ── 5. review ──
    review_block, review_ok, review_detail = _execute_review_phase(
        svc=svc,
        created_ids=created_ids,
        pipeline_context=pipeline_context,
        recommend_block=recommend_block,
        model_name=model_name,
    )
    state.log(
        "review",
        review_ok,
        review_detail,
        agent_id=SPEC_COMPLIANCE_REVIEWER.id,
        skill=SPEC_COMPLIANCE_REVIEWER.skill,
    )
    pipeline_context["review"] = review_block
    pipeline_context["step"] = "review_done"

    return {
        **extract_out,
        "pipeline_context": pipeline_context,
        "pipeline_events": [e.as_dict() for e in state.events],
        "plan": plan,
        "strategy": strategy,
        "recommend_verify": recommend_block,
        "review": review_block,
        "orchestration": "sia-spec-pipeline",
    }


def iter_spec_extract_pipeline(
    *,
    svc: SpecificationService,
    mm: ModelManager,
    doc_ids: list[str],
    kb_id: str = "default",
    goal: str = "",
    topic: str = "",
    max_rules: int | None = None,
    persist: bool = True,
    re_extract: bool = False,
    model_name: str | None = None,
    embedding_model_name: str | None = None,
) -> Iterator[dict[str, Any]]:
    """流式流水线：预检 → 并发分片抽取（逐条入库）→ 推荐确认 → 审核。"""
    kb = (kb_id or "default").strip() or "default"
    docs = [d.strip() for d in doc_ids if d and str(d).strip()]
    if len(docs) > 1:
        raise ValueError("流水线暂不支持多文档，请仅传入一个 doc_id")
    if not docs:
        raise ValueError("doc_ids 不能为空")

    state = SpecPipelineState(kb_id=kb, doc_ids=docs, goal=(goal or topic or "规范条目抽取").strip())
    pipeline_context: dict[str, Any] = {
        "version": 1,
        "step": "init",
        "kb_id": kb,
        "doc_ids": docs,
        "goal": state.goal,
        "stages": list(_PIPELINE_STAGES),
    }

    preflight = preflight_extract_documents(
        kb_id=kb,
        doc_ids=docs,
        model_manager=mm,
        embedding_model_name=embedding_model_name,
    )
    doc_name = ""
    for row in preflight.get("documents") or []:
        doc_name = str(row.get("document_name") or "")
    if not preflight.get("ready"):
        state.log("preflight", False, "；".join(preflight.get("messages") or []))
        yield {
            "type": "error",
            "message": "流水线预检未通过：" + "；".join(preflight.get("messages") or []),
        }
        return

    chunk_total = sum(r.get("chunk_count", 0) for r in preflight.get("documents") or [])
    state.log("preflight", True, f"chunks={chunk_total}")
    pipeline_context["step"] = "preflight_done"
    pipeline_context["preflight"] = preflight
    yield {
        "type": "phase",
        "phase": "preflight",
        "ok": True,
        "detail": f"chunks={chunk_total}",
        "chunks_total": chunk_total,
    }

    plan = _default_plan(goal=state.goal, doc_name=doc_name)
    strategy = _default_strategy(topic=topic or state.goal)
    topic_eff = str(strategy.get("topic") or topic or state.goal).strip()
    strategy["topic"] = topic_eff
    pipeline_context["plan"] = plan
    pipeline_context["strategy"] = strategy
    pipeline_context["step"] = "strategy_ready"

    extract_out: dict[str, Any] = {}
    for ev in extract_rules_iter(
        svc=svc,
        mm=mm,
        doc_ids=docs,
        topic=topic_eff,
        max_rules=max_rules,
        model_name=model_name,
        persist=persist,
        kb_id=kb,
        re_extract=re_extract,
        preflight=preflight,
    ):
        if ev.get("type") == "extract_done":
            extract_out = ev
            continue
        if ev.get("type") in ("rule_created", "chunk_skipped", "chunk_failed", "extract_heartbeat"):
            yield ev
        elif ev.get("type") == "extract_start":
            yield {
                "type": "extract_start",
                "chunks_total": ev.get("chunks_total"),
                "workers": ev.get("workers"),
                "cleared_draft_count": ev.get("cleared_draft_count"),
            }

    created_ids = list(extract_out.get("created_rule_ids") or [])
    rules_count = len(extract_out.get("rules") or [])
    extract_ok = rules_count > 0 or bool(extract_out.get("note"))
    state.log(
        "extract",
        extract_ok,
        f"rules={rules_count} created={len(created_ids)} chunks={extract_out.get('chunks_processed', 0)}",
        agent_id="spec_rule_entity_recognizer",
        skill="sia-spec-step-extract",
    )
    pipeline_context["extract"] = {
        "created_rule_ids": created_ids,
        "rules_count": rules_count,
        "warnings": extract_out.get("warnings") or [],
        "note": extract_out.get("note") or "",
    }
    pipeline_context["step"] = "extract_done"
    yield {
        "type": "phase",
        "phase": "extract",
        "ok": extract_ok,
        "detail": f"rules={rules_count} chunks={extract_out.get('chunks_processed', 0)}",
        "created_rule_ids": created_ids,
    }

    checked: list[str] = []
    empty_region = 0
    empty_algo = 0
    for rid in created_ids:
        try:
            rec = svc.get_rule(rid)
        except KeyError:
            continue
        checked.append(rid)
        regs, algos = _region_algo_ids(rec)
        if not regs:
            empty_region += 1
        if not algos:
            empty_algo += 1
    recommend_block = {
        "checked_rule_ids": checked,
        "empty_region_count": empty_region,
        "empty_algorithm_count": empty_algo,
        "remediation": [],
    }
    state.log(
        "recommend_verify",
        True,
        f"empty_region={empty_region} empty_algo={empty_algo}",
        agent_id="spec_region_algorithm_matcher",
        skill="sia-spec-step-recommend",
    )
    pipeline_context["recommend"] = recommend_block
    pipeline_context["step"] = "recommend_done"
    yield {
        "type": "phase",
        "phase": "recommend_verify",
        "ok": True,
        "detail": f"empty_region={empty_region} empty_algo={empty_algo}",
    }

    review_block, review_ok, review_detail = _execute_review_phase(
        svc=svc,
        created_ids=created_ids,
        pipeline_context=pipeline_context,
        recommend_block=recommend_block,
        model_name=model_name,
    )
    state.log(
        "review",
        review_ok,
        review_detail,
        agent_id=SPEC_COMPLIANCE_REVIEWER.id,
        skill=SPEC_COMPLIANCE_REVIEWER.skill,
    )
    pipeline_context["review"] = review_block
    pipeline_context["step"] = "review_done"
    yield {
        "type": "phase",
        "phase": "review",
        "ok": review_ok,
        "detail": str(review_block.get("summary") or review_detail)[:160],
    }

    yield {
        "type": "done",
        "result": {
            "kb_id": extract_out.get("kb_id", kb),
            "created_rule_ids": created_ids,
            "cleared_draft_count": extract_out.get("cleared_draft_count", 0),
            "warnings": extract_out.get("warnings") or [],
            "chunks_processed": extract_out.get("chunks_processed", 0),
            "extraction_mode": extract_out.get("extraction_mode", "per_chunk"),
            "pipeline_events": [e.as_dict() for e in state.events],
            "recommend_verify": recommend_block,
            "review": review_block,
            "orchestration": "sia-spec-pipeline",
        },
    }
