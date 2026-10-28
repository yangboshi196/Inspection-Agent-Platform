"""巡检业务创建/更新时的统一校验。"""

from __future__ import annotations

from typing import Any

from inspection_platform.algorithm.service import AlgorithmService
from inspection_platform.inspection_work.service import InspectionWorkService
from inspection_platform.specification.service import SpecificationService


def validate_work_payload(
    *,
    rule_set: list[dict[str, Any]],
    algorithm_set: list[dict[str, Any]],
    equipment_set: list[dict[str, Any]],
    spec_svc: SpecificationService,
    work_svc: InspectionWorkService,
    require_online_rules: bool = True,
    explicit_region_ids: list[str] | None = None,
) -> tuple[list[str], str]:
    if not equipment_set:
        raise ValueError("equipment_set 不能为空；巡检业务须关联至少一台设备")
    rule_ids = [str(r.get("rule_id") or "") for r in rule_set if str(r.get("rule_id") or "").strip()]
    if not rule_ids:
        raise ValueError("rule_set 须包含至少一条规范 rule_id")
    algo_ids = [
        str(a.get("algorithm_id") or "")
        for a in algorithm_set
        if str(a.get("algorithm_id") or "").strip()
    ]
    if not algo_ids:
        raise ValueError("algorithm_set 须包含至少一条 algorithm_id")
    algo_svc = AlgorithmService()
    algo_svc.ensure_ready()
    seen_algo: set[str] = set()
    for aid in algo_ids:
        if aid in seen_algo:
            continue
        seen_algo.add(aid)
        if not algo_svc.get(aid):
            raise ValueError(f"算法 {aid} 不存在")
    equip_ids = [str(e.get("equipment_id") or "") for e in equipment_set]
    work_svc.validate_equipment_ids(equip_ids)
    if require_online_rules:
        spec_svc.validate_rules_for_inspection(rule_ids)
    if explicit_region_ids is not None:
        region_ids = [str(x).strip() for x in explicit_region_ids if str(x).strip()]
        if not region_ids:
            raise ValueError("region_ids 不能为空；请至少选择一个作用区域")
        primary_region = region_ids[0]
        return region_ids, primary_region
    region_ids = work_svc.derive_region_ids(equip_ids)
    if not region_ids:
        work_svc.raise_if_equipment_missing_region(equip_ids)
        raise ValueError("无法从所选设备推导区域，请检查设备是否已配置 region_id")
    primary_region = region_ids[0]
    return region_ids, primary_region
