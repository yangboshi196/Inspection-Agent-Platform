---
name: sia-spec-step-extract
description: >-
  Pipeline step 3/5: call platform preflight + extract API using strategy from step 2.
  Runs spec_rule_entity_recognizer and recommend per rule. Triggers: 步骤3, 规范抽取 API.
version: 1.0.0
author: sia
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [specification, pipeline, step, extract, sia]
    related_skills: [sia-spec-pipeline, sia-spec-step-product-manager, sia-spec-step-recommend]
---

# 流水线步骤 3/5：规范抽取（平台 API）

## 前置条件

- `pipeline_context.step` === `product_manager_done`
- `pipeline_context.strategy` 含 `topic`、`max_rules`
- `auth.token` 非空（否则先登录）

## 本步动作

### 1. 预检

```bash
curl -s -X POST "${PLATFORM}/api/spec/rules/extract/preflight" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "{\"kb_id\":\"${KB_ID}\",\"doc_ids\":${DOC_IDS_JSON}}"
```

`ready` 必须为 `true`，否则停止并提示先 `POST /api/knowledge/ingest`。

### 2. 抽取（含平台内推荐）

```bash
curl -s -X POST "${PLATFORM}/api/spec/rules/extract" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "{
    \"kb_id\": \"${KB_ID}\",
    \"doc_ids\": ${DOC_IDS_JSON},
    \"topic\": \"${TOPIC}\",
    \"max_rules\": ${MAX_RULES},
    \"persist\": true,
    \"re_extract\": false
  }"
```

变量来自 `pipeline_context`：`PLATFORM`=platform_base，`KB_ID`=kb_id，`DOC_IDS_JSON`=doc_ids 的 JSON 数组，`TOPIC`=strategy.topic，`MAX_RULES`=strategy.max_rules。

重抽时设 `re_extract: true`。

### 3. 写入 `extract` 并更新 step

```json
{
  "preflight_ready": true,
  "created_rule_ids": ["..."],
  "rules_count": 3,
  "warnings": []
}
```

`step` = **`extract_done`**

## 平台角色

本步调用平台 Agent 角色 `spec_rule_entity_recognizer` + `spec_region_algorithm_matcher`（见 [sia-spec-rule-extractor](../sia-spec-rule-extractor/SKILL.md)）。

## 下一步

```
skill_view("sia-spec-step-recommend")
```
