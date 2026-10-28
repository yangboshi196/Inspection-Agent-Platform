"""环境变量读取：优先 ``SIA_*`` 新名，回退到历史变量名。"""

from __future__ import annotations

import os


def first_env(*names: str) -> str:
    for name in names:
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    return ""
