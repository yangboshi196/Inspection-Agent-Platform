"""
ModelManager 模块 - API Key 安全解析。

支持三种 Key 来源：
- env:VAR_NAME  ：读取环境变量
- secret:NAME   ：读取加密存储（预留）
- 明文           ：直接使用
"""


from __future__ import annotations

import os


class SecretResolver:
    """
    最小可用的 key_ref 解析器：
    - env:OPENAI_API_KEY -> 读取环境变量；若未设置且构造时传入 `local_env`，则按变量名取备用值（仅建议本地调试）
    - secret:<name> -> 预留（当前未实现，可对接你们的密钥管理/数据库）
    - 其它字符串：按明文密钥原样返回（不推荐用于生产配置）
    """

    def __init__(self, *, local_env: dict[str, str] | None = None) -> None:
        """
        Args:
            local_env: 按「环境变量名」提供备用密钥；仅当 `env:NAME` 在系统中未设置时使用（本地调试）。
        """
        self._local_env: dict[str, str] = {k: v for k, v in (local_env or {}).items() if v}

    def resolve(self, key_ref: str) -> str | None:
        """解析 `key_ref`（`env:` / `secret:` / 明文），得到实际密钥或 `None`。"""
        if not key_ref:
            return None
        if key_ref.startswith("env:"):
            env_key = key_ref.split("env:", 1)[1].strip()
            val = os.environ.get(env_key) or self._local_env.get(env_key)
            if val is None:
                return None
            val = val.strip()
            return val or None
        if key_ref.startswith("secret:"):
            name = key_ref.split("secret:", 1)[1].strip()
            raise NotImplementedError(f"secret resolver not implemented for '{name}'")
        return key_ref

