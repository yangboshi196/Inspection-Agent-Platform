"""规范抽取专用 Agent 角色：封装 system prompt、调用参数与 user 消息构造。"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from agent_base.llm.types import ChatRequest, LlmChatMessage
from agent_base.prompts import load_prompt, load_prompt_json


@dataclass(frozen=True)
class SpecAgentRole:
    id: str
    label: str
    role: str
    system_prompt_path: str
    purpose: str
    temperature: float
    max_output_tokens: int
    skill: str

    @property
    def system_prompt(self) -> str:
        return load_prompt(self.system_prompt_path)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "role": self.role,
            "system_prompt": self.system_prompt_path,
            "purpose": self.purpose,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "skill": self.skill,
        }


@lru_cache(maxsize=1)
def _agents_from_manifest() -> dict[str, SpecAgentRole]:
    manifest = load_prompt_json("specification/agents.json")
    out: dict[str, SpecAgentRole] = {}
    for row in manifest.get("agents") or []:
        role = SpecAgentRole(
            id=str(row["id"]),
            label=str(row["label"]),
            role=str(row["role"]),
            system_prompt_path=str(row["system_prompt"]),
            purpose=str(row["purpose"]),
            temperature=float(row.get("temperature", 0.2)),
            max_output_tokens=int(row.get("max_output_tokens", 2048)),
            skill=str(row.get("skill") or ""),
        )
        out[role.id] = role
    return out


RULE_ENTITY_RECOGNIZER = SpecAgentRole(
    id="spec_rule_entity_recognizer",
    label="规范实体识别助手",
    role="从已向量化文档摘录中提取可入库的规范实体（规则记录）",
    system_prompt_path="specification/rule_entity_recognition.txt",
    purpose="spec_rule_extract",
    temperature=0.2,
    max_output_tokens=4096,
    skill="sia-spec-rule-extractor",
)

REGION_ALGORITHM_MATCHER = SpecAgentRole(
    id="spec_region_algorithm_matcher",
    label="规范条目智能推荐助手",
    role="为单条规范从平台区域/算法目录中语义匹配适用区域与推荐算法",
    system_prompt_path="specification/match_regions_algorithms.txt",
    purpose="spec_rule_recommend",
    temperature=0.2,
    max_output_tokens=2048,
    skill="sia-spec-rule-recommender",
)

SPEC_PROJECT_MANAGER = SpecAgentRole(
    id="spec_project_manager",
    label="规范入库项目经理",
    role="规划单批文档规范抽取的范围、风险与交付物",
    system_prompt_path="specification/pipeline_project_manager.txt",
    purpose="spec_pipeline_project_manager",
    temperature=0.3,
    max_output_tokens=1024,
    skill="sia-spec-step-project-manager",
)

SPEC_PRODUCT_MANAGER = SpecAgentRole(
    id="spec_product_manager",
    label="规范抽取产品经理",
    role="制定 topic、max_rules 与验收标准",
    system_prompt_path="specification/pipeline_product_manager.txt",
    purpose="spec_pipeline_product_manager",
    temperature=0.3,
    max_output_tokens=1024,
    skill="sia-spec-step-product-manager",
)

SPEC_COMPLIANCE_REVIEWER = SpecAgentRole(
    id="spec_compliance_reviewer",
    label="规范合规审核员",
    role="审核草稿规范及区域/算法推荐",
    system_prompt_path="specification/pipeline_compliance_reviewer.txt",
    purpose="spec_pipeline_review",
    temperature=0.2,
    max_output_tokens=2048,
    skill="sia-spec-step-review",
)


def list_spec_agent_roles() -> list[SpecAgentRole]:
    return [
        RULE_ENTITY_RECOGNIZER,
        REGION_ALGORITHM_MATCHER,
        SPEC_PROJECT_MANAGER,
        SPEC_PRODUCT_MANAGER,
        SPEC_COMPLIANCE_REVIEWER,
    ]


def get_spec_agent_role(agent_id: str) -> SpecAgentRole:
    roles = _agents_from_manifest()
    role = roles.get(agent_id.strip())
    if role is None:
        raise KeyError(f"unknown spec agent role: {agent_id!r}")
    return role


def build_rule_entity_user_message(
    *,
    kb_id: str,
    topic: str,
    max_rules: int,
    context: str,
    per_chunk: bool = False,
) -> str:
    scope_line = (
        f"摘录来自知识库 kb_id={kb_id!r}；"
        "规则为全局条目，设备与区域在巡检业务中绑定。\n"
    )
    topic_line = topic.strip() or "（未指定，请通读摘录归纳）"
    if per_chunk:
        limit_line = (
            "本摘录为**单个文档分片**（全文之一段）。请从中提取**恰好 1 条**规范实体；"
            "若仅为标题或目录，仍须根据可见内容生成一条可入库条目，"
            "`requirements` 优先保留摘录原文关键句。\n"
        )
    else:
        limit_line = f"最多输出 {max_rules} 条规则。\n"
    return (
        scope_line
        + f"用户关注主题：{topic_line}\n"
        + limit_line
        + "\n【原文摘录】\n"
        + f"{context}\n\n"
        + "请只输出 JSON 数组，不要其它说明文字。"
    )


def build_region_algorithm_user_message(
    *,
    name: str,
    desc: str,
    requirements: str,
    regions: list[dict[str, str]],
    algorithms: list[dict[str, str]],
) -> str:
    payload = {
        "rule": {
            "name": (name or "").strip(),
            "desc": (desc or "").strip(),
            "requirements": (requirements or "").strip(),
        },
        "regions": regions,
        "algorithms": algorithms,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_chat_request(
    role: SpecAgentRole,
    *,
    user_content: str,
    model_name: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> ChatRequest:
    meta: dict[str, Any] = {
        "request_id": uuid.uuid4().hex,
        "purpose": role.purpose,
        "agent_id": role.id,
        "agent_label": role.label,
    }
    if model_name:
        meta["model_name"] = model_name
    if extra_metadata:
        meta.update(extra_metadata)
    return ChatRequest(
        messages=[
            LlmChatMessage(role="system", content=role.system_prompt, metadata={}),
            LlmChatMessage(role="user", content=user_content, metadata={}),
        ],
        metadata=meta,
        temperature=role.temperature,
        max_output_tokens=role.max_output_tokens,
    )
