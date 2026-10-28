---
name: sia-spec-rule-extractor
description: >-
  Use when extracting specification rules from vectorized knowledge-base documents,
  re-extracting rules, or debugging zero-rule / failed extraction (抽不到数据、0条规范).
  Runs spec_rule_entity_recognizer via POST /api/spec/rules/extract after Milvus preflight.
  Triggers: 规范抽取, 规则识别, 从文档抽规范, 全新抽取, 抽不到数据, 0条规范,
  知识库抽取, 规范实体识别, 规则持久化, spec_rule_extract.
version: 1.0.0
author: sia
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [specification, knowledge, extraction, llm, sia, 规范抽取, 全新抽取]
    related_skills: [sia-knowledge-pipeline, sia-spec-rule-recommender, sia-spec-pipeline, sia-spec-step-extract]
---

# sia 规范实体识别（Agent 角色）

## 何时启用（Hermes 自动识别）

用户提到 **规范抽取、全新抽取、抽不到数据、0 条规范、规则识别、预检未通过** 时加载本 skill。

**多角色 5 步流水线**请用总控 [sia-spec-pipeline](../sia-spec-pipeline/SKILL.md)（步骤 3 为 [sia-spec-step-extract](../sia-spec-step-extract/SKILL.md)）。

若还需上传/向量化，先加载 [sia-knowledge-pipeline](../sia-knowledge-pipeline/SKILL.md)。

平台内置 Agent 角色 **`spec_rule_entity_recognizer`**（规范实体识别助手），从已向量化文档摘录中提取可入库的规范实体。

## Agent 角色元数据

| 字段 | 值 |
|------|-----|
| `id` | `spec_rule_entity_recognizer` |
| `label` | 规范实体识别助手 |
| `purpose` | `spec_rule_extract` |
| System Prompt | `agent_base/prompts/specification/rule_entity_recognition.txt` |
| 角色注册 | `agent_base/prompts/specification/agents.json` |
| 运行时封装 | `inspection_platform/specification/agent_roles.py` |
| 编排入口 | `inspection_platform/specification/extractor.py` |

## 何时启用

- 用户上传规范/制度文档后需要**抽取规则条目**
- 用户对已有文档执行「全新抽取」
- 需要调试「为什么抽不到数据」——先确认预检与 Milvus 分片

**不要用于：** 区域/算法推荐（见 [sia-spec-rule-recommender](../sia-spec-rule-recommender/SKILL.md)）、直接向量化入库（见 [sia-knowledge-pipeline](../sia-knowledge-pipeline/SKILL.md)）。

## 前置条件（必须满足）

1. 文档已上传：`POST /api/document/`
2. 已向量化：`POST /api/knowledge/ingest` 且 `chunks > 0`
3. 预检通过：`POST /api/spec/rules/extract/preflight` → `ready: true`

## 标准调用（推荐）

```http
POST /api/spec/rules/extract/preflight
{ "kb_id": "default", "doc_ids": ["<document_id>"] }

POST /api/spec/rules/extract
{
  "kb_id": "default",
  "doc_ids": ["<document_id>"],
  "topic": "安全生产 现场管理",
  "max_rules": 10,
  "persist": true,
  "re_extract": false
}
```

平台内部流程：

1. Milvus 向量检索摘录（topic + 义务/指标等 query）
2. 拼装 user 消息（`build_rule_entity_user_message`）
3. 调用 `RULE_ENTITY_RECOGNIZER` → `platform_call_chat`（SiliconFlow DeepSeek-V3.2）
4. 解析 JSON 数组 → 逐条触发推荐 Agent → MySQL `spec_rule`

## LLM 输入 / 输出契约

### System（角色定义）

完整内容见 `rule_entity_recognition.txt`。核心约束：

- **零幻觉**：不得编造数值、条款号、标准号
- **输出**：纯 JSON 数组，每条 5 字段：`name` / `desc` / `source` / `requirements` / `algorithm_guidance`
- **拆分**：多条独立义务 → 多条规则；相同约束 → 合并
- **上限**：不超过 `max_rules`

### User（运行时拼装）

```
摘录来自知识库 kb_id='default'；规则为全局条目，设备与区域在巡检业务中绑定。
用户关注主题：<topic>
最多输出 <max_rules> 条规则。

【原文摘录】
### 文档片段 doc_id=... score=0.812
<检索到的文本片段>

请只输出 JSON 数组，不要其它说明文字。
```

### 输出示例

```json
[
  {
    "name": "深基坑专项方案与专家论证",
    "desc": "适用于开挖深度超过 5m 的基坑工程。",
    "source": "施工方案",
    "requirements": "开挖深度超过 5m 时，必须编制专项施工方案并组织专家论证。",
    "algorithm_guidance": "可通过现场视频巡检识别支护是否到位。"
  }
]
```

## Hermes 中手动复现（调试用）

若需在不走完整 API 的情况下验证 Prompt：

1. 将 system prompt 读入：`agent_base/prompts/specification/rule_entity_recognition.txt`
2. 用 `terminal` 调平台 API 获取预检与摘录上下文，或先 `POST /api/knowledge/query` 检索片段
3. 按上文 user 模板拼装后调用 LLM（与平台相同模型 `deepseek-ai/DeepSeek-V3.2`）
4. 校验输出为合法 JSON 数组

## 故障排查

| 现象 | 原因 | 处理 |
|------|------|------|
| 预检「尚未向量化」 | Milvus 无分片 | 先 `POST /api/knowledge/ingest` |
| 返回 0 条 + note | 摘录过短或与 topic 无关 | 调整 `topic` 或重新 ingest |
| LLM apiKey 错误 | ModelManager 未读到 Key | 检查 `.env` `SILICONFLOW_API_KEY` |
| 持久化失败 | MySQL 事务/字段错误 | 查平台日志 `规则持久化失败` |

## 代码引用

```python
from inspection_platform.specification.agent_roles import (
    RULE_ENTITY_RECOGNIZER,
    build_rule_entity_user_message,
    build_chat_request,
)
```
