---
name: sia-spec-step-product-manager
description: >-
  Pipeline step 2/5: product manager sets topic, max_rules and acceptance criteria.
  Requires step project_manager_done. Triggers: 产品经理, 步骤2, 抽取策略.
version: 1.0.0
author: sia
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [specification, pipeline, step, product-manager, sia]
    related_skills: [sia-spec-pipeline, sia-spec-step-project-manager, sia-spec-step-extract]
---

# 流水线步骤 2/5：产品经理

## 前置条件

- `pipeline_context.step` === `project_manager_done`
- 已存在 `pipeline_context.plan`

否则停止并提示先执行步骤 1。

## 本步动作

1. 阅读 `plan` 与 `goal`
2. 按 [role-prompt.txt](references/role-prompt.txt) 产出 `strategy`
3. 设置 `step` = `product_manager_done`
4. 向用户确认 `topic` 与 `max_rules`

## 下一步

```
skill_view("sia-spec-step-extract")
```
