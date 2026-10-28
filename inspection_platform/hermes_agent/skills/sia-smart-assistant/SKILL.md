---
name: sia-smart-assistant
description: >-
  Use when the user interacts with the sia 智能巡检助手 page: knowledge base
  ingest/query, inspection work drafting and creation, or inspection event
  triage. Triggers: 智能巡检助手, 智能助手, 触发任务, 巡检编排, 上传文档, 知识库,
  创建巡检业务, 巡检事件.
version: 1.1.0
author: 南京物盟信息技术有限公司
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [sia, smart-assistant, knowledge, inspection, events]
    related_skills: [sia-knowledge-pipeline, sia-algorithm-test]
---

# sia 智能巡检助手

在平台内完成 **知识库 → 巡检业务编排 → 事件处置** 的用户端闭环。依赖 MCP toolset **`mcp-inspection_platform`**（`SIA_*` 工具）。

## 何时启用

- 用户在「智能巡检助手」页对话，或提到：触发任务、巡检编排、上传文档、知识库、创建巡检业务、处理巡检事件
- 需要将文档入库并向量化、按自然语言生成巡检业务草案、确认后落库上线
- 需要列出/更新最近巡检事件状态

**不要用于：** VAIO 视频算法联调（用 `sia-algorithm-test`）、规范抽取流水线细节（用 `sia-knowledge-pipeline` 作参考）。

## 前置检查（静默执行，失败再告知用户）

1. 确认 Chat 中可见 **`SIA_*`** 工具；若无，提示用户执行 **`/reload-mcp`**
2. 确认 `~/.hermes/config.yaml` 含 `mcp_servers.inspection_platform`（平台启动时会自动注册；也可 `POST /api/platform/register-hermes-mcp`）
3. MCP 进程 cwd 为仓库根目录，`PYTHONPATH` 含 `sia/`

## 交互流程

### Step 1 — 理解意图

用 **`clarify`** 确认用户目标（单选或多轮）：

| 意图 | 说明 |
|------|------|
| **知识库** | 列出文档 → 向量化入库 → 检索问答 |
| **巡检业务** | 按描述生成草案 → 展示 → 确认后创建/上线 |
| **巡检事件** | 列出最近事件 → 更新状态/处理人 |
| **组合** | 先知识库再编排，或编排后关注事件 |

### Step 2 — 知识库（可选）

1. **`SIA_list_documents`** — 展示文档 id、名称
2. 用户指定 document_id 后 **`SIA_ingest_knowledge`**（`kb_id` 默认 `default`，`replace=true`）
3. 用户提问时 **`SIA_query_knowledge`**（`top_k` 5–8），引用命中片段回答

若用户刚在页面上传文件，提示其告知 **document_id**（上传成功 toast 会显示）。

### Step 3 — 巡检业务（可选）

1. 收集 **topic**（巡检目的/区域/规范关注点）；可选 **region_id**
2. **`SIA_generate_inspection_work`** — 返回 **draft only**，不自动落库
3. 用 Markdown 表格向用户展示：`name`、`desc`、`rule_set`、`algorithm_set`、`equipment_set` 摘要
4. 用户确认后：
   - **`SIA_create_inspection_work`** — `payload_json` 为完整 work JSON（建议 `work_status: offline` 先草稿）
   - 若需立即运行：**`SIA_patch_inspection_work`** — `{"work_status":"online"}`
5. 需要查看已有业务：**`SIA_list_inspection_works`**

### Step 4 — 巡检事件（可选）

1. **`SIA_list_inspection_events`** — 可按 `status`、`work_id` 过滤
2. 用户选定 event_id 后 **`SIA_patch_inspection_event`** — 例如 `{"status":"resolved","handler":"张三"}`

## 工具调用清单（Agent 自检）

```
clarify                    → 意图
SIA_list_documents
SIA_ingest_knowledge
SIA_query_knowledge
SIA_generate_inspection_work
SIA_create_inspection_work
SIA_patch_inspection_work
SIA_list_inspection_works
SIA_list_inspection_events
SIA_patch_inspection_event
```

## 故障处理

| 现象 | 处理 |
|------|------|
| 无 `SIA_*` 工具 | `/reload-mcp`；检查 `mcp_servers.inspection_platform` |
| `SIA_*` 报 `No module named 'chromadb'` | `pip install chromadb`（依赖来自 `agent_base/rag/` 与 `agent_base/context/`）|
| `SIA_*` 报 `No module named 'sqlalchemy'` | `pip install sqlalchemy`（文档库服务所需）|
| 向量化失败 / Milvus | 检查 `MILVUS_HOST`/`MILVUS_PORT`，平台日志 |
| 知识库/文档工具多个依赖报错 | 平台环境可能未完整安装，建议在 venv 内执行 `pip install chromadb sqlalchemy pymilvus` |
| 生成巡检业务 ValueError | 补全设备/规范/区域数据后再试 |
| create 409 | `work_id` 冲突，换 id 或 patch 已有业务 |

## 参考

- 知识库流水线：[sia-knowledge-pipeline](../sia-knowledge-pipeline/SKILL.md)
- 视频算法测试：[sia-algorithm-test](../sia-algorithm-test/SKILL.md)
