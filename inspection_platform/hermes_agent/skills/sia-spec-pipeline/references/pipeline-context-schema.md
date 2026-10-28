# pipeline_context 传递协议

各步骤 Skill **必须**维护并传递同一份 `pipeline_context`（JSON 对象）。每步结束时更新 `step` 字段，禁止跳步。

## 初始结构（总控 Skill 创建）

```json
{
  "version": 1,
  "step": "init",
  "kb_id": "default",
  "doc_ids": ["<document_id>"],
  "goal": "用户原始目标描述",
  "platform_base": "http://127.0.0.1:8001",
  "auth": { "token": "<Bearer token 或空>" }
}
```

## 各步完成后 `step` 取值

| step 值 | 含义 |
|---------|------|
| `init` | 已初始化，未开始 |
| `project_manager_done` | 步骤1完成 |
| `product_manager_done` | 步骤2完成 |
| `extract_done` | 步骤3完成 |
| `recommend_done` | 步骤4完成 |
| `review_done` | 步骤5完成（流水线结束） |

## 步骤产出字段

### 步骤1 项目经理 → `plan`

```json
{
  "scope": "本批次处理范围",
  "risks": ["风险1"],
  "deliverables": ["可交付：N 条草稿规范"],
  "notes": "给后续角色的备注"
}
```

### 步骤2 产品经理 → `strategy`

```json
{
  "topic": "安全生产 现场管理",
  "max_rules": 10,
  "extract_focus": ["义务条款", "禁止性规定", "量化指标"],
  "acceptance_criteria": ["每条须可核查", "须关联来源 doc_id"]
}
```

### 步骤3 规范抽取 → `extract`

```json
{
  "preflight_ready": true,
  "created_rule_ids": ["..."],
  "rules_count": 3,
  "warnings": []
}
```

### 步骤4 推荐确认 → `recommend`

```json
{
  "checked_rule_ids": ["..."],
  "empty_region_count": 0,
  "empty_algorithm_count": 0,
  "remediation": []
}
```

### 步骤5 审核 → `review`

```json
{
  "approved_rule_ids": ["..."],
  "rejected_rule_ids": [],
  "issues": [{ "rule_id": "...", "severity": "warn", "message": "..." }],
  "summary": "审核结论一句话"
}
```

## 传递规则

1. 每步开始时读取当前 `pipeline_context`（用户消息或上一步输出的 JSON 代码块）。
2. 每步结束时向用户展示**完整**更新后的 `pipeline_context`（便于下一步复制或续跑）。
3. 任一步 `step` 不符合前置条件时**停止**，不进入下一步。
4. 平台 API 调用使用 `platform_base` + `Authorization: Bearer {auth.token}`。
