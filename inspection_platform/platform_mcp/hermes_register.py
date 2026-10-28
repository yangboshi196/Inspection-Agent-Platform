"""Hermes MCP 注册辅助（inspection_platform 服务器）。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _hermes_config_path() -> Path:
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / "config.yaml"


def _platform_repo_root() -> str:
    env = os.environ.get("SIA_REPO_ROOT", "").strip()
    if env:
        return str(Path(env).resolve())
    # inspection_platform/platform_mcp/hermes_register.py -> sia/
    return str(Path(__file__).resolve().parents[2])


def _resolve_mcp_python() -> str:
    """Pick a Python >=3.10 that can ``import mcp`` for the stdio MCP server."""
    override = os.environ.get("SIA_MCP_PYTHON", "").strip()
    if override:
        return override

    import shutil
    import subprocess

    candidates: list[str] = []
    for name in ("python3.12", "python3.11", "python3.10", "python3"):
        path = shutil.which(name)
        if path:
            candidates.append(path)

    conda_root = os.environ.get("CONDA_PREFIX", "")
    if conda_root:
        candidates.insert(0, str(Path(conda_root) / "bin" / "python"))
    home = Path.home()
    for env_name in ("SIA_agent", "AgentScope", "vaio-mcp", "fastapi"):
        p = home / "miniconda3" / "envs" / env_name / "bin" / "python"
        if p.is_file():
            candidates.insert(0, str(p))

    seen: set[str] = set()
    for exe in candidates:
        if exe in seen:
            continue
        seen.add(exe)
        try:
            ver = subprocess.run(
                [exe, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip()
            major, minor = (int(x) for x in ver.split(".", 1))
            if major < 3 or (major == 3 and minor < 10):
                continue
            subprocess.run(
                [exe, "-c", "import mcp, sqlalchemy"],
                capture_output=True,
                timeout=10,
                check=True,
            )
            return exe
        except (OSError, subprocess.SubprocessError, ValueError):
            continue

    return shutil.which("python3") or "python3"


def platform_mcp_server_config() -> dict[str, Any]:
    repo = _platform_repo_root()
    python_exe = _resolve_mcp_python()
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    repo_path = str(Path(repo).resolve())
    if repo_path not in existing.split(os.pathsep):
        env["PYTHONPATH"] = f"{repo_path}{os.pathsep}{existing}" if existing else repo_path
    return {
        "command": python_exe,
        "args": ["-m", "inspection_platform.platform_mcp.server"],
        "cwd": repo,
        "env": env,
        "timeout": 180,
    }


def hermes_mcp_config_snippet() -> str:
    cfg = platform_mcp_server_config()
    cwd = cfg["cwd"]
    cmd = cfg["command"]
    return f"""mcp_servers:
  inspection_platform:
    command: {cmd}
    args: ["-m", "inspection_platform.platform_mcp.server"]
    cwd: {cwd}
    env:
      PYTHONPATH: "{cfg['env'].get('PYTHONPATH', '')}"
    timeout: 180
"""


def _register_via_yaml() -> dict[str, Any]:
    try:
        import yaml
    except ImportError as e:
        raise RuntimeError("缺少 PyYAML，无法写入 Hermes 配置") from e

    config_path = _hermes_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config: dict[str, Any] = {}
    if config_path.is_file():
        with config_path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                config = loaded
    config.setdefault("mcp_servers", {})["inspection_platform"] = platform_mcp_server_config()
    with config_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return {
        "registered": True,
        "server": "inspection_platform",
        "config_path": str(config_path),
        "cwd": _platform_repo_root(),
        "method": "yaml",
    }


def register_platform_mcp_in_hermes_config() -> dict[str, Any]:
    """写入 ~/.hermes/config.yaml 的 mcp_servers.inspection_platform。"""
    hermes_root = Path(__file__).resolve().parents[1] / "hermes_agent"
    if not hermes_root.is_dir():
        return _register_via_yaml()

    import sys

    root_str = str(hermes_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    try:
        from hermes_cli.config import load_config, save_config

        config = load_config()
        config.setdefault("mcp_servers", {})["inspection_platform"] = platform_mcp_server_config()
        save_config(config)
        return {
            "registered": True,
            "server": "inspection_platform",
            "config_path": str(_hermes_config_path()),
            "cwd": _platform_repo_root(),
            "method": "hermes_cli",
        }
    except Exception:
        return _register_via_yaml()
