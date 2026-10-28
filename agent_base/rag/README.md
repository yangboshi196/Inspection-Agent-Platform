# `rag` — 检索增强（RAG）

知识库：**文档解析 → 分块 → embedding → 写入 Chroma → 检索**；检索能力可通过 **`RagSearchTool`** 注册到 `ToolRegistry`，供 Agent 调用。

## 架构概览

```
rag/
  config.py / config.json    ← 知识库配置解析与示例配置
  knowledge_base.py          ← 入库与检索主逻辑
  chroma_vector_store.py     ← Chroma 集合封装
  chunking.py                ← 分块策略
  embedded_chunk.py          ← 分块 + 向量结构
  doc_vision_enrich.py       ← PDF/DOCX 插图提取与多模态描述插入正文
  rag_search_tool.py         ← 封装为 Tool（rag_search_<kb_id>）

识图/进度相关文案位于上级包：SIA_agent/prompts/rag/
  doc_image_caption.txt, vision_inline.json, vision_progress.txt
```

## 核心流程

### 入库（`KnowledgeBase.ingest_file` / `ingest_dir`）

```
.txt / .md / .pdf / .docx
  ↓
文本提取（pypdf.PdfReader / python-docx 等）
  ↓
可选 vision_paragraph：doc_vision_enrich 提取嵌入图 → visual 模型描述 → 插入正文
  ↓
chunking（fixed / paragraph / vision_paragraph）
  ↓
ModelManager.call_embedding
  ↓
ChromaVectorStore 写入
```

### 检索（`KnowledgeBase.search`）

```
query → embedding → Chroma 相似检索 → 返回 contexts（文本、分数、来源等）
```

## 公开接口

### `KnowledgeBase`（`knowledge_base.py`）

| 方法 | 说明 |
|------|------|
| `ingest_file(...)` | 单文件入库 |
| `ingest_dir(...)` | 扫描目录入库 |
| `rebuild()` | 按配置重建本知识库 collection |
| `search(...)` | 向量检索 |

### `ChromaVectorStore`（`chroma_vector_store.py`）

| 方法 | 说明 |
|------|------|
| `upsert_chunks(...)` | 写入/更新分块 |
| `query_similar_chunks(...)` | 相似检索 |
| `delete_by_document_name` / `clear` | 维护索引 |

### 分块策略（`chunking.py`）

| 策略 | 说明 |
|------|------|
| `fixed` | 固定窗口 + 重叠 |
| `paragraph` | 按段落 |
| `vision_paragraph` | 插图描述并入正文后按段落分块 |

### `RagSearchTool`（`rag_search_tool.py`）

将 `KnowledgeBase.search` 暴露为工具，名称形如 **`rag_search_<知识库 id>`**。入参含 `query`，可选 `top_k`、`filters`、`need_citation`。

## 配置（`config.json`）

示例见仓库内 `rag/config.json`。字段包含知识库 `id`、`doc_dir`、`persist_dir`、`embedding_model_name`、`split_strategy`、`chunk_size`、`retrieval` 等；**部署时需把路径改成你的实际数据目录**。

## vision_paragraph 说明

对 PDF/DOCX 中嵌入图片：`doc_vision_enrich.py` 抽取图片字节 → `ModelManager.call_visual` → 使用 `prompts/rag/doc_image_caption.txt` 等模板生成描述 → 插入正文后再分块。

入库阶段若传入进度回调，可发出识图进度事件（实现细节见 `doc_vision_enrich.py` / `knowledge_base.py`）。

## 已知限制

- `retrieval.enable_rerank` 等若为占位，以代码为准
- Chroma 侧可使用占位 embedding 维度，真实向量由 `ModelManager` 计算后写入 metadata

## 开发注意事项

1. **路径**：`doc_dir` / `persist_dir` 建议按环境单独配置，勿硬编码他人机器路径。
2. **增量入库**：同名文档替换策略见 `ingest_file` 参数与实现。
3. **Agent 侧**：`ReActAgent` 对 `rag_search_*` 工具的 observation 会使用缩短格式，避免把长原文塞进推理链。
