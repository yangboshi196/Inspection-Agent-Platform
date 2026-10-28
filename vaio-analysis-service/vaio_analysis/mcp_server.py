#!/usr/bin/env python3
"""MCP server — exposes vaio-analysis-core to Hermes Agent via stdio."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from vaio_analysis.core_bridge import VaioCoreBridge

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Install dependencies: pip install mcp httpx", file=sys.stderr)
    raise

bridge = VaioCoreBridge()
mcp = FastMCP("vaio-analysis")


@mcp.tool()
def vaio_health() -> dict[str, Any]:
    """Check vaio-analysis-core health."""
    return bridge.health()


@mcp.tool()
def vaio_list_algorithms() -> dict[str, Any]:
    """List available algorithm recipes (Algorithm_*.json)."""
    return bridge.list_algorithms()


@mcp.tool()
def vaio_get_algorithm(algorithm_id: int) -> dict[str, Any]:
    """Get full algorithm recipe JSON by id (e.g. 1000)."""
    return bridge.get_algorithm(algorithm_id)


@mcp.tool()
def vaio_start_task(
    task_id: str,
    video_url: str,
    algorithms: list[dict[str, Any]] | None = None,
    task_name: str | None = None,
    src_data_type: int = 1,
) -> dict[str, Any]:
    """Start a video analysis task on vaio-analysis-core.

    Each algorithms[].config must include ``defence`` (detect region polygons).
    If omitted, a full-screen default defence is injected automatically.
    """
    payload: dict[str, Any] = {
        "task_id": task_id,
        "video_url": video_url,
        "src_data_type": src_data_type,
    }
    if task_name:
        payload["task_name"] = task_name
    if algorithms:
        payload["algorithms"] = algorithms
    return bridge.start_task(payload)


@mcp.tool()
def vaio_stop_task(task_id: str) -> dict[str, Any]:
    """Stop a running analysis task."""
    return bridge.stop_task(task_id)


@mcp.tool()
def vaio_list_events(task_id: str = "", limit: int = 50) -> dict[str, Any]:
    """Poll detection events from memory event sink."""
    return bridge.list_events(task_id=task_id, limit=limit)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
