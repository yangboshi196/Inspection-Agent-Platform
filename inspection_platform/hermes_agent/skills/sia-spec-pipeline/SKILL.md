---
name: sia-spec-pipeline
description: >-
  Orchestrate multi-role specification workflow in strict serial steps via child
  skills: project manager, product manager, extract, recommend verify, compliance
  review. Triggers: 多角色流水线, 规范流水线, spec pipeline, 项目经理 产品经理 审核,
  串行编排, 分步抽取规范.
version: 1.0.0
author: sia
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [specification, pipeline, orchestration, sia, 多角色]
    related_skills:
      - sia-spec-step-project-manager
      - sia-spec-step-product-manager
      - sia-spec-step-extract
      - sia-spec-step-recommend
      - sia-spec-step-review
      - sia-knowledge-pipeline
---

# sia 规范多角色串行流水线（总控）

通过 **5 个子 Skill 严格串行** 完成：项目经理 → 产品经理 → 规范抽取 → 推荐确认 → 合规审核。

**不要**在本 Skill 内直接执行抽取或推荐；**必须**按序加载子 Skill 并传递 `pipeline_context`。

## 何时启用

- 用户要求「多角色」「分步」「流水线」「项目经理/产品经理/审核」
- 规范抽取需要可观测、可暂停、可逐步汇报
- 调试抽不到数据、推荐为空、需分步排查

仅上传/向量化、不需多角色：用 [sia-knowledge-pipeline](../sia-knowledge-pipeline/SKILL.md)。

## 前置条件

1. 文档已上传且已向量化（`POST /api/knowledge/ingest` 且 `chunks > 0`）
2. 已知 `document_id`（与 `doc_ids[0]` 一致）
3. 能访问平台 `http://127.0.0.1:8001`（或用户指定的 `platform_base`）

若未向量化，先执行 knowledge-pipeline 的步骤 1–2，再回本总控。

## 串行步骤表（禁止跳步、禁止并行）

| 序号 | Skill name | 完成后 `step` |
|------|------------|---------------|
| 1 | `sia-spec-step-project-manager` | `project_manager_done` |
| 2 | `sia-spec-step-product-manager` | `product_manager_done` |
| 3 | `sia-spec-step-extract` | `extract_done` |
| 4 | `sia-spec-step-recommend` | `recommend_done` |
| 5 | `sia-spec-step-review` | `review_done` |

## 总控执行协议（必须遵守）

### A. 初始化 `pipeline_context`

从用户输入解析 `doc_ids`、`goal`、`kb_id`（默认 `default`）。登录拿 token：

```bash
TOKEN=$(curl -s -X POST "${PLATFORM}/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"account":"zhang.gong","password":"demo1234"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")
```

将 `PLATFORM` 设为 `http://127.0.0.1:8001`（或用户环境）。

初始 JSON 见 [pipeline-context-schema.md](references/pipeline-context-schema.md)。

向用户确认后开始步骤 1。

### B. 逐步加载子 Skill

对每一步 **必须**：

```
skill_view("<step-skill-name>")
```

然后**严格按该 Skill 正文执行**，不得合并多步。

### C. 步骤闸门

进入步骤 N 前检查 `pipeline_context.step`：

| 要进入的步骤 | 要求的上一步 `step` |
|-------------|-------------------|
| 2 产品经理 | `project_manager_done` |
| 3 抽取 | `product_manager_done` |
| 4 推荐确认 | `extract_done` |
| 5 审核 | `recommend_done` |

不满足则停止并报告。

### D. 每步结束

1. 向用户汇报本步摘要
2. 输出完整 `pipeline_context` JSON（供续跑或排错）
3. 询问是否继续下一步（除非用户事先要求全自动跑完）

### E. 全自动模式

用户明确说「全自动跑完」时，连续执行 1→5，仅在失败或审核有 `rejected` 时暂停。

## 启动命令

用户可输入：

```
/sia-spec-pipeline doc_id=<uuid> goal=安全生产现场管理规范抽取
```

或对话描述目标后，你先初始化 `pipeline_context`，再 `skill_view("sia-spec-step-project-manager")`。

## 故障与续跑

- 中断后用户粘贴上次输出的 `pipeline_context`，从 `step` 对应的**下一步**继续
- `extract` 失败：可仅重跑步骤 3（保持 `strategy` 不变或回到步骤 2 调参）

## 参考

- 上下文协议：[references/pipeline-context-schema.md](references/pipeline-context-schema.md)
- 平台 Agent 角色：`agent_base/prompts/specification/agents.json`
