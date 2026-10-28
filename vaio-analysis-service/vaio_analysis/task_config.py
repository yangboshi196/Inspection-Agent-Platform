"""Task JSON helpers for vaio-analysis-core (detect region / defence)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# C++ ParseDetectRegionConf requires config.defence (non-empty).
# Coordinates are 0–100 integer percents (MAX_WH_PERCENT_VALUE).
# areaattr 0 = DetectAreaAtt_DetectArea (normal detection zone).
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


def _needs_defence(config: dict[str, Any]) -> bool:
    defence = config.get("defence")
    return not isinstance(defence, list) or len(defence) == 0


def ensure_algorithm_config_defence(algo: dict[str, Any]) -> dict[str, Any]:
    """Return algo with config.defence set to full-screen default when missing."""
    out = deepcopy(algo)
    config = out.get("config")
    if not isinstance(config, dict):
        config = {}
        out["config"] = config
    if _needs_defence(config):
        config["defence"] = deepcopy(DEFAULT_FULLSCREEN_DEFENCE)
    return out


def ensure_task_payload_defence(payload: dict[str, Any]) -> dict[str, Any]:
    """Inject default defence into each algorithms[].config before POST /v1/tasks."""
    out = deepcopy(payload)
    algorithms = out.get("algorithms")
    if not isinstance(algorithms, list):
        return out
    out["algorithms"] = [ensure_algorithm_config_defence(a) for a in algorithms if isinstance(a, dict)]
    return out
