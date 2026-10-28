"""HTTP client for vaio-analysis-core (C++ standalone, default :9200)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def _base_url() -> str:
    return os.environ.get("VAIO_CORE_BASE", "http://127.0.0.1:9200").rstrip("/")


def _request(method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
    url = f"{_base_url()}{path}"
    data = None
    headers: dict[str, str] = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw.strip():
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"vaio HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"vaio 核心不可达 ({_base_url()}): {e.reason}") from e
    except (TimeoutError, OSError) as e:
        raise RuntimeError(f"vaio 连接异常 ({_base_url()}): {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"vaio 响应非 JSON ({_base_url()}{path})") from e


def health() -> dict[str, Any]:
    return _request("GET", "/health")


def list_algorithms() -> dict[str, Any]:
    return _request("GET", "/v1/algorithms")


def get_algorithm(algorithm_id: int) -> dict[str, Any]:
    return _request("GET", f"/v1/algorithms/{algorithm_id}")


DEFAULT_FULLSCREEN_DEFENCE: list[dict[str, Any]] = [
    {
        "areaattr": 0,
        "points": [
            {"x": 0, "y": 0},
            {"x": 100, "y": 0},
            {"x": 100, "y": 100},
            {"x": 0, "y": 100},
        ],
    }
]


def _ensure_task_payload_defence(payload: dict[str, Any]) -> dict[str, Any]:
    """Inject default defence when algorithms[].config.defence is missing."""
    import copy

    out = copy.deepcopy(payload)
    algorithms = out.get("algorithms")
    if not isinstance(algorithms, list):
        return out
    for algo in algorithms:
        if not isinstance(algo, dict):
            continue
        config = algo.get("config")
        if not isinstance(config, dict):
            config = {}
            algo["config"] = config
        defence = config.get("defence")
        if not isinstance(defence, list) or len(defence) == 0:
            config["defence"] = copy.deepcopy(DEFAULT_FULLSCREEN_DEFENCE)
    return out


def start_task(payload: dict[str, Any], *, timeout: float = 60.0) -> dict[str, Any]:
    body = _ensure_task_payload_defence(payload)
    return _request("POST", "/v1/tasks", body, timeout=timeout)


def stop_task(task_id: str, *, timeout: float = 15.0) -> dict[str, Any]:
    tid = task_id.strip()
    try:
        return _request("DELETE", f"/v1/tasks/{tid}", timeout=timeout)
    except RuntimeError as e:
        return {"error": str(e)}


def list_events(task_id: str = "", *, limit: int = 50, timeout: float = 15.0) -> dict[str, Any]:
    q = f"limit={max(1, min(500, limit))}"
    if task_id.strip():
        from urllib.parse import quote

        q += f"&task_id={quote(task_id.strip())}"
    return _request("GET", f"/v1/events?{q}", timeout=timeout)


def core_available() -> bool:
    try:
        health()
        return True
    except RuntimeError:
        return False


VAIO_MCP_TOOLS: list[dict[str, str]] = [
    {
        "name": "vaio_health",
        "hermes_name": "mcp_vaio_analysis_vaio_health",
        "description": "检查 vaio-analysis-core 健康状态",
    },
    {
        "name": "vaio_list_algorithms",
        "hermes_name": "mcp_vaio_analysis_vaio_list_algorithms",
        "description": "列出 C++ 核心中的 Algorithm_*.json 配方",
    },
    {
        "name": "vaio_get_algorithm",
        "hermes_name": "mcp_vaio_analysis_vaio_get_algorithm",
        "description": "按 id 获取完整算法配方 JSON",
    },
    {
        "name": "vaio_start_task",
        "hermes_name": "mcp_vaio_analysis_vaio_start_task",
        "description": "启动视频分析任务（task_id、video_url、algorithms）",
    },
    {
        "name": "vaio_stop_task",
        "hermes_name": "mcp_vaio_analysis_vaio_stop_task",
        "description": "停止分析任务",
    },
    {
        "name": "vaio_list_events",
        "hermes_name": "mcp_vaio_analysis_vaio_list_events",
        "description": "拉取检测事件（MemoryEventSink）",
    },
]
