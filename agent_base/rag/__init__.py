"""RAG 模块 - 知识库构建与检索

本模块实现文档解析→分块→向量化→检索的完整 RAG 流程：

核心组件：
- KnowledgeBase       : 知识库管理（ingest_file/rebuild/search）
- ChromaVectorStore   : Chroma 向量库封装（add_chunks/query_similar）
- chunking           : 文本分块策略（fixed/paragraph/vision_paragraph）
- RagSearchTool       : RAG 检索工具（Agent 可调用的工具）
- EmbeddedChunk       : 含向量 + metadata 的分块结构

分块策略：
- fixed          : 固定窗口 + 重叠（适用通用场景）
- paragraph      : 按空行分段 + 按大小合并（语义友好）
- vision_paragraph: 先多模态识图再按段落分块（适合图文混合文档）

Usage:
    from SIA_agent.rag import KnowledgeBase, KnowledgeBaseConfig

    config = KnowledgeBaseConfig(...)
    kb = KnowledgeBase(config, model_manager=mm)
    kb.ingest_file(Path("docs/report.pdf"), request_id="req-001")
    result = kb.search(query="报告结论是什么", request_id="req-001")
"""

from .config import KnowledgeBaseConfig, parse_rag_config
from .embed_texts import embed_texts
from .embedded_chunk import EmbeddedChunk
from .knowledge_base import KnowledgeBase
from .rag_search_tool import RagSearchTool

__all__ = [
    "KnowledgeBase",
    "KnowledgeBaseConfig",
    "parse_rag_config",
    "RagSearchTool",
    "EmbeddedChunk",
    "embed_texts",
]
