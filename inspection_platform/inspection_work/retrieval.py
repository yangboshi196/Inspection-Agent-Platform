"""巡检业务 AI 生成：规范向量检索（与知识库 / 规范管理同源）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from inspection_platform.specification.service import SpecificationService

# 向量检索：与 agent_base RAG 默认 min_score 对齐
RULE_VECTOR_MIN_SCORE = 0.75
# 与 top1 的最大允许分差（score 量纲 0~1）
RULE_VECTOR_SCORE_GAP = 0.10
RULE_VECTOR_MAX_K = 5
RULE_VECTOR_CANDIDATE_K = 15
# 未命中阈值时，黄色信息框展示的近义规范条数
RULE_NEAR_MISS_TOP_K = 3

# 未命中已发布规范时，前端黄色信息框首行文案
RULE_MISS_TRACE_MESSAGE = "未命中规范，以下是得分最高的三个规范"


@dataclass
class RuleRetrievalHit:
    rule: dict[str, Any]
    score: float
    recall_rate: float
    path: Literal["vector"] = "vector"


@dataclass
class RuleRetrievalResult:
    hits: list[RuleRetrievalHit] = field(default_factory=list)
    near_misses: list[RuleRetrievalHit] = field(default_factory=list)
    path: Literal["vector", "none"] = "none"

    @property
    def rules(self) -> list[dict[str, Any]]:
        return [h.rule for h in self.hits]


def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    s = (text or "").lower().strip()
    if not s:
        return tokens
    for m in re.findall(r"[\w\u4e00-\u9fff]{2,}", s):
        tokens.add(m)
    for run in re.findall(r"[\u4e00-\u9fff]+", s):
        if 2 <= len(run) <= 8:
            tokens.add(run)
        for n in (2, 3):
            for i in range(len(run) - n + 1):
                tokens.add(run[i : i + n])
    return tokens


def _rule_text_blob(rule: dict[str, Any]) -> str:
    rec_algos = rule.get("recommended_algorithms")
    algo_text = ""
    if isinstance(rec_algos, list):
        algo_text = " ".join(str(x) for x in rec_algos if str(x).strip())
    return " ".join(
        [
            str(rule.get("name") or ""),
            str(rule.get("desc") or ""),
            str(rule.get("requirements") or ""),
            algo_text,
        ]
    )


def keyword_recall_rate(topic: str, rule: dict[str, Any]) -> float:
    """检索召回率：用户描述分词在规范文本中的命中率（0~1），仅用于向量路 trace 展示。"""
    tokens = _tokenize(topic)
    if not tokens:
        return 0.0
    hay = _rule_text_blob(rule).lower()
    hits = sum(1 for t in tokens if t in hay)
    return hits / max(len(tokens), 1)


def _filter_scored_hits(
    scored: list[tuple[float, dict[str, Any]]],
    *,
    topic: str,
    min_score: float,
    gap: float,
    max_k: int,
) -> list[RuleRetrievalHit]:
    if not scored:
        return []
    scored.sort(key=lambda x: (-x[0], str(x[1].get("name") or "")))
    top_score = scored[0][0]
    if top_score < min_score:
        return []
    floor = top_score - gap
    out: list[RuleRetrievalHit] = []
    seen: set[str] = set()
    for score, rule in scored:
        if score < min_score or score < floor:
            continue
        rid = str(rule.get("rule_id") or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        out.append(
            RuleRetrievalHit(
                rule=rule,
                score=score,
                recall_rate=keyword_recall_rate(topic, rule),
                path="vector",
            )
        )
        if len(out) >= max_k:
            break
    return out


def _top_near_miss_hits(
    scored: list[tuple[float, dict[str, Any]]],
    *,
    topic: str,
    max_k: int = RULE_NEAR_MISS_TOP_K,
) -> list[RuleRetrievalHit]:
    """未达 min_score 时，取相似度最高的若干条供前端展示（不参与业务编组）。"""
    if not scored:
        return []
    scored.sort(key=lambda x: (-x[0], str(x[1].get("name") or "")))
    out: list[RuleRetrievalHit] = []
    seen: set[str] = set()
    for score, rule in scored:
        rid = str(rule.get("rule_id") or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        out.append(
            RuleRetrievalHit(
                rule=rule,
                score=score,
                recall_rate=keyword_recall_rate(topic, rule),
                path="vector",
            )
        )
        if len(out) >= max(1, int(max_k)):
            break
    return out


def _rules_from_vector_hits(
    spec_svc: SpecificationService,
    hits: list[dict[str, Any]],
) -> list[tuple[float, dict[str, Any]]]:
    rows: list[tuple[float, dict[str, Any]]] = []
    seen: set[str] = set()
    for hit in hits:
        rule = hit.get("rule")
        if not isinstance(rule, dict):
            continue
        if str(rule.get("status") or "") != "published":
            continue
        rid = str(rule.get("rule_id") or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        score = float(hit.get("score") or 0.0)
        try:
            full = spec_svc.get_rule(rid)
        except KeyError:
            full = rule
        rows.append((score, full))
    return rows


def retrieve_published_rules_by_topic(
    spec_svc: SpecificationService,
    *,
    topic: str,
    max_k: int = RULE_VECTOR_MAX_K,
    min_score: float = RULE_VECTOR_MIN_SCORE,
    score_gap: float = RULE_VECTOR_SCORE_GAP,
    candidate_k: int = RULE_VECTOR_CANDIDATE_K,
) -> RuleRetrievalResult:
    """
    按用户诉求检索已发布规范（仅向量路）。

    candidate_k 召回 → min_score + 与 top1 分差 gap 过滤 → 动态 K（≤ max_k）。
    无命中时返回空结果（path=none），由上层在 trace 中展示未命中提示。
    """
    q = (topic or "").strip()
    if not q:
        raise ValueError("topic 不能为空")

    k = max(1, min(int(max_k), 50))
    cand = max(k, min(int(candidate_k), 50))

    hits = spec_svc.query_rules(query=q, top_k=k, candidate_k=cand)
    vector_rows = _rules_from_vector_hits(spec_svc, hits)
    filtered = _filter_scored_hits(
        vector_rows,
        topic=q,
        min_score=float(min_score),
        gap=float(score_gap),
        max_k=k,
    )
    if filtered:
        return RuleRetrievalResult(hits=filtered, path="vector")
    near = _top_near_miss_hits(vector_rows, topic=q)
    return RuleRetrievalResult(hits=[], near_misses=near, path="none")


def rule_hit_to_trace(hit: RuleRetrievalHit, *, index: int) -> dict[str, Any]:
    rule = hit.rule
    name = str(rule.get("name") or "").strip()
    desc = str(rule.get("desc") or "").strip()
    req = str(rule.get("requirements") or "").strip()
    if name and desc:
        summary = f"{name}（{desc}）"
    elif name and req:
        summary = f"{name}（{req[:240]}{'…' if len(req) > 240 else ''}）"
    else:
        summary = name or desc or req
    return {
        "index": index,
        "rule_id": str(rule.get("rule_id") or ""),
        "name": name,
        "summary": summary,
        "similarity": round(hit.score, 4),
        "recall_rate": round(hit.recall_rate, 4),
        "path": hit.path,
    }
