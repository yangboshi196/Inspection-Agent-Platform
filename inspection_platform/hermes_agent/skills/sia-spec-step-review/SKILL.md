---
name: sia-spec-step-review
description: >-
  Pipeline step 5/5: compliance review of draft rules and recommendations.
  Triggers: 步骤5, 规范审核, 合规审核, 审核推荐.
version: 1.0.0
author: sia
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [specification, pipeline, step, review, sia]
    related_skills: [sia-spec-pipeline, sia-spec-step-recommend]
---

# 流水线步骤 5/5：合规审核

## 前置条件

- `pipeline_context.step` === `recommend_done`
- 已拉取本批草稿规则全文

## 本步动作

1. 按 [role-prompt.txt](references/role-prompt.txt) 审核
2. 可选对每条 `approved_rule_ids` 调用：

```bash
curl -s "${PLATFORM}/api/spec/rules/${RULE_ID}/publish-readiness" \
  -H "Authorization: Bearer ${TOKEN}"
```

机械检查未通过项写入 `issues`（severity: `error`）。

3. 产出 `review`，`step` = **`review_done`**
4. 向用户输出**流水线总结表**：

| 阶段 | 结果 |
|------|------|
| 项目经理 | scope / risks |
| 产品经理 | topic / max_rules |
| 抽取 | rules_count |
| 推荐确认 | empty_*_count |
| 审核 | approved / rejected |

## 流水线结束

- 建议用户到 Web 知识库页查看草稿
- 发布：`POST /api/spec/rules/{rule_id}/publish`（须 publish-readiness 通过）
- 续跑：粘贴 `pipeline_context` 可从任意 `step` 恢复（见总控 Skill）

## 无下一步

本步为终点。若用户要求发布，逐条检查 readiness 后调用 publish API。
