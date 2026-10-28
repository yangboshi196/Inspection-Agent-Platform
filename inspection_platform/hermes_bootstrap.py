"""Hermes 配置引导：平台启动时补齐缺失的主模型配置。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CHAT_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
_DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"


def _model_is_unconfigured(model_val: Any) -> bool:
    if model_val is None:
        return True
    if isinstance(model_val, str):
        return not model_val.strip()
    if isinstance(model_val, dict):
        default = str(model_val.get("default") or model_val.get("name") or "").strip()
        provider = str(model_val.get("provider") or "").strip()
        return not default and not provider
    return True


def _has_siliconflow_credential() -> bool:
    try:
        from hermes_cli.auth import read_credential_pool

        entries = read_credential_pool("custom:siliconflow") or []
        return bool(entries)
    except Exception:
        return False


def _default_model_block() -> dict[str, str]:
    return {
        "provider": "siliconflow",
        "default": _DEFAULT_CHAT_MODEL,
        "base_url": _DEFAULT_BASE_URL,
    }


def _default_providers_block() -> dict[str, Any]:
    return {
        "siliconflow": {
            "name": "siliconflow",
            "api": _DEFAULT_BASE_URL,
            "key_env": "SILICONFLOW_API_KEY",
            "model": _DEFAULT_CHAT_MODEL,
            "models": {
                _DEFAULT_CHAT_MODEL: {},
                "Pro/deepseek-ai/DeepSeek-R1": {},
            },
        },
    }


def _siliconflow_api_key_from_env() -> str:
    from inspection_platform.envutil import env_first

    return env_first("SILICONFLOW_API_KEY")


def _sync_hermes_env_key(api_key: str) -> None:
    """将 SiliconFlow Key 写入 ~/.hermes/.env，供 Hermes CLI 读取。"""
    from hermes_cli.config import get_env_path

    env_path = get_env_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith("SILICONFLOW_API_KEY="):
            out.append(f"SILICONFLOW_API_KEY={api_key}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(f"SILICONFLOW_API_KEY={api_key}")
    env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def ensure_hermes_model_config() -> dict[str, Any]:
    """
    若 ``~/.hermes/config.yaml`` 未配置主模型，或项目 ``.env`` 提供 SiliconFlow Key，
    则写入 SiliconFlow 默认项（不覆盖用户已手动选择的非 siliconflow 提供商）。
    """
    platform_root = Path(__file__).resolve().parent
    hermes_root = platform_root / "hermes_agent"
    if not hermes_root.is_dir():
        return {"updated": False, "reason": "hermes_agent missing"}

    import sys

    root_str = str(hermes_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    try:
        from hermes_cli.config import load_config, save_config
    except Exception as exc:
        return {"updated": False, "reason": f"hermes_cli unavailable: {exc}"}

    config = load_config()
    api_key = _siliconflow_api_key_from_env()
    if api_key:
        try:
            _sync_hermes_env_key(api_key)
        except Exception as exc:
            logger.warning("写入 ~/.hermes/.env SILICONFLOW_API_KEY 失败: %s", exc)

    model_block = config.get("model")
    provider = ""
    if isinstance(model_block, dict):
        provider = str(model_block.get("provider") or "").strip().lower()

    should_update = _model_is_unconfigured(model_block)
    if api_key and provider in ("", "siliconflow", "custom"):
        should_update = True

    if not should_update:
        return {"updated": False, "reason": "model already configured"}

    if api_key:
        config["model"] = {
            "provider": "siliconflow",
            "default": _DEFAULT_CHAT_MODEL,
            "base_url": _DEFAULT_BASE_URL,
        }
        providers = config.get("providers")
        if not isinstance(providers, dict):
            providers = {}
        providers["siliconflow"] = _default_providers_block()["siliconflow"]
        config["providers"] = providers
        save_config(config)
        logger.info("已同步 Hermes model/providers 为 SiliconFlow（%s）", _DEFAULT_CHAT_MODEL)
        return {
            "updated": True,
            "model": config["model"],
            "providers_keys": list((config.get("providers") or {}).keys()),
        }

    if not _has_siliconflow_credential():
        logger.warning(
            "Hermes model 未配置且未找到 custom:siliconflow 凭证；"
            "请在 ~/.hermes/.env 设置 SILICONFLOW_API_KEY 或运行 hermes model"
        )
        return {"updated": False, "reason": "no siliconflow credential"}

    config["model"] = _default_model_block()
    providers = config.get("providers")
    if not isinstance(providers, dict) or not providers:
        config["providers"] = _default_providers_block()

    save_config(config)
    logger.info("已自动补齐 Hermes model/providers（custom + %s）", _DEFAULT_CHAT_MODEL)
    return {
        "updated": True,
        "model": config["model"],
        "providers_keys": list((config.get("providers") or {}).keys()),
    }


def _bundled_skills_dir() -> Path:
    return Path(__file__).resolve().parent / "hermes_agent" / "skills"


def ensure_hermes_skills_config() -> dict[str, Any]:
    """
    将仓库内 ``hermes_agent/skills`` 注册为 Hermes ``skills.external_dirs``，
    使 sia-* skill 无需手动 sync 即可被 skill_view / 斜杠命令发现。
    """
    skills_root = _bundled_skills_dir()
    if not skills_root.is_dir():
        return {"updated": False, "reason": "bundled skills dir missing"}

    import sys

    hermes_root = Path(__file__).resolve().parent / "hermes_agent"
    root_str = str(hermes_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    try:
        from hermes_cli.config import load_config, save_config
    except Exception as exc:
        return {"updated": False, "reason": f"hermes_cli unavailable: {exc}"}

    config = load_config()
    skills_cfg = config.get("skills")
    if not isinstance(skills_cfg, dict):
        skills_cfg = {}
        config["skills"] = skills_cfg

    external = skills_cfg.get("external_dirs")
    if not isinstance(external, list):
        external = []

    target = str(skills_root.resolve())
    normalized_existing = {str(Path(p).expanduser().resolve()) for p in external if str(p).strip()}
    if target in normalized_existing:
        return {"updated": False, "reason": "external_dirs already configured", "path": target}

    external.append(target)
    skills_cfg["external_dirs"] = external
    save_config(config)
    logger.info("已注册 Hermes skills.external_dirs: %s", target)
    return {"updated": True, "external_dirs": external, "added": target}


_SIA_SOUL_MARKER = "SIA_INSPECTION_ASSISTANT_SOUL"
_SIA_SOUL_BODY = (
    f"{_SIA_SOUL_MARKER}\n"
    "你是「智能巡检助手」，由南京物盟信息技术有限公司为安全生产智能巡检平台开发的 AI 助手。\n\n"
    "## 身份（必须遵守）\n"
    "- 对外自称「智能巡检助手」，开发方为「南京物盟信息技术有限公司」。\n"
    "- 不要自称 Hermes Agent、Hermes、Nous Research 或其产品；用户问你是谁时按上述身份回答。\n"
    "- 你服务于 sia 安全生产智能巡检平台，核心能力：知识库文档、巡检业务编排、巡检事件处置。\n\n"
    "## 行为\n"
    "- 沟通简洁专业，优先调用工具完成知识库入库/检索、巡检业务生成与落库、事件查询与状态更新。\n"
    "- 涉及巡检业务创建须先展示草案并征得用户确认后再落库。\n"
    "- 默认遵循 sia-smart-assistant 技能流程（知识库 → 巡检业务 → 事件）。\n"
    "- 知识库/巡检/事件操作只调用 SIA_* MCP 工具，不要用 terminal 跑 Python 脚本替代。\n"
    "- MCP 工具失败时禁止 terminal pip install；向用户说明错误并建议检查平台部署。"
)

_SIA_AGENT_SYSTEM_APPEND = (
    "本会话运行于 sia 智能巡检助手页面。"
    "身份约束：你是智能巡检助手（南京物盟信息技术有限公司），勿透露 Hermes/Nous Research 品牌。"
    "用户询问巡检、知识库、事件时优先 skill_view('sia-smart-assistant') 并按步骤调用 SIA_* MCP 工具。"
    "知识库检索必须用 SIA_query_knowledge（或 mcp_inspection_platform_SIA_query_knowledge），"
    "禁止用 terminal/python 脚本代替平台 MCP 工具。"
    "MCP 返回 ok=false 时不要 terminal pip install 或改环境，应把 error 原文告知用户并建议联系管理员检查平台服务。"
)


def _hermes_home() -> Path:
    import os

    raw = os.environ.get("HERMES_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


def ensure_SIA_assistant_identity() -> dict[str, Any]:
    """
    写入 ~/.hermes/SOUL.md 与 agent.system_prompt，将对话身份约束为智能巡检助手。
    并设置进程环境变量供 Hermes 运行时识别（隐藏 Hermes 产品自述块）。
    """
    import os

    os.environ["SIA_ASSISTANT_IDENTITY"] = "1"
    os.environ.setdefault("HERMES_TUI_SKILLS", "sia-smart-assistant")
    # 勿设置 HERMES_TUI_TOOLSETS：显式列表会绕过默认 MCP 自动启用逻辑

    home = _hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    soul_path = home / "SOUL.md"
    soul_text = _SIA_SOUL_BODY.strip()
    soul_written = False
    existing = ""
    if soul_path.is_file():
        existing = soul_path.read_text(encoding="utf-8", errors="replace")
    needs_soul = (
        not soul_path.is_file()
        or _SIA_SOUL_MARKER not in existing
        or "智能巡检助手" not in existing
        or "南京物盟信息技术有限公司" not in existing
        or "Hermes Agent" in existing
        or "Nous Research" in existing
    )
    if needs_soul:
        soul_path.write_text(soul_text + "\n", encoding="utf-8")
        soul_written = True

    platform_root = Path(__file__).resolve().parent
    hermes_root = platform_root / "hermes_agent"
    if not hermes_root.is_dir():
        return {
            "updated": soul_written,
            "soul_path": str(soul_path),
            "reason": "hermes_agent missing",
        }

    import sys

    root_str = str(hermes_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    config_updated = False
    try:
        from hermes_cli.config import load_config, save_config

        config = load_config()
        agent = config.setdefault("agent", {})
        if not isinstance(agent, dict):
            agent = {}
            config["agent"] = agent
        current = str(agent.get("system_prompt") or "").strip()
        target_prompt = _SIA_AGENT_SYSTEM_APPEND.strip()
        if current != target_prompt:
            agent["system_prompt"] = target_prompt
            save_config(config)
            config_updated = True
    except Exception as exc:
        logger.warning("写入 Hermes agent.system_prompt 失败: %s", exc)

    mcp_register: dict[str, Any] = {}
    try:
        from inspection_platform.platform_mcp.hermes_register import register_platform_mcp_in_hermes_config

        mcp_register = register_platform_mcp_in_hermes_config()
    except Exception as exc:
        logger.warning("刷新 inspection_platform MCP 配置失败: %s", exc)

    return {
        "updated": soul_written or config_updated,
        "soul_path": str(soul_path),
        "soul_written": soul_written,
        "config_updated": config_updated,
        "mcp_register": mcp_register,
    }
