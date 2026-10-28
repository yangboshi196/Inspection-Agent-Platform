"""巡检报告正文生成（与前端 reportPlanMock 逻辑对齐）。"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from agent_base.llm.errors import LLMError
from agent_base.llm.types import ChatRequest, LlmChatMessage
from agent_base.model_manager.manager import ModelManager

ReportFrequency = Literal["daily", "weekly", "monthly", "adhoc"]
ReportSource = Literal["scheduled", "manual"]

CORE_SECTION_TITLES = ("规范", "巡检业务", "区域", "巡检结果")
DEFAULT_NAMING_TEMPLATE = "{name}-{date}"


def _display_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _ref_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def frequency_label(frequency: str) -> str:
    if frequency == "daily":
        return "日报"
    if frequency == "weekly":
        return "周报"
    if frequency == "monthly":
        return "月报"
    return "临时"


def schedule_mode_label(mode: str) -> str:
    mapping = {
        "periodic": "周期执行",
        "scheduled": "定时执行",
        "continuous": "连续监测",
        "manual": "手动触发",
    }
    return mapping.get(mode, mode or "手动触发")


def period_for_frequency(frequency: str, ref_date: str | None = None) -> str:
    ref = ref_date or _ref_date()
    if frequency == "daily":
        return ref
    d = datetime.strptime(ref, "%Y-%m-%d")
    if frequency == "weekly":
        day = d.isoweekday()
        mon = d - timedelta(days=day - 1)
        sun = mon + timedelta(days=6)
        return f"{mon.strftime('%Y-%m-%d')} — {sun.strftime('%Y-%m-%d')}"
    y, m = d.year, d.month
    if m == 12:
        last = datetime(y + 1, 1, 1) - timedelta(days=1)
    else:
        last = datetime(y, m + 1, 1) - timedelta(days=1)
    return f"{y}-{m:02d}-01 — {last.strftime('%Y-%m-%d')}"


def default_report_title(name: str, ref_date: str | None = None) -> str:
    ref = ref_date or _ref_date()
    return DEFAULT_NAMING_TEMPLATE.replace("{name}", name).replace("{date}", ref).replace("{period}", ref).replace("{work}", name)


def _resolve_works(work_ids: list[str], catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index = {str(w.get("work_id") or ""): w for w in catalog}
    out: list[dict[str, Any]] = []
    for wid in work_ids:
        w = index.get(wid)
        if w:
            out.append(w)
    return out


def _unique_rule_names(works: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for work in works:
        for rule in work.get("rule_set") or []:
            rid = str(rule.get("rule_id") or "")
            if rid and rid not in seen:
                seen.add(rid)
                names.append(str(rule.get("name") or rid))
    return names


def _unique_region_names(works: list[dict[str, Any]], region_names: dict[str, str]) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for work in works:
        rid = str(work.get("region_id") or "")
        if rid and rid not in seen:
            seen.add(rid)
            names.append(region_names.get(rid) or str(work.get("region_name") or rid))
    return names


def _demo_execution_count(work_count: int, frequency: str) -> int:
    if frequency == "daily":
        return max(work_count * 6, 6)
    if frequency == "weekly":
        return max(work_count * 16, 16)
    if frequency == "monthly":
        return max(work_count * 60, 60)
    return max(work_count * 2, 2)


def _core_section_body(
    title: str,
    works: list[dict[str, Any]],
    frequency: str,
    prompt: str,
    region_names: dict[str, str],
) -> str:
    freq = frequency_label(frequency)
    rule_names = _unique_rule_names(works)
    region_names_list = _unique_region_names(works, region_names)

    if title == "规范":
        if not rule_names:
            return "本报告未关联知识库规范条款。"
        return f"共对照 {len(rule_names)} 条规范：{'、'.join(rule_names)}。"
    if title == "巡检业务":
        if not works:
            return "未关联巡检业务。"
        names = [str(w.get("name") or "") for w in works]
        return f"{len(works)} 条巡检业务：{'、'.join(names)}。"
    if title == "区域":
        if not region_names_list:
            return "未覆盖现场区域。"
        return f"覆盖 {len(region_names_list)} 个区域：{'、'.join(region_names_list)}。"

    exec_count = _demo_execution_count(len(works), frequency)
    prompt_hint = ""
    p = (prompt or "").strip()
    if p:
        snippet = p[:48] + ("…" if len(p) > 48 else "")
        prompt_hint = f" {snippet}"
    return (
        f"{freq}内 {len(works) or 0} 条巡检业务共执行巡检 {exec_count} 次，"
        f"综合合规率 89.2%；视频告警 3 起、传感异常 2 起，已关闭 2 起。{prompt_hint}"
    )


def _core_section_detail(title: str, works: list[dict[str, Any]], region_names: dict[str, str]) -> str | None:
    if not works:
        return None

    if title == "规范":
        lines = []
        for w in works:
            rules = "、".join(str(r.get("name") or "") for r in (w.get("rule_set") or [])) or "未绑定规范"
            lines.append(f"· {w.get('name') or ''}：{rules}")
        return "\n".join(lines)

    if title == "巡检业务":
        lines = []
        for w in works:
            mode = str(w.get("schedule_mode") or "manual")
            if mode == "periodic":
                schedule = w.get("schedule_interval") or schedule_mode_label(mode)
            elif mode == "scheduled":
                schedule = w.get("schedule_times") or schedule_mode_label(mode)
            else:
                schedule = schedule_mode_label(mode)
            algo_n = len(w.get("algorithm_set") or [])
            equip_n = len(w.get("equipment_set") or [])
            lines.append(f"· {w.get('name') or ''}（{schedule}）· {algo_n} 个算法 · {equip_n} 个设备")
        return "\n".join(lines)

    if title == "区域":
        lines = []
        for w in works:
            rid = str(w.get("region_id") or "")
            rn = region_names.get(rid) or str(w.get("region_name") or rid)
            lines.append(f"· {rn} ← {w.get('name') or ''}")
        return "\n".join(lines)

    lines = []
    for w in works:
        algos = w.get("algorithm_set") or []
        degraded = any(str(a.get("health") or "") == "degraded" for a in algos)
        algo_health = "部分算法降级" if degraded else "算法运行正常"
        lines.append(f"· {w.get('name') or ''}：合规率 91%，告警 1 起待跟进，{algo_health}")
    return "\n".join(lines)


def _section_id() -> str:
    return f"sec-{uuid.uuid4().hex[:7]}"


def parse_template_section_titles(text: str) -> list[str]:
    titles: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^#{1,3}\s+(.+)", line)
        if m:
            titles.append(m.group(1))
            continue
        m = re.match(r"^\d+[.、)\]]\s*(.+)", line)
        if m:
            titles.append(m.group(1))
            continue
        m = re.match(r"^[一二三四五六七八九十]+[、.]\s*(.+)", line)
        if m:
            titles.append(m.group(1))
            continue
        if line.endswith("：") or line.endswith(":"):
            titles.append(line.rstrip("：:"))
    return titles


def build_core_report_sections(
    work_ids: list[str],
    frequency: str,
    prompt: str,
    works_catalog: list[dict[str, Any]],
    region_names: dict[str, str],
) -> list[dict[str, Any]]:
    works = _resolve_works(work_ids, works_catalog)
    sections: list[dict[str, Any]] = []
    for title in CORE_SECTION_TITLES:
        detail = _core_section_detail(title, works, region_names)
        row: dict[str, Any] = {
            "id": _section_id(),
            "title": title,
            "body": _core_section_body(title, works, frequency, prompt, region_names),
        }
        if detail:
            row["detail"] = detail
        sections.append(row)
    return sections


def generate_report_sections(
    prompt: str,
    work_ids: list[str],
    frequency: str,
    template_content: str | None,
    works_catalog: list[dict[str, Any]],
    region_names: dict[str, str],
) -> list[dict[str, Any]]:
    return _generate_template_sections(
        prompt, work_ids, frequency, template_content, works_catalog, region_names
    )


def _template_content_hint(template_content: str | None, *, max_len: int = 4000) -> str:
    text = (template_content or "").strip()
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _generate_template_sections(
    prompt: str,
    work_ids: list[str],
    frequency: str,
    template_content: str | None,
    works_catalog: list[dict[str, Any]],
    region_names: dict[str, str],
) -> list[dict[str, Any]]:
    sections = build_core_report_sections(work_ids, frequency, prompt, works_catalog, region_names)
    hint = _template_content_hint(template_content)
    if not hint:
        return sections
    out: list[dict[str, Any]] = []
    for section in sections:
        if section.get("title") != "巡检结果":
            out.append(section)
            continue
        out.append(
            {
                **section,
                "body": f"{section.get('body') or ''}\n\n（参照报告模版）\n{hint}",
            }
        )
    return out


def generate_report_summary(
    work_ids: list[str],
    frequency: str,
    works_catalog: list[dict[str, Any]],
    region_names: dict[str, str],
) -> str:
    return _generate_template_summary(work_ids, frequency, works_catalog, region_names)


def _generate_template_summary(
    work_ids: list[str],
    frequency: str,
    works_catalog: list[dict[str, Any]],
    region_names: dict[str, str],
) -> str:
    works = _resolve_works(work_ids, works_catalog)
    region_names_list = _unique_region_names(works, region_names)
    rule_names = _unique_rule_names(works)
    freq = frequency_label(frequency)
    exec_count = _demo_execution_count(len(works), frequency)
    regions = "、".join(region_names_list) if region_names_list else "—"
    return (
        f"{freq}汇总：对照 {len(rule_names)} 条规范，{len(works)} 条巡检业务覆盖 {regions}；"
        f"共执行 {exec_count} 次，综合合规率 89.2%，待跟进告警 2 起。"
    )


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _normalize_llm_sections(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    sections: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        if not title or not body:
            continue
        row: dict[str, Any] = {
            "id": _section_id(),
            "title": title[:256],
            "body": body[:16000],
        }
        detail = item.get("detail")
        if detail is not None and str(detail).strip():
            row["detail"] = str(detail).strip()[:32000]
        sections.append(row)
    return sections


def _try_llm_report_content(
    mm: ModelManager,
    *,
    prompt: str,
    work_ids: list[str],
    frequency: str,
    template_content: str | None,
    works_catalog: list[dict[str, Any]],
    region_names: dict[str, str],
) -> tuple[str, list[dict[str, Any]]] | None:
    works = _resolve_works(work_ids, works_catalog)
    works_summary = [
        {
            "name": w.get("name"),
            "region": region_names.get(str(w.get("region_id") or "")) or w.get("region_name"),
            "rules": [str(r.get("name") or "") for r in (w.get("rule_set") or [])],
            "algorithm_count": len(w.get("algorithm_set") or []),
            "equipment_count": len(w.get("equipment_set") or []),
        }
        for w in works
    ]

    template_hint = ""
    tpl_text = _template_content_hint(template_content, max_len=12000)
    if tpl_text:
        template_hint = f"\n\n参照以下报告模版全文（按此结构与风格输出）：\n{tpl_text}"

    user = (
        f"报告类型：{frequency_label(frequency)}\n"
        f"报告周期：{period_for_frequency(frequency)}\n"
        f"生成意图：{(prompt or '').strip() or '按常规模板汇总巡检情况'}\n"
        f"关联巡检业务 JSON：\n{json.dumps(works_summary, ensure_ascii=False)}"
        f"{template_hint}\n\n"
        "请输出 JSON 对象，字段：summary（字符串）、sections（数组）。"
        "sections 每项含 title、body，可选 detail。"
        "若提供了报告模版，sections 应尽量贴合模版章节；否则须包含：规范、巡检业务、区域、巡检结果。"
    )

    req = ChatRequest(
        messages=[
            LlmChatMessage(
                role="system",
                content="你是工业巡检报告撰写助手。只输出 JSON 对象，不要 markdown 或解释文字。",
                metadata={},
            ),
            LlmChatMessage(role="user", content=user, metadata={}),
        ],
        metadata={"request_id": uuid.uuid4().hex, "purpose": "report_generate"},
        temperature=0.3,
        max_output_tokens=4096,
    )

    try:
        from inspection_platform.deps import platform_call_chat

        resp = platform_call_chat(req)
    except LLMError:
        return None

    parsed = _extract_json_object(str(resp.content or ""))
    if not parsed:
        return None

    summary = str(parsed.get("summary") or "").strip()
    sections = _normalize_llm_sections(parsed.get("sections"))
    if not summary or len(sections) < 2:
        return None
    return summary[:8000], sections


def resolve_report_content(
    prompt: str,
    work_ids: list[str],
    frequency: str,
    template_content: str | None,
    works_catalog: list[dict[str, Any]],
    region_names: dict[str, str],
    *,
    model_manager: ModelManager | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    if model_manager is not None:
        try:
            llm = _try_llm_report_content(
                model_manager,
                prompt=prompt,
                work_ids=work_ids,
                frequency=frequency,
                template_content=template_content,
                works_catalog=works_catalog,
                region_names=region_names,
            )
            if llm:
                return llm
        except Exception:
            pass

    sections = _generate_template_sections(
        prompt, work_ids, frequency, template_content, works_catalog, region_names
    )
    summary = _generate_template_summary(work_ids, frequency, works_catalog, region_names)
    return summary, sections


def compose_report_full_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        str(report.get("title") or ""),
        f"报告周期：{report.get('period') or ''}",
        f"生成时间：{report.get('updated_at') or ''}",
    ]
    if report.get("plan_name"):
        lines.append(f"来源计划：{report['plan_name']}")
    else:
        lines.append("来源：临时生成")
    if report.get("template_name"):
        lines.append(f"参照模版：{report['template_name']}")
    lines.extend(["", "—— 摘要 ——", str(report.get("summary") or ""), ""])
    for section in report.get("sections") or []:
        lines.append(f"—— {section.get('title') or ''} ——")
        lines.append(str(section.get("body") or ""))
        if section.get("detail"):
            lines.extend(["", str(section["detail"])])
        lines.append("")
    return "\n".join(lines).rstrip()


def build_report_from_plan(
    plan: dict[str, Any],
    *,
    works_catalog: list[dict[str, Any]],
    template: dict[str, Any] | None = None,
    region_names: dict[str, str] | None = None,
    source: ReportSource = "manual",
    model_manager: ModelManager | None = None,
) -> dict[str, Any]:
    from .template_schema import template_effective_content

    region_names = region_names or {}
    frequency = str(plan.get("frequency") or "weekly")
    work_ids = list(plan.get("work_ids") or [])
    content_prompt = str(plan.get("content_prompt") or "")
    template_id = (template or {}).get("template_id") or plan.get("template_id")
    template_name = (template or {}).get("name") if template else None
    template_content = template_effective_content(template) if template else None
    period = period_for_frequency(frequency)
    title = default_report_title(str(plan.get("name") or "巡检报告"))
    stamp = _display_now()
    summary, sections = resolve_report_content(
        content_prompt,
        work_ids,
        frequency,
        template_content,
        works_catalog,
        region_names,
        model_manager=model_manager,
    )
    base = {
        "title": title,
        "period": period,
        "frequency": frequency,
        "work_ids": work_ids,
        "status": "draft",
        "source": source,
        "content_prompt": content_prompt,
        "plan_id": plan.get("plan_id"),
        "plan_name": plan.get("name"),
        "template_id": template_id,
        "template_name": template_name,
        "summary": summary,
        "sections": sections,
        "created_at": stamp,
        "updated_at": stamp,
    }
    return {**base, "full_text": compose_report_full_text({**base, "updated_at": stamp})}


def build_adhoc_report(
    *,
    name: str,
    work_ids: list[str],
    content_prompt: str,
    template: dict[str, Any] | None = None,
    works_catalog: list[dict[str, Any]],
    region_names: dict[str, str] | None = None,
    model_manager: ModelManager | None = None,
) -> dict[str, Any]:
    region_names = region_names or {}
    ref = _ref_date()
    period = f"{ref} 专项"
    title = default_report_title(name)
    stamp = _display_now()
    template_id = (template or {}).get("template_id")
    template_name = (template or {}).get("name") if template else None
    from .template_schema import template_effective_content

    template_content = template_effective_content(template) if template else None
    summary, sections = resolve_report_content(
        content_prompt,
        work_ids,
        "adhoc",
        template_content,
        works_catalog,
        region_names,
        model_manager=model_manager,
    )
    base = {
        "title": title,
        "period": period,
        "frequency": "adhoc",
        "work_ids": work_ids,
        "status": "draft",
        "source": "manual",
        "content_prompt": content_prompt,
        "plan_id": None,
        "plan_name": None,
        "template_id": template_id,
        "template_name": template_name,
        "summary": summary,
        "sections": sections,
        "created_at": stamp,
        "updated_at": stamp,
    }
    return {**base, "full_text": compose_report_full_text({**base, "updated_at": stamp})}
