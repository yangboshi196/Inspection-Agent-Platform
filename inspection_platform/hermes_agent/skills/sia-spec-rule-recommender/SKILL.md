---
name: sia-spec-rule-recommender
description: >-
  Use when matching applicable regions and recommended algorithms for a specification
  rule, or when region/algorithm recommendations are empty or wrong (推荐为空).
  Runs spec_region_algorithm_matcher with GET /api/region and GET /api/algorithm catalogs.
  Triggers: 区域推荐, 算法推荐, 智能推荐, 规范匹配区域算法, 适用区域, 推荐算法,
  推荐说明, spec_rule_recommend.
version: 1.0.0
author: sia
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [specification, recommendation, region, algorithm, llm, sia, 智能推荐]
    related_skills: [sia-knowledge-pipeline, sia-spec-rule-extractor, sia-spec-pipeline, sia-spec-step-recommend]
---

# sia 规范智能推荐（Agent 角色）

## 何时启用（Hermes 自动识别）

用户提到 **区域推荐、算法推荐、智能推荐、推荐为空、适用区域、推荐说明** 时加载本 skill。

**多角色流水线**中推荐确认见 [sia-spec-step-recommend](../sia-spec-step-recommend/SKILL.md)（步骤 4/5）。

若规则尚未抽取，先加载 [sia-spec-rule-extractor](../sia-spec-rule-extractor/SKILL.md)。

平台内置 Agent 角色 **`spec_region_algorithm_matcher`**（规范条目智能推荐助手），为单条规范从平台目录中选出适用区域与推荐算法。

## Agent 角色元数据

| 字段 | 值 |
|------|-----|
| `id` | `spec_region_algorithm_matcher` |
| `label` | 规范条目智能推荐助手 |
| `purpose` | `spec_rule_recommend` |
| System Prompt | `agent_base/prompts/specification/match_regions_algorithms.txt` |
| 角色注册 | `agent_base/prompts/specification/agents.json` |
| 运行时封装 | `inspection_platform/specification/agent_roles.py` |
| 编排入口 | `inspection_platform/specification/recommender.py` |

## 何时启用

- 规范抽取完成后，需要为每条规则绑定**适用区域**与**推荐算法**
- 用户编辑规范后需要重新生成推荐说明
- 调试「推荐 id 为空」或「推荐了不存在的算法」

**不要用于：** 从文档原文抽取规则（见 [sia-spec-rule-extractor](../sia-spec-rule-extractor/SKILL.md)）。

## 调用方式

### 方式 A — 随抽取自动触发（默认）

`POST /api/spec/rules/extract` 在识别出每条规则后，**自动**调用本角色一次（`recommend_for_rule`）。

### 方式 B — 代码直接调用

```python
from inspection_platform.specification.recommender import recommend_for_rule

rec = recommend_for_rule(
    name="吊装卸货期间吊物下方严禁站人",
    desc="装卸作业现场人员站位管控。",
    requirements="吊物下方严禁站人，作业区域应设置警戒。",
)
# rec: region_ids, algorithm_ids, region_reasoning, algorithm_reasoning
```

## 目录输入（User 消息的一部分）

推荐前平台自动加载：

| 目录 | 来源 | 字段 |
|------|------|------|
| 区域 | `RegionMetaService` / `GET /api/region` | `id`, `name`, `desc` |
| 算法 | `AlgorithmService` / `GET /api/algorithm/` | `algorithm_id`, `name`, `desc`, `health` |

User 消息为 JSON（`build_region_algorithm_user_message`）：

```json
{
  "rule": {
    "name": "规范标题",
    "desc": "适用场景",
    "requirements": "具体要求"
  },
  "regions": [{ "id": "...", "name": "...", "desc": "..." }],
  "algorithms": [{ "algorithm_id": "...", "name": "...", "desc": "...", "health": "healthy" }]
}
```

## LLM 输出契约

System prompt 要求**只输出一个 JSON 对象**（无 Markdown 围栏）：

```json
{
  "region_ids": ["region-id-1"],
  "algorithm_ids": ["1014", "1013"],
  "region_reasoning": "该规范适用于码头装卸区…",
  "algorithm_reasoning": "推荐吊车作业禁止进入、卸货作业禁止进入算法…"
}
```

### 后处理（防幻觉）

`recommender.py` 对 `region_ids` / `algorithm_ids` 做**白名单校验**，不在目录中的 id 会被丢弃。

## 约束摘要

- id 必须**逐字复制**自输入目录，禁止编造
- 算法优先 `health=healthy`；`degraded` 可备选
- 每条规范通常推荐 1–3 个算法；区域可多选

## 故障排查

| 现象 | 原因 | 处理 |
|------|------|------|
| `region_ids` 为空 | 目录无匹配或 LLM 保守 | 检查区域目录是否覆盖业务场景 |
| `algorithm_ids` 为空 | 算法目录缺项或 health 差 | `GET /api/algorithm/` 确认同步 |
| 解析失败 | 模型输出非 JSON | 查 `recommend_warnings` |
| id 被丢弃 | 模型幻觉 id | 正常现象，白名单已过滤 |

## 与抽取 Agent 的关系

```
spec_rule_entity_recognizer  →  JSON 数组（规则实体）
        ↓ 每条规则
spec_region_algorithm_matcher  →  JSON 对象（区域 + 算法推荐）
        ↓
MySQL spec_rule（recommended_regions_json / recommended_algorithms_json）
```

## 代码引用

```python
from inspection_platform.specification.agent_roles import (
    REGION_ALGORITHM_MATCHER,
    build_region_algorithm_user_message,
    build_chat_request,
    list_spec_agent_roles,
)
```
