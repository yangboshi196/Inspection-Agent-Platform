---
name: sia-spec-step-project-manager
description: >-
  Pipeline step 1/5: project manager plans scope and deliverables for spec
  extraction. Requires pipeline_context from sia-spec-pipeline. Triggers:
  项目经理, 步骤1, pipeline step 1.
version: 1.0.0
author: sia
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [specification, pipeline, step, project-manager, sia]
    related_skills: [sia-spec-pipeline, sia-spec-step-product-manager]
---

# 流水线步骤 1/5：项目经理

## 前置条件

- 已加载 [sia-spec-pipeline](../sia-spec-pipeline/SKILL.md) 或用户提供了 `pipeline_context`
- `pipeline_context.step` 为 `init` 或缺失（本步为起点）

## 本步动作

1. 读取 `pipeline_context`（`goal`、`doc_ids`、`kb_id`）
2. 以项目经理角色思考（角色定义见 [role-prompt.txt](references/role-prompt.txt)）
3. 产出 `plan` 对象，设置 `step` = `project_manager_done`
4. 向用户汇报计划摘要

## 角色 Prompt

执行前阅读：`skill_view("sia-spec-step-project-manager", file_path="references/role-prompt.txt")`  
或直接使用 [references/role-prompt.txt](references/role-prompt.txt) 中的约束。

## 本步输出示例

```json
{
  "version": 1,
  "step": "project_manager_done",
  "kb_id": "default",
  "doc_ids": ["ac73237c9c99431b811ad33ce071b123"],
  "goal": "安全生产现场管理规范抽取",
  "platform_base": "http://127.0.0.1:8001",
  "auth": { "token": "..." },
  "plan": {
    "scope": "单文档《现场安全生产管理规范细则》",
    "risks": ["需确认已向量化"],
    "deliverables": ["5–10 条可核查草稿规范"],
    "notes": "关注禁止性条款与量化时限"
  }
}
```

## 下一步（必须）

```
skill_view("sia-spec-step-product-manager")
```

并将完整 `pipeline_context` 带入下一步。
