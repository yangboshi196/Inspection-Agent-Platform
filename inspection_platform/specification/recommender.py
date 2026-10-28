"""规范条目：适用区域与推荐算法智能匹配（Hermes/平台 LLM）。"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from agent_base.llm.errors import LLMError

from .agent_roles import (
    REGION_ALGORITHM_MATCHER,
    build_chat_request,
    build_region_algorithm_user_message,
)


@lru_cache(maxsize=1)
def _load_region_catalog() -> list[dict[str, str]]:
    from inspection_platform.document.region_meta import RegionMetaService

    svc = RegionMetaService()
    rows = svc.list_regions()
    out: list[dict[str, str]] = []
    for r in rows:
        rid = str(r.get("id") or "").strip()
        if not rid:
            continue
        out.append(
            {
                "id": rid,
                "name": str(r.get("name") or "").strip(),
                "desc": str(r.get("desc") or "").strip(),
            }
        )
    return out


@lru_cache(maxsize=1)
def _load_algorithm_catalog() -> list[dict[str, str]]:
    from inspection_platform.algorithm.service import AlgorithmService

    svc = AlgorithmService()
    items, _ = svc.list_algorithms(limit=500, offset=0)
    out: list[dict[str, str]] = []
    for a in items:
        aid = str(a.get("algorithm_id") or "").strip()
        if not aid:
            continue
        out.append(
            {
                "algorithm_id": aid,
                "name": str(a.get("name") or "").strip(),
                "desc": str(a.get("desc") or "").strip(),
                "health": str(a.get("health") or "unknown").strip(),
            }
        )
    return out


def clear_recommendation_catalog_cache() -> None:
    _load_region_catalog.cache_clear()
    _load_algorithm_catalog.cache_clear()


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


def _coerce_id_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for el in raw:
        if isinstance(el, dict):
            sid = str(el.get("id") or el.get("algorithm_id") or el.get("region_id") or "").strip()
        else:
            sid = str(el).strip()
        if sid:
            out.append(sid)
    return out


def _extract_recommendation_ids(
    obj: dict[str, Any],
    *,
    region_allowed: set[str],
    algo_allowed: set[str],
    regions: list[dict[str, str]],
    algorithms: list[dict[str, str]],
) -> tuple[list[str], list[str]]:
    region_raw = (
        obj.get("region_ids")
        or obj.get("recommended_regions")
        or obj.get("regions")
        or []
    )
    algo_raw = (
        obj.get("algorithm_ids")
        or obj.get("recommended_algorithms")
        or obj.get("algorithms")
        or []
    )
    region_ids = _validate_ids(_coerce_id_list(region_raw), allowed=region_allowed, field="region_ids")
    algorithm_ids = _validate_ids(_coerce_id_list(algo_raw), allowed=algo_allowed, field="algorithm_ids")

    if not region_ids:
        region_ids = _match_ids_by_name(
            _coerce_id_list(region_raw),
            catalog=regions,
            id_key="id",
            name_keys=("name", "region_name"),
        )
    if not algorithm_ids:
        algorithm_ids = _match_ids_by_name(
            _coerce_id_list(algo_raw),
            catalog=algorithms,
            id_key="algorithm_id",
            name_keys=("name", "algorithm_name"),
        )
    return region_ids, algorithm_ids


def _match_ids_by_name(
    tokens: list[str],
    *,
    catalog: list[dict[str, str]],
    id_key: str,
    name_keys: tuple[str, ...],
) -> list[str]:
    if not tokens:
        return []
    name_to_id: dict[str, str] = {}
    for row in catalog:
        rid = str(row.get(id_key) or "").strip()
        if not rid:
            continue
        for key in name_keys:
            name = str(row.get(key) or "").strip()
            if name:
                name_to_id[name] = rid
    seen: set[str] = set()
    out: list[str] = []
    for token in tokens:
        rid = name_to_id.get(token)
        if not rid or rid in seen:
            continue
        seen.add(rid)
        out.append(rid)
    return out


def _validate_ids(
    raw_ids: Any,
    *,
    allowed: set[str],
    field: str,
) -> list[str]:
    if not isinstance(raw_ids, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for el in raw_ids:
        sid = str(el).strip()
        if not sid or sid in seen:
            continue
        if sid not in allowed:
            continue
        seen.add(sid)
        out.append(sid)
    return out


def _fallback_region_reasoning(
    region_ids: list[str],
    regions: list[dict[str, str]],
    *,
    rule_name: str = "",
) -> str:
    name_by_id = {r["id"]: r.get("name") or r["id"] for r in regions}
    names = [name_by_id.get(rid, rid) for rid in region_ids if rid]
    if not names:
        return ""
    title = (rule_name or "").strip()
    if len(names) == 1:
        base = f"本条规范适用于「{names[0]}」"
    elif len(names) <= 4:
        base = f"本条规范适用于「{'」「'.join(names)}」"
    else:
        base = f"本条规范适用于「{'」「'.join(names[:3])}」等 {len(names)} 个区域"
    return f"{base}，与条目描述的现场管控场景相匹配。" if title else f"{base}。"


def _fallback_algorithm_reasoning(
    algorithm_ids: list[str],
    algorithms: list[dict[str, str]],
    *,
    rule_name: str = "",
    algorithm_guidance: str = "",
) -> str:
    guidance = (algorithm_guidance or "").strip()
    if guidance:
        return guidance
    name_by_id = {a["algorithm_id"]: a.get("name") or a["algorithm_id"] for a in algorithms}
    names = [name_by_id.get(aid, aid) for aid in algorithm_ids if aid]
    if not names:
        return ""
    title = (rule_name or "").strip()
    algo_text = "、".join(names[:3])
    if len(names) > 3:
        algo_text += f" 等 {len(names)} 项算法"
    if title:
        return f"建议通过「{algo_text}」对「{title}」相关场景进行监测或巡检，并与人工核查、记录留痕相结合。"
    return f"建议通过「{algo_text}」进行监测或巡检，并与人工核查、记录留痕相结合。"


def recommend_for_rule(
    *,
    name: str,
    desc: str,
    requirements: str,
    model_name: str | None = None,
    algorithm_guidance: str = "",
) -> dict[str, Any]:
    """
    为单条规范匹配适用区域与推荐算法，返回可写入 spec_rule 的推荐字段。
    """
    regions = _load_region_catalog()
    algorithms = _load_algorithm_catalog()
    region_allowed = {r["id"] for r in regions}
    algo_allowed = {a["algorithm_id"] for a in algorithms}

    user = build_region_algorithm_user_message(
        name=name,
        desc=desc,
        requirements=requirements,
        regions=regions,
        algorithms=algorithms,
    )
    req = build_chat_request(REGION_ALGORITHM_MATCHER, user_content=user, model_name=model_name)

    try:
        from inspection_platform.deps import platform_call_chat

        resp = platform_call_chat(req, model_name=model_name)
    except LLMError as e:
        return {
            "region_ids": [],
            "algorithm_ids": [],
            "region_reasoning": "",
            "algorithm_reasoning": "",
            "error": f"LLM 调用失败: {e.code} {e.message}",
        }

    try:
        obj = _parse_json_object(resp.content)
    except Exception as e:
        return {
            "region_ids": [],
            "algorithm_ids": [],
            "region_reasoning": "",
            "algorithm_reasoning": "",
            "error": f"推荐结果解析失败: {e}",
        }

    region_ids, algorithm_ids = _extract_recommendation_ids(
        obj,
        region_allowed=region_allowed,
        algo_allowed=algo_allowed,
        regions=regions,
        algorithms=algorithms,
    )
    region_reasoning = str(obj.get("region_reasoning") or "").strip()
    algorithm_reasoning = str(obj.get("algorithm_reasoning") or "").strip()

    if region_ids and not region_reasoning:
        region_reasoning = _fallback_region_reasoning(
            region_ids, regions, rule_name=name
        )
    if algorithm_ids and not algorithm_reasoning:
        algorithm_reasoning = _fallback_algorithm_reasoning(
            algorithm_ids,
            algorithms,
            rule_name=name,
            algorithm_guidance=algorithm_guidance,
        )
    if not region_reasoning and (desc or "").strip():
        region_reasoning = (desc or "").strip()

    return {
        "region_ids": region_ids,
        "algorithm_ids": algorithm_ids,
        "region_reasoning": region_reasoning,
        "algorithm_reasoning": algorithm_reasoning,
    }


async def recommend_for_rule_async(
    *,
    name: str,
    desc: str,
    requirements: str,
    model_name: str | None = None,
    algorithm_guidance: str = "",
) -> dict[str, Any]:
    """异步版：为单条规范匹配适用区域与推荐算法。"""
    regions = _load_region_catalog()
    algorithms = _load_algorithm_catalog()
    region_allowed = {r["id"] for r in regions}
    algo_allowed = {a["algorithm_id"] for a in algorithms}

    user = build_region_algorithm_user_message(
        name=name,
        desc=desc,
        requirements=requirements,
        regions=regions,
        algorithms=algorithms,
    )
    req = build_chat_request(REGION_ALGORITHM_MATCHER, user_content=user, model_name=model_name)

    try:
        from inspection_platform.deps import platform_call_chat_async

        resp = await platform_call_chat_async(req, model_name=model_name)
    except LLMError as e:
        return {
            "region_ids": [],
            "algorithm_ids": [],
            "region_reasoning": "",
            "algorithm_reasoning": "",
            "error": f"LLM 调用失败: {e.code} {e.message}",
        }

    try:
        obj = _parse_json_object(resp.content)
    except Exception as e:
        return {
            "region_ids": [],
            "algorithm_ids": [],
            "region_reasoning": "",
            "algorithm_reasoning": "",
            "error": f"推荐结果解析失败: {e}",
        }

    region_ids, algorithm_ids = _extract_recommendation_ids(
        obj,
        region_allowed=region_allowed,
        algo_allowed=algo_allowed,
        regions=regions,
        algorithms=algorithms,
    )
    region_reasoning = str(obj.get("region_reasoning") or "").strip()
    algorithm_reasoning = str(obj.get("algorithm_reasoning") or "").strip()

    if region_ids and not region_reasoning:
        region_reasoning = _fallback_region_reasoning(region_ids, regions, rule_name=name)
    if algorithm_ids and not algorithm_reasoning:
        algorithm_reasoning = _fallback_algorithm_reasoning(
            algorithm_ids,
            algorithms,
            rule_name=name,
            algorithm_guidance=algorithm_guidance,
        )
    if not region_reasoning and (desc or "").strip():
        region_reasoning = (desc or "").strip()

    return {
        "region_ids": region_ids,
        "algorithm_ids": algorithm_ids,
        "region_reasoning": region_reasoning,
        "algorithm_reasoning": algorithm_reasoning,
    }
