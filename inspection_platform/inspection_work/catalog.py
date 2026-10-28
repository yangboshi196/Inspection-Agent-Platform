"""规范检索与意图识别两路目录收集、合并去重。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from inspection_platform.algorithm.service import AlgorithmService
from inspection_platform.document.region_meta import RegionMetaService
from inspection_platform.equipment.service import EquipmentService
from inspection_platform.inspection_work.entity_resolve import (
    collect_catalog_search_terms,
    resolve_algorithms,
    resolve_equipment,
    resolve_regions,
)


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[\w\u4e00-\u9fff]{2,}", (text or "").lower()))


def _rule_blob(rule: dict[str, Any]) -> str:
    return " ".join(
        [
            str(rule.get("name") or ""),
            str(rule.get("desc") or ""),
            str(rule.get("requirements") or ""),
        ]
    )


def _score_text_match(blob: str, tokens: set[str]) -> float:
    if not tokens:
        return 0.0
    hay = blob.lower()
    hits = sum(1 for t in tokens if t in hay)
    return hits / max(len(tokens), 1)


@dataclass
class EntityCatalog:
    regions: list[dict[str, Any]] = field(default_factory=list)
    algorithms: list[dict[str, Any]] = field(default_factory=list)
    equipment: list[dict[str, Any]] = field(default_factory=list)

    def merge(self, other: EntityCatalog) -> EntityCatalog:
        return merge_catalogs(self, other)


def _region_for_llm(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "name": str(row.get("name") or ""),
        "desc": str(row.get("desc") or ""),
    }


def _algorithm_for_llm(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "algorithm_id": str(row.get("algorithm_id") or ""),
        "name": str(row.get("name") or ""),
        "desc": str(row.get("desc") or ""),
        "health": str(row.get("health") or "unknown"),
    }


def _equipment_for_llm(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "name": str(row.get("name") or ""),
        "description": str(row.get("description") or ""),
        "kind": str(row.get("kind") or ""),
        "region_id": str(row.get("region_id") or ""),
    }


def merge_catalogs(*parts: EntityCatalog) -> EntityCatalog:
    regions: dict[str, dict[str, Any]] = {}
    algorithms: dict[str, dict[str, Any]] = {}
    equipment: dict[str, dict[str, Any]] = {}

    for part in parts:
        for row in part.regions:
            rid = str(row.get("id") or "").strip()
            if rid:
                regions[rid] = row
        for row in part.algorithms:
            aid = str(row.get("algorithm_id") or "").strip()
            if aid:
                algorithms[aid] = row
        for row in part.equipment:
            eid = str(row.get("id") or "").strip()
            if eid:
                equipment[eid] = row

    return EntityCatalog(
        regions=list(regions.values()),
        algorithms=list(algorithms.values()),
        equipment=list(equipment.values()),
    )


def _resolve_algorithm_hints(
    hints: list[str],
    algo_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {k.lower(): v for k, v in algo_index.items()}
    by_name = {str(v.get("name") or "").lower(): v for v in algo_index.values()}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(algo: dict[str, Any]) -> None:
        aid = str(algo.get("algorithm_id") or "").strip()
        if aid and aid not in seen:
            seen.add(aid)
            out.append(algo)

    for raw in hints:
        key = str(raw or "").strip().lower()
        if not key:
            continue
        if key in by_id:
            add(by_id[key])
            continue
        if key in by_name:
            add(by_name[key])
            continue
        for kid, algo in by_id.items():
            if key in kid or kid in key or key in str(algo.get("name") or "").lower():
                add(algo)
                break
    return out


def collect_from_rules(
    rules: list[dict[str, Any]],
    *,
    all_regions: list[dict[str, Any]],
    algo_svc: AlgorithmService,
    eq_svc: EquipmentService,
    equip_per_rule_limit: int = 120,
) -> EntityCatalog:
    """从 MySQL 规范绑定字段读取区域、算法、设备（设备优先读绑定 id，否则取绑定区域内设备）。"""
    region_by_id = {str(r["id"]): dict(r) for r in all_regions}
    regions_out: dict[str, dict[str, Any]] = {}
    algos_out: dict[str, dict[str, Any]] = {}
    equip_out: dict[str, dict[str, Any]] = {}

    for rule in rules:
        bound_region_ids: list[str] = []

        for rid in rule.get("recommended_regions") or []:
            sid = str(rid).strip()
            if not sid:
                continue
            reg = region_by_id.get(sid)
            if reg:
                regions_out[sid] = reg
                bound_region_ids.append(sid)

        for raw in rule.get("recommended_algorithms") or []:
            aid = str(raw).strip()
            if not aid:
                continue
            row = algo_svc.get(aid)
            if row:
                algos_out[aid] = row
                continue
            rows, _ = algo_svc.list_algorithms(q=aid, limit=4, offset=0)
            for row in rows:
                algos_out[str(row["algorithm_id"])] = row

        bound_equip_ids: list[str] = []
        for eid in rule.get("recommended_equipment") or []:
            sid = str(eid).strip()
            if not sid:
                continue
            row = eq_svc.get(sid)
            if row:
                equip_out[sid] = row
                bound_equip_ids.append(sid)

        if not bound_equip_ids and bound_region_ids:
            eq_rows, _ = eq_svc.list_equipment(
                region_ids=bound_region_ids,
                limit=equip_per_rule_limit,
                offset=0,
            )
            for eq in eq_rows:
                equip_out[str(eq["id"])] = eq

    return EntityCatalog(
        regions=[_region_for_llm(regions_out[k]) for k in sorted(regions_out.keys())],
        algorithms=[_algorithm_for_llm(algos_out[k]) for k in sorted(algos_out.keys())],
        equipment=[_equipment_for_llm(equip_out[k]) for k in sorted(equip_out.keys())],
    )


def collect_from_intent(
    intent: dict[str, Any],
    *,
    topic: str = "",
    all_regions: list[dict[str, Any]],
    algo_svc: AlgorithmService,
    eq_svc: EquipmentService,
) -> EntityCatalog:
    regions_out: dict[str, dict[str, Any]] = {}
    algos_out: dict[str, dict[str, Any]] = {}
    equip_out: dict[str, dict[str, Any]] = {}

    region_by_id = {str(r["id"]): r for r in all_regions}
    region_by_name = {str(r.get("name") or "").lower(): r for r in all_regions}

    # 1) LLM 意图给出的 id / 名称（精确路径）
    for el in intent.get("regions") or []:
        if not isinstance(el, dict):
            continue
        rid = str(el.get("id") or "").strip()
        name = str(el.get("name") or "").strip().lower()
        if rid and rid in region_by_id:
            regions_out[rid] = region_by_id[rid]
        elif name and name in region_by_name:
            reg = region_by_name[name]
            regions_out[str(reg["id"])] = reg
        elif name:
            for reg in all_regions:
                rn = str(reg.get("name") or "").lower()
                if name in rn or rn in name:
                    regions_out[str(reg["id"])] = reg
                    break

    for el in intent.get("algorithms") or []:
        if not isinstance(el, dict):
            continue
        aid = str(el.get("id") or "").strip()
        name = str(el.get("name") or "").strip()
        if aid:
            row = algo_svc.get(aid)
            if row:
                algos_out[aid] = row
        if name and not aid:
            rows, _ = algo_svc.list_algorithms(q=name, limit=8, offset=0)
            for row in rows:
                algos_out[str(row["algorithm_id"])] = row

    for el in intent.get("devices") or []:
        if not isinstance(el, dict):
            continue
        eid = str(el.get("id") or "").strip()
        name = str(el.get("name") or "").strip()
        if eid:
            row = eq_svc.get(eid)
            if row:
                equip_out[eid] = row
        if name and not eid:
            rows, _ = eq_svc.list_equipment(q=name, limit=8, offset=0)
            for row in rows:
                equip_out[str(row["id"])] = row

    # 2) 关键字拆解 + 别名扩展检索（意图路增强）
    search_terms = collect_catalog_search_terms(topic, intent)
    for reg in resolve_regions(all_regions, search_terms)[0]:
        rid = str(reg.get("id") or "").strip()
        if rid:
            regions_out[rid] = reg
    for algo in resolve_algorithms(algo_svc, search_terms)[0]:
        aid = str(algo.get("algorithm_id") or "").strip()
        if aid:
            algos_out[aid] = algo
    for eq in resolve_equipment(eq_svc, search_terms)[0]:
        eid = str(eq.get("id") or "").strip()
        if eid:
            equip_out[eid] = eq

    return EntityCatalog(
        regions=[_region_for_llm(regions_out[k]) for k in sorted(regions_out.keys())],
        algorithms=[_algorithm_for_llm(algos_out[k]) for k in sorted(algos_out.keys())],
        equipment=[_equipment_for_llm(equip_out[k]) for k in sorted(equip_out.keys())],
    )


def catalog_llm_payload(catalog: EntityCatalog) -> dict[str, Any]:
    return {
        "regions": catalog.regions,
        "algorithms": catalog.algorithms,
        "devices": catalog.equipment,
    }


def filter_devices_for_regions(
    equipment: list[dict[str, Any]],
    region_ids: list[str],
    *,
    limit: int = 24,
) -> list[dict[str, Any]]:
    if not region_ids:
        return equipment[:limit]
    allow = {str(x).strip() for x in region_ids if str(x).strip()}
    matched = [e for e in equipment if str(e.get("region_id") or "") in allow]
    return (matched or equipment)[:limit]
