---
name: sia-knowledge-pipeline
description: >-
  Use for the full sia knowledge-base pipeline: document upload, text governance,
  Milvus vectorization ingest, specification rule extraction, region/algorithm
  recommendation, and MySQL persistence. Triggers: 知识库, 上传文档, 向量化, 入库,
  规范抽取, 知识库全流程, Milvus, 全新向量化, 全新抽取, 安全生产规范.
version: 1.0.0
author: sia
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [knowledge, pipeline, milvus, specification, sia, 知识库]
    related_skills: [sia-spec-rule-extractor, sia-spec-rule-recommender, sia-spec-pipeline]
---

# sia 知识库流水线

## 何时启用（Hermes 自动识别）

用户提到以下任一意图时，**必须先** `skill_view("sia-knowledge-pipeline")` 或更具体的子 skill：

- 上传制度/规范文档、知识库入库、向量化、Milvus 分片
- 规范抽取、全新抽取、抽不到数据、显示 0 条规范
- 区域推荐、算法推荐、智能推荐为空
- **多角色分步流水线**（项目经理→产品经理→抽取→推荐→审核）

子 skill 分工：

| 场景 | 加载 |
|------|------|
| 全流程 / 不确定从哪步开始 | `sia-knowledge-pipeline` |
| **多角色串行编排（5 步）** | [sia-spec-pipeline](../sia-spec-pipeline/SKILL.md) |
| 仅抽取 / 重抽 / 0 条 | `sia-spec-rule-extractor` |
| 仅推荐区域或算法 | `sia-spec-rule-recommender` |

## 适用场景

用户上传规范/制度文档，需要完成：**治理 → 分片向量化 → 规范抽取 → 区域/算法推荐 → MySQL 持久化**。

## 标准流程

### 1. 上传文档

```http
POST /api/document/
Content-Type: multipart/form-data

file=<文档>
doc_type=<分类>
```

### 2. 向量化入库（含治理 + 句级分块 + Milvus HNSW）

```http
POST /api/knowledge/ingest
{
  "document_id": "<文档 UUID>",
  "kb_id": "default",
  "replace": true,
  "max_chars": 900,
  "overlap": 120
}
```

流水线阶段：
- `extract`：多格式纯文本抽取
- `govern`：清洗、脱敏（手机/身份证/邮箱）、去噪（页眉页脚）
- `chunk`：空行段落 + 句号边界 + 字符窗口
- `embed`：本地 Qwen3-Embedding-0.6B
- `commit`：Milvus collection（HNSW + COSINE）

### 3. 规范抽取 + 智能推荐

由两个专用 **Agent 角色** 串联（非 Hermes 主对话 Agent）：

| 角色 id | Skill | 职责 |
|---------|-------|------|
| `spec_rule_entity_recognizer` | [sia-spec-rule-extractor](../sia-spec-rule-extractor/SKILL.md) | 从 Milvus 摘录识别规范实体 |
| `spec_region_algorithm_matcher` | [sia-spec-rule-recommender](../sia-spec-rule-recommender/SKILL.md) | 匹配适用区域与推荐算法 |

角色注册表：`agent_base/prompts/specification/agents.json`  
运行时封装：`inspection_platform/specification/agent_roles.py`

```http
POST /api/spec/rules/extract/preflight
{ "kb_id": "default", "doc_ids": ["<document_id>"] }

POST /api/spec/rules/extract
{
  "kb_id": "default",
  "doc_ids": ["<document_id>"],
  "topic": "安全生产 现场管理",
  "max_rules": 10,
  "persist": true
}
```

抽取结果写入 `spec_rule`（MySQL）：
| 字段 | 含义 |
|------|------|
| `name` | 标题 |
| `desc` | 适用场景 |
| `requirements` | 具体要求 |
| `recommended_regions_json` | 适用区域 id 数组 |
| `region_reasoning` | 适用说明 |
| `recommended_algorithms_json` | 推荐算法 id 数组 |
| `algorithm_reasoning` | 推荐说明 |

推荐匹配输入：
- `GET /api/region` — 区域目录（id、name、desc）
- `GET /api/algorithm/` — 算法目录（algorithm_id、name、desc）

LLM 通过 **ModelManager + SiliconFlow**（`platform_call_chat`）完成语义匹配，id 必须来自上述目录。

### 4. 发布

```http
POST /api/spec/rules/{rule_id}/publish
```

已发布规则同步至 Milvus `spec_rules` collection。

## 关键代码路径

| 模块 | 路径 |
|------|------|
| 数据治理 | `inspection_platform/knowledge/preprocess.py` |
| 分块 | `inspection_platform/knowledge/chunk.py` |
| 入库流水线 | `inspection_platform/knowledge/ingest_pipeline.py` |
| Milvus HNSW | `inspection_platform/app/vector/milvus_store.py` |
| 规范抽取 Agent | `inspection_platform/specification/extractor.py` |
| 区域/算法推荐 Agent | `inspection_platform/specification/recommender.py` |
| Agent 角色注册 | `inspection_platform/specification/agent_roles.py` |
| 角色清单 | `agent_base/prompts/specification/agents.json` |
| 抽取 Prompt | `agent_base/prompts/specification/rule_entity_recognition.txt` |
| 推荐 Prompt | `agent_base/prompts/specification/match_regions_algorithms.txt` |
| 抽取 Skill | `hermes_agent/skills/sia-spec-step-extract/SKILL.md` |
| 多角色总控 Skill | `hermes_agent/skills/sia-spec-pipeline/SKILL.md` |
| 推荐 Skill | `hermes_agent/skills/sia-spec-rule-recommender/SKILL.md` |
| 前端知识库 | `webui/src/platform/admin/KnowledgePage.tsx` |

## 注意事项

- Embedding 维度为 **1024**（Qwen3-Embedding-0.6B）；更换模型后需 `replace: true` 重新 ingest。
- Chat 走 ModelManager + SiliconFlow（`SIA_CHAT_MODEL`）；需配置 `.env` 中 `SILICONFLOW_API_KEY`。
- 区域/算法为多 id 绑定（JSON 数组），非单 FK。
