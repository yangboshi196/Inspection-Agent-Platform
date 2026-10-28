"""ModelManager 模块 - 多模型统一调度与配置管理

本模块提供：
- ModelManager  : 统一调度入口（call_chat/embedding/visual/voice），含重试/降级/限流
- SecretResolver: API Key 引用解析（env:/secret:/明文）
- ModelSpec/ModelSource : 模型配置结构

配置格式（provider-first）：
    {
        "siliconflow": {
            "chat": [{"name": "deepseek-ai/DeepSeek-V4-Flash", "impl": "openai_compat", ...}],
            "embedding": [...]
        }
    }

Usage:
    from SIA_agent.model_manager import ModelManager

    mm = ModelManager.from_file("models.json")
    resp = mm.call_chat(ChatRequest(...))
    for chunk in mm.call_chat_stream(req):
        print(chunk, end="")
"""

from .manager import ModelManager
from .secrets import SecretResolver

__all__ = ["ModelManager", "SecretResolver"]

