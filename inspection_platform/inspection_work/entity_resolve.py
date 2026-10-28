"""通用意图路实体解析：分词、去后缀、关键字检索与内存模糊匹配（不改数据库）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from inspection_platform.algorithm.service import AlgorithmService
from inspection_platform.equipment.service import EquipmentService

# 通用能力类后缀：用户说「XX检测/识别」时，额外用「XX」再检索
_ACTION_SUFFIXES = ("检测", "识别", "监测", "检查", "分析", "管控", "巡检", "告警", "预警")

# 从用户原文抽取「XX检测 / XX识别」等能力短语（与具体业务词无关）
_CAPABILITY_PHRASE_RE = re.compile(
    r"([\w\u4e00-\u9fff]{2,12})(?:检测|识别|检查|监测|分析|告警|预警)"
)

# 从用户原文抽取设备类名词（通用 IoT 表述）
_DEVICE_NOUN_RE = re.compile(r"(摄像头|摄像机|传感器|探头|读数器|采集器)")

# 按标点切分 topic 子句，便于分段检索
_SEGMENT_SPLIT_RE = re.compile(r"[，,。；;\n、]+")

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]{2,}")

# 并入业务（pin）所需最低匹配分；仅对「明确提及」的实体生效
_PIN_SCORE_THRESHOLD = 0.55
# 进入候选目录的最低匹配分
_CATALOG_SCORE_THRESHOLD = 0.4


@dataclass
class IntentPins:
    """意图路关键字命中、需强制并入业务的实体 id。"""

    algorithm_ids: list[str] = field(default_factory=list)
    region_ids: list[str] = field(default_factory=list)
    equipment_ids: list[str] = field(default_factory=list)


@dataclass
class ExplicitMentions:
    """用户明确点名的实体短语（来自 LLM 意图 + 通用句式抽取）。"""

    algorithms: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    devices: list[str] = field(default_factory=list)


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _strip_action_suffix(term: str) -> str:
    for suf in _ACTION_SUFFIXES:
        if term.endswith(suf) and len(term) > len(suf) + 1:
            return term[: -len(suf)]
    return ""


def expand_mention_phrases(*phrases: str) -> list[str]:
    """
    对单条实体短语做通用扩展：原词 → 去后缀 → 分词 → 分词再去后缀。
    不依赖任何业务别名表。
    """
    seen: set[str] = set()
    ordered: list[str] = []

    def add(raw: str) -> None:
        term = raw.strip()
        if len(term) < 2:
            return
        key = _norm(term)
        if key in seen:
            return
        seen.add(key)
        ordered.append(term)

    for phrase in phrases:
        if not phrase:
            continue
        text = phrase.strip()
        add(text)
        stem = _strip_action_suffix(text)
        if stem:
            add(stem)
        for tok in _tokenize(text):
            add(tok)
            stem_tok = _strip_action_suffix(tok)
            if stem_tok:
                add(stem_tok)

    return ordered


def _topic_segments(topic: str) -> list[str]:
    return [s.strip() for s in _SEGMENT_SPLIT_RE.split(topic or "") if len(s.strip()) >= 3]


def extract_explicit_mentions(topic: str, intent: dict[str, Any]) -> ExplicitMentions:
    """汇总 LLM 意图实体 + 通用句式抽取的能力/设备短语。"""
    algos: list[str] = []
    regions: list[str] = []
    devices: list[str] = []
    seen_a: set[str] = set()
    seen_r: set[str] = set()
    seen_d: set[str] = set()

    def _push(bucket: list[str], seen: set[str], val: str) -> None:
        v = val.strip()
        if len(v) < 2:
            return
        k = _norm(v)
        if k in seen:
            return
        seen.add(k)
        bucket.append(v)

    for el in intent.get("algorithms") or []:
        if isinstance(el, dict):
            _push(algos, seen_a, str(el.get("name") or ""))

    for el in intent.get("regions") or []:
        if isinstance(el, dict):
            _push(regions, seen_r, str(el.get("name") or ""))

    for el in intent.get("devices") or []:
        if isinstance(el, dict):
            _push(devices, seen_d, str(el.get("name") or ""))

    for m in _CAPABILITY_PHRASE_RE.finditer(topic or ""):
        _push(algos, seen_a, m.group(0))
        _push(algos, seen_a, m.group(1))

    for m in _DEVICE_NOUN_RE.finditer(topic or ""):
        _push(devices, seen_d, m.group(1))

    return ExplicitMentions(algorithms=algos, regions=regions, devices=devices)


def collect_catalog_search_terms(topic: str, intent: dict[str, Any]) -> list[str]:
    """
    目录扩展用检索词：明确提及 + topic 子句 + 意图实体，均只做通用短语扩展。
    用于扩大 LLM 候选池，不直接决定 pin。
    """
    mentions = extract_explicit_mentions(topic, intent)
    seeds: list[str] = []
    seeds.extend(mentions.algorithms)
    seeds.extend(mentions.regions)
    seeds.extend(mentions.devices)
    seeds.extend(_topic_segments(topic))
    return expand_mention_phrases(*seeds)


def collect_pin_search_terms(topic: str, intent: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    """强制并入业务用的分域检索词（仅来自明确提及，不含 topic 全文分词）。"""
    mentions = extract_explicit_mentions(topic, intent)
    return (
        expand_mention_phrases(*mentions.algorithms),
        expand_mention_phrases(*mentions.regions),
        expand_mention_phrases(*mentions.devices),
    )


def _score_text_match(query: str, *texts: str) -> float:
    q = _norm(query)
    if not q:
        return 0.0
    best = 0.0
    for text in texts:
        n = _norm(text)
        if not n:
            continue
        if q == n:
            return 1.0
        if q in n or n in q:
            best = max(best, 0.85)
            continue
        q_tokens = _tokenize(q)
        if not q_tokens:
            continue
        hits = sum(1 for t in q_tokens if t in n)
        best = max(best, hits / len(q_tokens))
    return best


def _rank_rows(
    term: str,
    rows: list[dict[str, Any]],
    *,
    id_key: str,
    name_key: str,
    desc_key: str | None = None,
) -> list[tuple[float, dict[str, Any]]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        name = str(row.get(name_key) or "")
        desc = str(row.get(desc_key) or "") if desc_key else ""
        score = _score_text_match(term, name, desc)
        if score >= _CATALOG_SCORE_THRESHOLD and str(row.get(id_key) or "").strip():
            scored.append((score, row))
    scored.sort(key=lambda x: (-x[0], str(x[1].get(name_key) or "")))
    return scored


def _resolve_by_terms(
    terms: list[str],
    *,
    sql_search: Callable[[str], list[dict[str, Any]]],
    pool: list[dict[str, Any]],
    id_key: str,
    name_key: str,
    desc_key: str | None = None,
    pin_threshold: float = _PIN_SCORE_THRESHOLD,
) -> tuple[list[dict[str, Any]], list[str]]:
    by_id: dict[str, dict[str, Any]] = {}
    pinned: list[str] = []
    seen_pin: set[str] = set()

    for term in terms:
        candidates: dict[str, tuple[float, dict[str, Any]]] = {}

        for row in sql_search(term):
            rid = str(row.get(id_key) or "").strip()
            if not rid:
                continue
            score = _score_text_match(
                term,
                str(row.get(name_key) or ""),
                str(row.get(desc_key) or "") if desc_key else "",
            )
            prev = candidates.get(rid)
            if prev is None or score > prev[0]:
                candidates[rid] = (score, row)

        if not candidates:
            for score, row in _rank_rows(term, pool, id_key=id_key, name_key=name_key, desc_key=desc_key):
                rid = str(row.get(id_key) or "").strip()
                if rid:
                    prev = candidates.get(rid)
                    if prev is None or score > prev[0]:
                        candidates[rid] = (score, row)

        if not candidates:
            continue

        best_id, (best_score, best_row) = max(candidates.items(), key=lambda x: (x[1][0], str(x[1][1].get(name_key) or "")))
        by_id[best_id] = best_row
        if best_score >= pin_threshold and best_id not in seen_pin:
            seen_pin.add(best_id)
            pinned.append(best_id)

        for rid, (score, row) in sorted(candidates.items(), key=lambda x: -x[1][0])[:4]:
            if score >= _CATALOG_SCORE_THRESHOLD:
                by_id[rid] = row

    return list(by_id.values()), pinned


def resolve_algorithms(
    algo_svc: AlgorithmService,
    terms: list[str],
    *,
    pin_threshold: float = _PIN_SCORE_THRESHOLD,
) -> tuple[list[dict[str, Any]], list[str]]:
    pool, _ = algo_svc.list_algorithms(limit=200, offset=0)

    def sql_search(term: str) -> list[dict[str, Any]]:
        rows, _ = algo_svc.list_algorithms(q=term, limit=12, offset=0)
        return rows

    return _resolve_by_terms(
        terms,
        sql_search=sql_search,
        pool=pool,
        id_key="algorithm_id",
        name_key="name",
        desc_key="desc",
        pin_threshold=pin_threshold,
    )


def resolve_regions(
    all_regions: list[dict[str, Any]],
    terms: list[str],
    *,
    pin_threshold: float = _PIN_SCORE_THRESHOLD,
) -> tuple[list[dict[str, Any]], list[str]]:
    def sql_search(term: str) -> list[dict[str, Any]]:
        return [
            r
            for r in all_regions
            if _score_text_match(term, str(r.get("name") or ""), str(r.get("desc") or ""))
            >= _CATALOG_SCORE_THRESHOLD
        ]

    return _resolve_by_terms(
        terms,
        sql_search=sql_search,
        pool=all_regions,
        id_key="id",
        name_key="name",
        desc_key="desc",
        pin_threshold=pin_threshold,
    )


def resolve_equipment(
    eq_svc: EquipmentService,
    terms: list[str],
    *,
    pin_threshold: float = _PIN_SCORE_THRESHOLD,
) -> tuple[list[dict[str, Any]], list[str]]:
    pool, _ = eq_svc.list_equipment(limit=300, offset=0)

    def sql_search(term: str) -> list[dict[str, Any]]:
        rows, _ = eq_svc.list_equipment(q=term, limit=12, offset=0)
        return rows

    return _resolve_by_terms(
        terms,
        sql_search=sql_search,
        pool=pool,
        id_key="id",
        name_key="name",
        desc_key="description",
        pin_threshold=pin_threshold,
    )


def resolve_intent_entities(
    *,
    topic: str,
    intent: dict[str, Any],
    all_regions: list[dict[str, Any]],
    algo_svc: AlgorithmService,
    eq_svc: EquipmentService,
) -> IntentPins:
    """意图路增强：仅对明确提及的实体做关键字 + 模糊匹配，返回需并入业务的 id。"""
    algo_terms, region_terms, device_terms = collect_pin_search_terms(topic, intent)

    _, algo_pins = resolve_algorithms(algo_svc, algo_terms)
    _, region_pins = resolve_regions(all_regions, region_terms)
    _, equip_pins = resolve_equipment(eq_svc, device_terms)

    for el in intent.get("algorithms") or []:
        if isinstance(el, dict):
            aid = str(el.get("id") or "").strip()
            if aid and aid not in algo_pins:
                algo_pins.append(aid)
    for el in intent.get("regions") or []:
        if isinstance(el, dict):
            rid = str(el.get("id") or "").strip()
            if rid and rid not in region_pins:
                region_pins.append(rid)
    for el in intent.get("devices") or []:
        if isinstance(el, dict):
            eid = str(el.get("id") or "").strip()
            if eid and eid not in equip_pins:
                equip_pins.append(eid)

    return IntentPins(
        algorithm_ids=algo_pins,
        region_ids=region_pins,
        equipment_ids=equip_pins,
    )


# 兼容旧调用名
def collect_intent_search_terms(topic: str, intent: dict[str, Any]) -> list[str]:
    return collect_catalog_search_terms(topic, intent)
