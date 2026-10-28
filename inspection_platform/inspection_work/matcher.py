"""根据向量检索命中的规范与算法目录，调用 LLM 生成巡检业务草案。"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from agent_base.llm.errors import LLMError
from agent_base.llm.types import ChatRequest, LlmChatMessage
from agent_base.model_manager.manager import ModelManager
from agent_base.prompts import load_prompt

from inspection_platform.algorithm.service import AlgorithmService
from inspection_platform.equipment.service import EquipmentService
from inspection_platform.inspection_work.catalog import (
    EntityCatalog,
    catalog_llm_payload,
    collect_from_intent,
    collect_from_rules,
    filter_devices_for_regions,
    merge_catalogs,
)
from inspection_platform.inspection_work.intent import extract_user_intent
from inspection_platform.inspection_work.entity_resolve import IntentPins, resolve_intent_entities
from inspection_platform.document.region_meta import RegionMetaService
from inspection_platform.inspection_work.retrieval import (
    RULE_MISS_TRACE_MESSAGE,
    RULE_VECTOR_MAX_K,
    RuleRetrievalResult,
    retrieve_published_rules_by_topic,
    rule_hit_to_trace,
)
from inspection_platform.specification.service import SpecificationService
from inspection_platform.envutil import env_first

RULE_RETRIEVAL_TOP_K = RULE_VECTOR_MAX_K
_WORK_MATCH_PROMPT = load_prompt("inspection_work/work_catalog_match.txt")
_RULE_MATCH_PROMPT = load_prompt("inspection_work/rule_catalog_match.txt")
_SYSTEM_PROMPT = load_prompt("inspection_work/match_rules_algorithms.txt")
_RETRY_APPEND = (
    "\n\n【重要】上次输出无法解析。请仅输出合法 JSON 数组："
    "不要用 ``` 包裹；desc 不超过 50 字且不含英文双引号；"
    "每条 equipment_set 最多 2 个设备。"
)


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[\w\u4e00-\u9fff]{2,}", (text or "").lower()))


def _repair_json_text(s: str) -> str:
    t = s.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    t = re.sub(r",\s*]", "]", t)
    t = re.sub(r",\s*}", "}", t)
    return t


def _extract_json_objects(s: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    depth = 0
    start = -1
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    chunk = s[start : i + 1]
                    try:
                        obj = json.loads(_repair_json_text(chunk))
                        if isinstance(obj, dict):
                            out.append(obj)
                    except json.JSONDecodeError:
                        pass
                    start = -1
    return out


def _parse_json_array(content: str) -> list[Any]:
    s = (content or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.IGNORECASE)
    if m:
        s = m.group(1).strip()
    start = s.find("[")
    end = s.rfind("]")
    if start < 0 or end <= start:
        objs = _extract_json_objects(s)
        if objs:
            return objs
        raise ValueError("模型输出中未找到 JSON 数组")
    blob = s[start : end + 1]
    for cand in (blob, _repair_json_text(blob)):
        try:
            val = json.loads(cand)
            if isinstance(val, list):
                return val
        except json.JSONDecodeError:
            continue
    objs = _extract_json_objects(blob)
    if objs:
        return objs
    raise ValueError("模型输出 JSON 无法解析，请重试或调低「最多生成」条数")


def _truncate(s: str, max_chars: int) -> str:
    s = (s or "").strip()
    if max_chars <= 0 or len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _rule_snapshot(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": str(rule.get("rule_id") or ""),
        "name": str(rule.get("name") or ""),
        "desc": str(rule.get("desc") or ""),
        "level": str(rule.get("level") or ""),
        "requirements": str(rule.get("requirements") or ""),
        "source": str(rule.get("source") or ""),
    }


def _rule_for_llm(rule: dict[str, Any]) -> dict[str, Any]:
    rec = rule.get("recommended_algorithms")
    algo_names = [str(x).strip() for x in rec if str(x).strip()] if isinstance(rec, list) else []
    return {
        "rule_id": str(rule.get("rule_id") or ""),
        "name": _truncate(str(rule.get("name") or ""), 120),
        "recommended_algorithm_names": algo_names[:8],
    }


def _algorithm_for_llm(algo: dict[str, Any]) -> dict[str, Any]:
    return {
        "algorithm_id": str(algo.get("algorithm_id") or ""),
        "name": _truncate(str(algo.get("name") or ""), 80),
    }


def _algorithm_snapshot(algo: dict[str, Any]) -> dict[str, Any]:
    return {
        "algorithm_id": str(algo.get("algorithm_id") or ""),
        "name": str(algo.get("name") or ""),
        "desc": str(algo.get("desc") or ""),
        "link": str(algo.get("link") or ""),
        "health": str(algo.get("health") or "unknown"),
    }


def _equipment_for_llm(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for eq in items:
        eid = str(eq.get("id") or eq.get("equipment_id") or "").strip()
        if not eid:
            continue
        out.append(
            {
                "equipment_id": eid,
                "name": _truncate(str(eq.get("name") or eid), 64),
                "kind": str(eq.get("kind") or "")[:32],
                "region_id": str(eq.get("region_id") or "")[:64],
            }
        )
    return out


def _algorithms_for_rules(
    rules: list[dict[str, Any]],
    algo_items: list[dict[str, Any]],
    *,
    limit: int = 32,
) -> list[dict[str, Any]]:
    hints: set[str] = set()
    for rule in rules:
        for raw in rule.get("recommended_algorithms") or []:
            s = str(raw).strip().lower()
            if s:
                hints.add(s)
        hints.add(str(rule.get("name") or "").strip().lower())

    if not hints:
        return algo_items[: min(limit, len(algo_items))]

    matched: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_algo(algo: dict[str, Any]) -> None:
        aid = str(algo.get("algorithm_id") or "").strip()
        if not aid or aid in seen:
            return
        seen.add(aid)
        matched.append(algo)

    for algo in algo_items:
        aid = str(algo.get("algorithm_id") or "").strip().lower()
        aname = str(algo.get("name") or "").strip().lower()
        if aid in hints or aname in hints:
            add_algo(algo)
            continue
        if any(h in aid or h in aname or aid in h or aname in h for h in hints if len(h) >= 3):
            add_algo(algo)

    if len(matched) < min(8, limit):
        for algo in algo_items:
            add_algo(algo)
            if len(matched) >= limit:
                break
    return matched[:limit]


def _equipment_for_topic(
    equipment: list[dict[str, Any]],
    *,
    topic: str,
    rules: list[dict[str, Any]],
    limit: int = 36,
) -> list[dict[str, Any]]:
    tokens = _tokenize(topic)
    for rule in rules:
        tokens |= _tokenize(str(rule.get("name") or ""))
        tokens |= _tokenize(str(rule.get("desc") or ""))

    scored: list[tuple[float, dict[str, Any]]] = []
    for eq in equipment:
        blob = " ".join(
            [
                str(eq.get("name") or ""),
                str(eq.get("kind") or ""),
                str(eq.get("region_id") or ""),
            ]
        ).lower()
        score = sum(1 for t in tokens if t in blob)
        scored.append((score, eq))
    scored.sort(key=lambda x: (-x[0], str(x[1].get("name") or "")))
    picked = [e for s, e in scored if s > 0][:limit]
    if not picked:
        picked = [e for _, e in scored[:limit]]
    return picked


def _resolve_ids_from_llm(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for el in raw:
        sid = str(el).strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append(sid)
    return out


def _expand_rule_set(rule_ids: list[str], rule_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [_rule_snapshot(rule_index[rid]) for rid in rule_ids if rid in rule_index]


def _expand_algorithm_set(
    algorithm_ids: list[str], algo_index: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    return [_algorithm_snapshot(algo_index[aid]) for aid in algorithm_ids if aid in algo_index]


def _normalize_equipment(raw: Any, *, allowed_ids: set[str] | None = None) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for el in raw:
        if not isinstance(el, dict):
            continue
        eid = str(el.get("equipment_id") or "").strip()
        if allowed_ids is not None:
            if not eid or eid not in allowed_ids:
                continue
        if not eid:
            eid = f"eq_{uuid.uuid4().hex[:10]}"
        nm = str(el.get("name") or "").strip() or eid
        row: dict[str, Any] = {"equipment_id": eid, "name": nm}
        if el.get("role"):
            row["role"] = str(el.get("role"))[:128]
        out.append(row)
    return out


def _derive_regions_from_equipment(
    equipment_set: list[dict[str, Any]],
    eq_index: dict[str, dict[str, Any]],
) -> tuple[list[str], str]:
    region_ids: list[str] = []
    for eq in equipment_set:
        eid = str(eq.get("equipment_id") or "").strip()
        full = eq_index.get(eid)
        if not full:
            continue
        rid = str(full.get("region_id") or "").strip()
        if rid and rid not in region_ids:
            region_ids.append(rid)
    primary = region_ids[0] if region_ids else ""
    return region_ids, primary


def _resolve_algorithm_ids_for_rules(
    rules: list[dict[str, Any]],
    algo_index: dict[str, dict[str, Any]],
) -> list[str]:
    by_id = {k.lower(): k for k in algo_index}
    by_name = {str(v.get("name") or "").lower(): k for k, v in algo_index.items()}
    out: list[str] = []
    seen: set[str] = set()

    def resolve_hint(hint: str) -> str | None:
        key = hint.strip().lower()
        if not key:
            return None
        if key in by_id:
            return by_id[key]
        if key in by_name:
            return by_name[key]
        for kid, full in by_id.items():
            if key in kid or kid in key:
                return full
        for n, full in by_name.items():
            if key in n or n in key:
                return full
        return None

    for rule in rules:
        for raw in rule.get("recommended_algorithms") or []:
            aid = resolve_hint(str(raw))
            if aid and aid not in seen:
                seen.add(aid)
                out.append(aid)
    if not out:
        out = list(algo_index.keys())[:3]
    return out


def _compose_works_deterministic(
    *,
    rules: list[dict[str, Any]],
    topic_text: str,
    cap: int,
    rule_index: dict[str, dict[str, Any]],
    algo_index: dict[str, dict[str, Any]],
    eq_index: dict[str, dict[str, Any]],
    allowed_equip_ids: set[str],
    platform_equipment: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """LLM 输出不可解析时的兜底：按全部规范推荐算法 + 设备打分组装一条业务。"""
    if rules:
        algo_ids = _resolve_algorithm_ids_for_rules(rules, algo_index)
    else:
        algo_ids = list(algo_index.keys())[:3]
    equip_pool = _equipment_for_llm(
        _equipment_for_topic(platform_equipment, topic=topic_text, rules=rules, limit=12)
    )
    if not equip_pool:
        return []

    rule_ids = [str(r.get("rule_id") or "") for r in rules if r.get("rule_id")]
    rule_set = _expand_rule_set(rule_ids, rule_index) if rule_ids else []
    algorithm_set = _expand_algorithm_set(algo_ids, algo_index)
    equipment_set = _normalize_equipment(
        [{"equipment_id": e["equipment_id"], "name": e["name"]} for e in equip_pool[:5]],
        allowed_ids=allowed_equip_ids,
    )
    if not algorithm_set or not equipment_set:
        return []
    if rules and not rule_set:
        return []

    if rules:
        primary = rules[0]
        title = _truncate(str(primary.get("name") or "巡检业务"), 36)
        if len(rules) > 1:
            title = _truncate(f"{title}等综合巡检", 40)
    else:
        title = _truncate(topic_text, 36) or "巡检业务"

    region_ids, primary_region = _derive_regions_from_equipment(equipment_set, eq_index)
    if not primary_region:
        return []

    work = {
        "work_id": "",
        "name": title,
        "region_id": primary_region,
        "region_ids": region_ids,
        "desc": _truncate(topic_text, 160),
        "rule_set": rule_set,
        "algorithm_set": algorithm_set,
        "equipment_set": equipment_set,
    }
    return [work][: max(1, cap)]


def _build_user_prompt(
    *,
    topic_text: str,
    cap: int,
    rid: str,
    rules_compact: list[dict[str, Any]],
    algos_compact: list[dict[str, Any]],
    equip_compact: list[dict[str, Any]],
    retry: bool = False,
) -> str:
    parts = [
        f"用户巡检诉求：{topic_text}\n",
        f"max_works={cap}。\n",
    ]
    if rid:
        parts.append(f"设备范围限定 region_id={rid!r}。\n")
    parts.append(
        "equipment_set 的 equipment_id 必须来自设备列表；region 由设备 region_id 推导。\n\n"
        f"【规范规则】\n{json.dumps(rules_compact, ensure_ascii=False)}\n\n"
        f"【算法目录】\n{json.dumps(algos_compact, ensure_ascii=False)}\n\n"
        f"【设备列表】\n{json.dumps(equip_compact, ensure_ascii=False)}\n"
    )
    if retry:
        parts.append(_RETRY_APPEND)
    return "".join(parts)


def _works_from_llm_array(
    raw_list: list[Any],
    *,
    cap: int,
    rule_index: dict[str, dict[str, Any]],
    algo_index: dict[str, dict[str, Any]],
    eq_index: dict[str, dict[str, Any]],
    allowed_equip_ids: set[str],
) -> list[dict[str, Any]]:
    works: list[dict[str, Any]] = []
    for el in raw_list[:cap]:
        if not isinstance(el, dict):
            continue
        name = str(el.get("name") or "").strip()
        desc = str(el.get("desc") or "").strip()
        rule_ids = _resolve_ids_from_llm(el.get("rule_ids"))
        algorithm_ids = _resolve_ids_from_llm(el.get("algorithm_ids"))
        if not name or not rule_ids or not algorithm_ids:
            continue
        rule_set = _expand_rule_set(rule_ids, rule_index)
        algorithm_set = _expand_algorithm_set(algorithm_ids, algo_index)
        if not rule_set or not algorithm_set:
            continue
        equipment_set = _normalize_equipment(el.get("equipment_set"), allowed_ids=allowed_equip_ids)
        if not equipment_set:
            continue
        region_ids, primary_region = _derive_regions_from_equipment(equipment_set, eq_index)
        if not primary_region:
            continue
        works.append(
            {
                "work_id": "",
                "name": name[:512],
                "region_id": primary_region,
                "region_ids": region_ids,
                "desc": desc[:16000],
                "rule_set": rule_set,
                "algorithm_set": algorithm_set,
                "equipment_set": equipment_set,
            }
        )
    return works


def _inspection_work_chat_model(model_name: str | None) -> str | None:
    if model_name and str(model_name).strip():
        return str(model_name).strip()
    return env_first("SIA_INSPECTION_WORK_CHAT_MODEL") or "deepseek-ai/DeepSeek-V4-Flash"


def _parse_json_object(content: str) -> dict[str, Any]:
    s = (content or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.IGNORECASE)
    if m:
        s = m.group(1).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        objs = _extract_json_objects(s)
        if objs:
            return objs[0]
        raise ValueError("模型输出中未找到 JSON 对象")
    blob = s[start : end + 1]
    for cand in (blob, _repair_json_text(blob)):
        try:
            val = json.loads(cand)
            if isinstance(val, dict):
                return val
        except json.JSONDecodeError:
            continue
    objs = _extract_json_objects(blob)
    if objs:
        return objs[0]
    raise ValueError("模型输出 JSON 对象无法解析")


def _recommend_rule_catalog(
    mm: ModelManager,
    *,
    rule: dict[str, Any],
    catalog: EntityCatalog,
    algo_index: dict[str, dict[str, Any]],
    chat_model: str | None,
) -> dict[str, Any]:
    devices = catalog.equipment
    user_payload = {
        "rule": {
            "rule_id": str(rule.get("rule_id") or ""),
            "name": str(rule.get("name") or ""),
            "desc": str(rule.get("desc") or ""),
            "requirements": _truncate(str(rule.get("requirements") or ""), 800),
        },
        **catalog_llm_payload(catalog),
    }
    req = ChatRequest(
        messages=[
            LlmChatMessage(role="system", content=_RULE_MATCH_PROMPT, metadata={}),
            LlmChatMessage(
                role="user",
                content=json.dumps(user_payload, ensure_ascii=False),
                metadata={},
            ),
        ],
        metadata={"request_id": uuid.uuid4().hex, "purpose": "inspection_work_rule_match"},
        temperature=0.1,
        max_output_tokens=1536,
    )
    try:
        resp = mm.call_chat(req, model_name=chat_model)
        data = _parse_json_object(resp.content or "")
    except (LLMError, ValueError, json.JSONDecodeError):
        data = {}

    region_ids = _resolve_ids_from_llm(data.get("region_ids"))
    algorithm_ids = _resolve_ids_from_llm(data.get("algorithm_ids"))
    equipment_ids = _resolve_ids_from_llm(data.get("equipment_ids"))

    if not algorithm_ids:
        algorithm_ids = _resolve_algorithm_ids_for_rules([rule], algo_index)

    if not region_ids and equipment_ids:
        eq_index = {str(e["id"]): e for e in devices}
        for eid in equipment_ids:
            eq = eq_index.get(eid)
            if eq:
                rid = str(eq.get("region_id") or "").strip()
                if rid and rid not in region_ids:
                    region_ids.append(rid)

    return {
        "region_ids": region_ids,
        "algorithm_ids": algorithm_ids,
        "equipment_ids": equipment_ids,
        "region_reasoning": str(data.get("region_reasoning") or "").strip(),
        "algorithm_reasoning": str(data.get("algorithm_reasoning") or "").strip(),
    }


def _recommend_work_catalog(
    mm: ModelManager,
    *,
    rules: list[dict[str, Any]],
    catalog: EntityCatalog,
    topic_text: str,
    algo_index: dict[str, dict[str, Any]],
    chat_model: str | None,
) -> dict[str, Any]:
    """综合 Top-K 规范与合并目录，一次 LLM 推荐一条巡检业务所需区域/算法/设备。"""
    user_payload = {
        "topic": topic_text,
        "rules": [
            {
                "rule_id": str(rule.get("rule_id") or ""),
                "name": str(rule.get("name") or ""),
                "desc": str(rule.get("desc") or ""),
                "requirements": _truncate(str(rule.get("requirements") or ""), 800),
            }
            for rule in rules
        ],
        **catalog_llm_payload(catalog),
    }
    req = ChatRequest(
        messages=[
            LlmChatMessage(role="system", content=_WORK_MATCH_PROMPT, metadata={}),
            LlmChatMessage(
                role="user",
                content=json.dumps(user_payload, ensure_ascii=False),
                metadata={},
            ),
        ],
        metadata={"request_id": uuid.uuid4().hex, "purpose": "inspection_work_catalog_match"},
        temperature=0.1,
        max_output_tokens=2048,
    )
    try:
        resp = mm.call_chat(req, model_name=chat_model)
        data = _parse_json_object(resp.content or "")
    except (LLMError, ValueError, json.JSONDecodeError):
        data = {}

    region_ids = _resolve_ids_from_llm(data.get("region_ids"))
    algorithm_ids = _resolve_ids_from_llm(data.get("algorithm_ids"))
    equipment_ids = _resolve_ids_from_llm(data.get("equipment_ids"))

    if not algorithm_ids:
        algorithm_ids = _resolve_algorithm_ids_for_rules(rules, algo_index)

    if not region_ids and equipment_ids:
        eq_index = {str(e["id"]): e for e in catalog.equipment}
        for eid in equipment_ids:
            eq = eq_index.get(eid)
            if eq:
                rid = str(eq.get("region_id") or "").strip()
                if rid and rid not in region_ids:
                    region_ids.append(rid)

    return {
        "name": str(data.get("name") or "").strip(),
        "desc": str(data.get("desc") or "").strip(),
        "region_ids": region_ids,
        "algorithm_ids": algorithm_ids,
        "equipment_ids": equipment_ids,
        "region_reasoning": str(data.get("region_reasoning") or "").strip(),
        "algorithm_reasoning": str(data.get("algorithm_reasoning") or "").strip(),
    }


def _build_single_work_from_recommendation(
    *,
    rules: list[dict[str, Any]],
    rec: dict[str, Any],
    catalog: EntityCatalog,
    topic_text: str,
    rule_index: dict[str, dict[str, Any]],
    eq_index: dict[str, dict[str, Any]],
    algo_index: dict[str, dict[str, Any]],
    allowed_equip_ids: set[str],
    intent_pins: IntentPins | None = None,
) -> dict[str, Any] | None:
    rule_ids = [str(r.get("rule_id") or "").strip() for r in rules if str(r.get("rule_id") or "").strip()]
    rule_set = _expand_rule_set(rule_ids, rule_index)
    rules_empty = not rules
    if not rule_set and not rules_empty:
        return None

    algorithm_ids = [aid for aid in rec.get("algorithm_ids") or [] if aid in algo_index]
    if intent_pins:
        for aid in intent_pins.algorithm_ids:
            if aid in algo_index and aid not in algorithm_ids:
                algorithm_ids.append(aid)
    algorithm_set = _expand_algorithm_set(algorithm_ids, algo_index)
    if not algorithm_set:
        if rules:
            algorithm_ids = _resolve_algorithm_ids_for_rules(rules, algo_index)
            algorithm_set = _expand_algorithm_set(algorithm_ids, algo_index)
        elif catalog.algorithms:
            algorithm_ids = [
                str(a.get("algorithm_id") or "").strip()
                for a in catalog.algorithms
                if str(a.get("algorithm_id") or "").strip()
            ][:5]
            algorithm_set = _expand_algorithm_set(algorithm_ids, algo_index)
    if not algorithm_set:
        return None

    region_ids = [str(x).strip() for x in rec.get("region_ids") or [] if str(x).strip()]
    if intent_pins:
        for rid in intent_pins.region_ids:
            if rid and rid not in region_ids:
                region_ids.append(rid)
    scoped_devices = filter_devices_for_regions(catalog.equipment, region_ids, limit=36)
    picked_ids = [eid for eid in rec.get("equipment_ids") or [] if eid in eq_index]
    if intent_pins:
        for eid in intent_pins.equipment_ids:
            if eid in eq_index and eid not in picked_ids:
                picked_ids.append(eid)
    if not picked_ids:
        tokens = _tokenize(topic_text)
        for rule in rules:
            tokens |= _tokenize(_rule_blob(rule))
        scored: list[tuple[float, dict[str, Any]]] = []
        for eq in scoped_devices:
            blob = f"{eq.get('name') or ''} {eq.get('description') or ''} {eq.get('kind') or ''}"
            scored.append((_score_text_match(blob, tokens), eq))
        scored.sort(key=lambda x: (-x[0], str(x[1].get("name") or "")))
        picked_ids = [str(e["id"]) for _, e in scored[:5] if str(e.get("id") or "")]

    equipment_set = _normalize_equipment(
        [{"equipment_id": eid, "name": str(eq_index[eid].get("name") or eid)} for eid in picked_ids],
        allowed_ids=allowed_equip_ids,
    )
    if not equipment_set:
        return None

    derived_region_ids, primary_region = _derive_regions_from_equipment(equipment_set, eq_index)
    if rec.get("region_ids"):
        region_ids = [rid for rid in rec["region_ids"] if rid]
        primary_region = region_ids[0] if region_ids else primary_region
    elif derived_region_ids:
        region_ids = derived_region_ids

    name = str(rec.get("name") or "").strip()
    if not name:
        if rules:
            primary = rules[0]
            name = _truncate(str(primary.get("name") or "巡检业务"), 36)
            if len(rules) > 1:
                name = _truncate(f"{name}等综合巡检", 40)
        else:
            name = _truncate(topic_text, 36) or "巡检业务"

    desc_parts = [rec.get("desc"), rec.get("region_reasoning"), rec.get("algorithm_reasoning")]
    desc = " ".join(str(x).strip() for x in desc_parts if str(x or "").strip())
    if not desc:
        desc = _truncate(topic_text, 160)

    return {
        "work_id": "",
        "name": name[:512],
        "region_id": primary_region,
        "region_ids": region_ids or ([primary_region] if primary_region else []),
        "desc": desc[:16000],
        "rule_set": rule_set,
        "algorithm_set": algorithm_set,
        "equipment_set": equipment_set,
    }


def _build_works_from_rule_recommendations(
    *,
    rules: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    catalog: EntityCatalog,
    topic_text: str,
    eq_index: dict[str, dict[str, Any]],
    algo_index: dict[str, dict[str, Any]],
    allowed_equip_ids: set[str],
) -> list[dict[str, Any]]:
    works: list[dict[str, Any]] = []

    for rule, rec in zip(rules, recommendations):
        rule_id = str(rule.get("rule_id") or "").strip()
        if not rule_id:
            continue
        rule_set = _expand_rule_set([rule_id], {rule_id: dict(rule)})
        if not rule_set:
            continue

        algorithm_ids = [aid for aid in rec.get("algorithm_ids") or [] if aid in algo_index]
        algorithm_set = _expand_algorithm_set(algorithm_ids, algo_index)
        if not algorithm_set:
            algorithm_ids = _resolve_algorithm_ids_for_rules([rule], algo_index)
            algorithm_set = _expand_algorithm_set(algorithm_ids, algo_index)
        if not algorithm_set:
            continue

        region_ids = [str(x).strip() for x in rec.get("region_ids") or [] if str(x).strip()]
        scoped_devices = filter_devices_for_regions(catalog.equipment, region_ids, limit=24)
        picked_ids = [eid for eid in rec.get("equipment_ids") or [] if eid in eq_index]
        if not picked_ids:
            tokens = _tokenize(topic_text) | _tokenize(_rule_blob(rule))
            scored: list[tuple[float, dict[str, Any]]] = []
            for eq in scoped_devices:
                blob = f"{eq.get('name') or ''} {eq.get('description') or ''} {eq.get('kind') or ''}"
                scored.append((_score_text_match(blob, tokens), eq))
            scored.sort(key=lambda x: (-x[0], str(x[1].get("name") or "")))
            picked_ids = [str(e["id"]) for _, e in scored[:3] if str(e.get("id") or "")]

        equipment_set = _normalize_equipment(
            [{"equipment_id": eid, "name": str(eq_index[eid].get("name") or eid)} for eid in picked_ids],
            allowed_ids=allowed_equip_ids,
        )
        if not equipment_set:
            continue

        region_ids, primary_region = _derive_regions_from_equipment(equipment_set, eq_index)
        if region_ids and not rec.get("region_ids"):
            pass
        elif rec.get("region_ids"):
            region_ids = [rid for rid in rec["region_ids"] if rid]
            primary_region = region_ids[0] if region_ids else primary_region

        desc_parts = [rec.get("region_reasoning"), rec.get("algorithm_reasoning")]
        desc = " ".join(str(x).strip() for x in desc_parts if str(x or "").strip())
        if not desc:
            desc = _truncate(topic_text, 160)

        works.append(
            {
                "work_id": "",
                "name": _truncate(str(rule.get("name") or "巡检业务"), 40),
                "region_id": primary_region,
                "region_ids": region_ids or ([primary_region] if primary_region else []),
                "desc": desc[:16000],
                "rule_set": rule_set,
                "algorithm_set": algorithm_set,
                "equipment_set": equipment_set,
            }
        )
    return works


def _rule_blob(rule: dict[str, Any]) -> str:
    return " ".join(
        [
            str(rule.get("name") or ""),
            str(rule.get("desc") or ""),
            str(rule.get("requirements") or ""),
        ]
    )


def _score_text_match(text: str, tokens: set[str]) -> float:
    if not tokens:
        return 0.0
    hay = (text or "").lower()
    hits = sum(1 for t in tokens if t in hay)
    return hits / max(len(tokens), 1)


def _ensure_catalog_baseline(
    catalog: EntityCatalog,
    *,
    all_regions: list[dict[str, Any]],
    algo_items: list[dict[str, Any]],
    platform_equipment: list[dict[str, Any]],
) -> EntityCatalog:
    regions = list(catalog.regions)
    algorithms = list(catalog.algorithms)
    equipment = list(catalog.equipment)

    if not regions:
        regions = [{"id": r["id"], "name": r["name"], "desc": r.get("desc") or ""} for r in all_regions[:24]]
    if not algorithms:
        algorithms = [_algorithm_for_llm(a) for a in algo_items[:32]]
    if not equipment:
        equipment = _equipment_for_llm(platform_equipment[:36])
    return EntityCatalog(regions=regions, algorithms=algorithms, equipment=equipment)


def _catalog_names(rows: list[dict[str, Any]], key: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        name = str(row.get(key) or row.get("name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _trace_entity_names(
    *,
    from_intent: EntityCatalog,
    intent_pins: IntentPins | None,
    region_by_id: dict[str, dict[str, Any]],
    algo_index: dict[str, dict[str, Any]],
    eq_index: dict[str, dict[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    """意图路命中实体名称（pins 优先，再合并 catalog 关键字命中）。"""
    regions: list[str] = []
    algos: list[str] = []
    devices: list[str] = []
    seen_r: set[str] = set()
    seen_a: set[str] = set()
    seen_d: set[str] = set()

    def add_name(bucket: list[str], seen: set[str], name: str) -> None:
        n = (name or "").strip()
        if not n or n in seen:
            return
        seen.add(n)
        bucket.append(n)

    if intent_pins:
        for rid in intent_pins.region_ids:
            reg = region_by_id.get(rid)
            if reg:
                add_name(regions, seen_r, str(reg.get("name") or rid))
        for aid in intent_pins.algorithm_ids:
            algo = algo_index.get(aid)
            if algo:
                add_name(algos, seen_a, str(algo.get("name") or aid))
        for eid in intent_pins.equipment_ids:
            eq = eq_index.get(eid)
            if eq:
                add_name(devices, seen_d, str(eq.get("name") or eid))

    for row in from_intent.regions:
        add_name(regions, seen_r, str(row.get("name") or ""))
    for row in from_intent.algorithms:
        add_name(algos, seen_a, str(row.get("name") or ""))
    for row in from_intent.equipment:
        add_name(devices, seen_d, str(row.get("name") or ""))

    return regions, algos, devices


def _build_retrieval_trace(
    *,
    rule_result: RuleRetrievalResult,
    from_intent: EntityCatalog,
    intent_pins: IntentPins | None = None,
    region_by_id: dict[str, dict[str, Any]] | None = None,
    algo_index: dict[str, dict[str, Any]] | None = None,
    eq_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    region_by_id = region_by_id or {}
    algo_index = algo_index or {}
    eq_index = eq_index or {}
    regions, algos, devices = _trace_entity_names(
        from_intent=from_intent,
        intent_pins=intent_pins,
        region_by_id=region_by_id,
        algo_index=algo_index,
        eq_index=eq_index,
    )
    trace: dict[str, Any] = {
        "rule_path": rule_result.path,
        "rules": [rule_hit_to_trace(h, index=i + 1) for i, h in enumerate(rule_result.hits)],
        "algorithms": algos,
        "regions": regions,
        "devices": devices,
    }
    if not rule_result.hits:
        trace["rules_miss_message"] = RULE_MISS_TRACE_MESSAGE
        trace["rule_near_misses"] = [
            rule_hit_to_trace(h, index=i + 1) for i, h in enumerate(rule_result.near_misses)
        ]
    return trace


def generate_inspection_works(
    *,
    spec_svc: SpecificationService,
    mm: ModelManager,
    region_id: str | None = None,
    model_name: str | None = None,
    max_works: int = 1,
    topic: str | None = None,
    algorithm_limit: int = 40,
    rule_desc_max_chars: int = 400,
    rule_requirements_max_chars: int = 1200,
    algorithm_desc_max_chars: int = 400,
    rule_top_k: int | None = None,
) -> dict[str, Any]:
    """向量检索（动态 K）+ 意图识别两路合并目录，综合生成一条巡检业务。"""
    del rule_desc_max_chars, rule_requirements_max_chars, algorithm_desc_max_chars, max_works

    topic_text = (topic or "").strip()
    if not topic_text:
        raise ValueError("请描述巡检目的、关注规范或设备范围")

    rid = (region_id or "").strip()
    top_k = rule_top_k if rule_top_k is not None else RULE_RETRIEVAL_TOP_K
    chat_model = _inspection_work_chat_model(model_name)

    rule_result = retrieve_published_rules_by_topic(spec_svc, topic=topic_text, max_k=top_k)
    rules = rule_result.rules

    eq_svc = EquipmentService()
    eq_svc.ensure_ready()
    if rid:
        platform_equipment, _ = eq_svc.list_equipment(region_id=rid, limit=200, offset=0)
        if not platform_equipment:
            raise ValueError(f"区域 {rid} 下暂无设备，请先在设备管理中登记")
    else:
        platform_equipment, _ = eq_svc.list_equipment(limit=500, offset=0)
        if not platform_equipment:
            raise ValueError("平台暂无设备，请先在设备管理中登记")

    eq_index = {str(e.get("id") or "").strip(): dict(e) for e in platform_equipment}
    eq_index.pop("", None)
    allowed_equip_ids = set(eq_index.keys())

    algo_svc = AlgorithmService()
    algo_svc.ensure_ready()
    alim = max(16, min(int(algorithm_limit), 80))
    algo_items, _ = algo_svc.list_algorithms(limit=alim, offset=0)

    algo_index = {str(a["algorithm_id"]): dict(a) for a in algo_items}

    region_svc = RegionMetaService()
    region_svc.ensure_ready()
    all_regions = region_svc.list_regions()

    intent = extract_user_intent(mm, topic=topic_text, model_name=chat_model)
    intent_pins = resolve_intent_entities(
        topic=topic_text,
        intent=intent,
        all_regions=all_regions,
        algo_svc=algo_svc,
        eq_svc=eq_svc,
    )
    from_rules = (
        collect_from_rules(
            rules,
            all_regions=all_regions,
            algo_svc=algo_svc,
            eq_svc=eq_svc,
        )
        if rules
        else EntityCatalog()
    )
    from_intent = collect_from_intent(
        intent,
        topic=topic_text,
        all_regions=all_regions,
        algo_svc=algo_svc,
        eq_svc=eq_svc,
    )
    region_by_id = {str(r["id"]): dict(r) for r in all_regions}
    retrieval_trace = _build_retrieval_trace(
        rule_result=rule_result,
        from_intent=from_intent,
        intent_pins=intent_pins,
        region_by_id=region_by_id,
        algo_index=algo_index,
        eq_index=eq_index,
    )
    merged = _ensure_catalog_baseline(
        merge_catalogs(from_rules, from_intent),
        all_regions=all_regions,
        algo_items=algo_items,
        platform_equipment=platform_equipment,
    )

    rule_index = {str(r["rule_id"]): dict(r) for r in rules}

    try:
        rec = _recommend_work_catalog(
            mm,
            rules=rules,
            catalog=merged,
            topic_text=topic_text,
            algo_index=algo_index,
            chat_model=chat_model,
        )
    except LLMError as e:
        raise RuntimeError(f"巡检业务编组 LLM 调用失败: {e.code} {e.message}") from e

    work = _build_single_work_from_recommendation(
        rules=rules,
        rec=rec,
        catalog=merged,
        topic_text=topic_text,
        rule_index=rule_index,
        eq_index=eq_index,
        algo_index=algo_index,
        allowed_equip_ids=allowed_equip_ids,
        intent_pins=intent_pins,
    )
    if work:
        return {"works": [work], "retrieval_trace": retrieval_trace}

    works = _compose_works_deterministic(
        rules=rules,
        topic_text=topic_text,
        cap=1,
        rule_index=rule_index,
        algo_index=algo_index,
        eq_index=eq_index,
        allowed_equip_ids=allowed_equip_ids,
        platform_equipment=platform_equipment,
    )
    if works:
        return {"works": works[:1], "retrieval_trace": retrieval_trace}

    raise ValueError("未能生成有效巡检业务；请确认规范、算法与设备数据已入库后重试")
