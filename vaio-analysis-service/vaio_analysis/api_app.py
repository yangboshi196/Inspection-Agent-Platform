"""FastAPI REST layer (optional) — proxies to C++ vaio-analysis-core."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from vaio_analysis.core_bridge import VaioCoreBridge

app = FastAPI(
    title="vaio-analysis-service",
    description="Video AI analysis API — thin HTTP layer over vaio-analysis-core",
    version="0.1.0",
)
bridge = VaioCoreBridge()


class StartTaskRequest(BaseModel):
    task_id: str
    video_url: str
    task_name: str | None = None
    src_data_type: int = 1
    resolution: int = 0
    user_data: int = 0
    video_id: str | None = None
    algorithms: list[dict[str, Any]] | None = None
    task_config: list[dict[str, Any]] | str | None = None


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        data = bridge.health()
        return {"status": "ok", "core": data}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"core unavailable: {exc}") from exc


@app.get("/v1/algorithms")
def list_algorithms() -> dict[str, Any]:
    return bridge.list_algorithms()


@app.get("/v1/algorithms/{algorithm_id}")
def get_algorithm(algorithm_id: int) -> dict[str, Any]:
    try:
        return bridge.get_algorithm(algorithm_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/v1/tasks")
def start_task(body: StartTaskRequest) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    result = bridge.start_task(payload)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result)
    return result


@app.delete("/v1/tasks/{task_id}")
def stop_task(task_id: str) -> dict[str, Any]:
    result = bridge.stop_task(task_id)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result)
    return result


@app.get("/v1/events")
def list_events(task_id: str = "", limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    return bridge.list_events(task_id=task_id, limit=limit)
