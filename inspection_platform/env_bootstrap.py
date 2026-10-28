"""启动时补全 LLM / Embedding 所需环境变量（硅基流动：项目 .env 为唯一来源）。"""

from __future__ import annotations

import os
from pathlib import Path

from inspection_platform.app.config import repo_root

_DEFAULT_CHAT_BASE = "https://api.siliconflow.cn/v1"
_DEFAULT_EMBED_BASE = "https://api.siliconflow.cn/v1"
_DEFAULT_EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"
_DEFAULT_CHAT_MODEL = "deepseek-ai/DeepSeek-V4-Flash"

# 平台硅基流动凭证与模型：仅读项目根 .env，不回退 Hermes / 历史网关
_SILICONFLOW_PROJECT_KEYS = frozenset(
    {
        "SILICONFLOW_API_KEY",
        "SILICONFLOW_CHAT_BASE_URL",
        "SILICONFLOW_EMBED_API_KEY",
        "SILICONFLOW_EMBED_BASE_URL",
        "SILICONFLOW_EMBED_MODEL",
        "SIA_OPENAI_API_KEY",
        "SIA_OPENAI_EMBED_API_KEY",
        "SIA_OPENAI_EMBED_BASE_URL",
        "SIA_EMBEDDING_BACKEND",
        "inspection_platform_EMBEDDING_MODEL",
        "SIA_CHAT_MODEL",
        "SIA_INSPECTION_WORK_CHAT_MODEL",
    }
)

# Hermes Agent 等可选第三方（与平台 LLM 无关）
_OPTIONAL_HERMES_KEYS = (
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_BASE_URL",
)


def _parse_dotenv_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            out[key] = val
    return out


def project_env_value(name: str) -> str | None:
    """读取项目根 ``.env`` 中的变量（不依赖 ``os.environ``）。"""
    val = (_parse_dotenv_file(repo_root() / ".env").get(name) or "").strip()
    return val or None


def project_env_values() -> dict[str, str]:
    return _parse_dotenv_file(repo_root() / ".env")


def apply_project_dotenv(*, override: bool = True) -> bool:
    """加载仓库根目录 ``.env``。"""
    from dotenv import load_dotenv

    path = repo_root() / ".env"
    if not path.is_file():
        return False
    load_dotenv(path, override=override)
    return True


def _apply_siliconflow_from_project() -> list[str]:
    """将项目 ``.env`` 中的硅基流动 Embedding / Chat 配置写入 ``os.environ``。"""
    project = project_env_values()
    applied: list[str] = []
    for name in _SILICONFLOW_PROJECT_KEYS:
        val = (project.get(name) or "").strip()
        if not val:
            continue
        if os.environ.get(name) != val:
            os.environ[name] = val
            applied.append(name)

    # Chat Key 未单独配置时，与 Embedding 共用同一 sk-
    embed_key = (project.get("SILICONFLOW_EMBED_API_KEY") or "").strip()
    chat_key = (project.get("SILICONFLOW_API_KEY") or "").strip()
    if embed_key and not chat_key:
        os.environ["SILICONFLOW_API_KEY"] = embed_key
        applied.append("SILICONFLOW_API_KEY<-EMBED")

    if not os.environ.get("SILICONFLOW_CHAT_BASE_URL", "").strip():
        os.environ["SILICONFLOW_CHAT_BASE_URL"] = _DEFAULT_CHAT_BASE
        applied.append("SILICONFLOW_CHAT_BASE_URL(default)")
    if not os.environ.get("SILICONFLOW_EMBED_BASE_URL", "").strip():
        os.environ["SILICONFLOW_EMBED_BASE_URL"] = _DEFAULT_EMBED_BASE
        applied.append("SILICONFLOW_EMBED_BASE_URL(default)")
    if not os.environ.get("SILICONFLOW_EMBED_MODEL", "").strip():
        os.environ["SILICONFLOW_EMBED_MODEL"] = _DEFAULT_EMBED_MODEL
        applied.append("SILICONFLOW_EMBED_MODEL(default)")
    if not os.environ.get("SIA_CHAT_MODEL", "").strip():
        os.environ["SIA_CHAT_MODEL"] = _DEFAULT_CHAT_MODEL
        applied.append("SIA_CHAT_MODEL(default)")
    if not os.environ.get("SIA_INSPECTION_WORK_CHAT_MODEL", "").strip():
        os.environ["SIA_INSPECTION_WORK_CHAT_MODEL"] = _DEFAULT_CHAT_MODEL
        applied.append("SIA_INSPECTION_WORK_CHAT_MODEL(default)")
    if not os.environ.get("inspection_platform_EMBEDDING_MODEL", "").strip():
        os.environ["inspection_platform_EMBEDDING_MODEL"] = _DEFAULT_EMBED_MODEL
        applied.append("inspection_platform_EMBEDDING_MODEL(default)")
    if not os.environ.get("SIA_EMBEDDING_BACKEND", "").strip():
        os.environ["SIA_EMBEDDING_BACKEND"] = "openai"
        applied.append("SIA_EMBEDDING_BACKEND(default)")

    return applied


def sync_platform_embed_credentials() -> None:
    """向量化前同步硅基流动 Embedding 凭证（兼容旧调用名）。"""
    sync_platform_siliconflow_credentials()


def sync_platform_siliconflow_credentials() -> None:
    """同步硅基流动 Embedding + Chat 凭证，并清空 OpenAI 客户端缓存。"""
    from inspection_platform.llm.openai_client import invalidate_openai_clients

    apply_project_dotenv(override=True)
    _apply_siliconflow_from_project()
    invalidate_openai_clients()


def bootstrap_platform_env(*, force: bool = False) -> list[str]:
    """
    平台启动环境补全：硅基流动走项目 ``.env``；Hermes 可选变量从 ``~/.hermes`` 补全。

    Returns:
        本次新写入 ``os.environ`` 的变量名列表。
    """
    del force
    apply_project_dotenv(override=True)
    applied = _apply_siliconflow_from_project()

    hermes_home = os.environ.get("HERMES_HOME", "").strip()
    hermes_paths = [Path.home() / ".hermes" / ".env"]
    if hermes_home:
        hermes_paths.insert(0, Path(hermes_home) / ".env")
    merged: dict[str, str] = {}
    for p in hermes_paths:
        merged.update(_parse_dotenv_file(p))

    for name in _OPTIONAL_HERMES_KEYS:
        if os.environ.get(name, "").strip():
            continue
        val = merged.get(name, "").strip()
        if val:
            os.environ[name] = val
            applied.append(name)

    return applied


def reset_model_stack() -> None:
    """环境变量补全后重建 ModelManager 单例。"""
    from inspection_platform import deps
    from inspection_platform.llm.openai_client import invalidate_openai_clients

    invalidate_openai_clients()
    deps._stack = None  # noqa: SLF001
