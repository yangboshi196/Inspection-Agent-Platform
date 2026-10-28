---
name: sia-spec-step-recommend
description: >-
  Pipeline step 4/5: verify region/algorithm recommendations on draft rules; remediate
  empty ids. Triggers: 步骤4, 推荐确认, 推荐为空.
version: 1.0.0
author: sia
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [specification, pipeline, step, recommend, sia]
    related_skills: [sia-spec-pipeline, sia-spec-step-extract, sia-spec-step-review]
---

# 流水线步骤 4/5：推荐确认

抽取 API 已写入推荐字段；本步**验证**并记录空缺，不重复全量抽取。

## 前置条件

- `pipeline_context.step` === `extract_done`
- `extract.created_rule_ids` 非空（为空则回到步骤 2 调 `topic`/`max_rules` 或步骤 3 重抽）

## 本步动作

### 1. 拉取草稿规则

```bash
curl -s "${PLATFORM}/api/spec/rules?status=draft" \
  -H "Authorization: Bearer ${TOKEN}"
```

筛选 `doc_id` 属于 `pipeline_context.doc_ids` 且 `rule_id` 在 `created_rule_ids` 内。

### 2. 检查推荐字段

对每条规则统计：

- `recommended_regions` / `recommended_regions_json` 是否为空
- `recommended_algorithms` / `recommended_algorithms_json` 是否为空

### 3. 补救（可选）

若大量为空：

- 查阅 [sia-spec-rule-recommender](../sia-spec-rule-recommender/SKILL.md)
- 对照 `GET /api/region` 与 `GET /api/algorithm/` 目录
- 对可明确匹配的规则用 `PATCH /api/spec/rules/{rule_id}` 补全 id 与 reasoning（**id 必须来自目录**）

### 4. 写入 `recommend`

```json
{
  "checked_rule_ids": ["..."],
  "empty_region_count": 0,
  "empty_algorithm_count": 1,
  "remediation": ["rule_id xxx 已 PATCH 补充算法 1014"]
}
```

`step` = **`recommend_done`**

## 下一步

```
skill_view("sia-spec-step-review")
```
