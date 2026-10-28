"""环境变量读取：支持「新名优先、旧名兼容」。

规范名（建议在新部署中只使用这些）::

    SIA_SPEC_SQLITE_PATH      — 规范 SQLite
    SIA_SPEC_FILES_ROOT       — 规范原文文件根目录（历史变量）
    SIA_DOC_SQLITE_PATH       — 文档库 SQLite
    SIA_DOC_FILES_ROOT        — 文档原文根目录
    SIA_REGION_SQLITE_PATH    — 区域元数据 SQLite
    inspection_platform_EMBEDDING_MODEL — （已弃用）平台向量化现默认本地 bge-m3
    SIA_EMBEDDING_MODEL_PATH    — 本地 SentenceTransformer 目录（默认识别 models 下 Qwen3-Embedding-0.6B）
    SIA_EMBEDDING_DEVICE        — ST 后端设备：cuda（默认）| cpu | auto
    SIA_EMBEDDING_BACKEND       — siliconflow | vllm | sentence_transformer
    SILICONFLOW_API_KEY            — 硅基流动 Chat API Key（sk- 格式）
    SILICONFLOW_CHAT_BASE_URL      — 硅基流动 Chat 根地址（默认 https://api.siliconflow.cn/v1）
    SILICONFLOW_EMBED_API_KEY      — 硅基流动 Embedding API Key（可与 Chat 共用同一 sk-）
    SILICONFLOW_EMBED_BASE_URL     — Embedding 根地址（默认 https://api.siliconflow.cn/v1）
    SILICONFLOW_EMBED_MODEL        — Embedding 模型（默认 Qwen/Qwen3-Embedding-0.6B）
    SIA_CHAT_MODEL              — 平台 LLM 默认模型（默认 deepseek-ai/DeepSeek-V4-Flash）
    SIA_INSPECTION_WORK_CHAT_MODEL — 巡检 AI 生成 Chat 模型
"""

from __future__ import annotations

import os


def env_first(*names: str) -> str:
    """按顺序读取环境变量，返回第一个非空字符串，否则空串。"""
    for name in names:
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    return ""
