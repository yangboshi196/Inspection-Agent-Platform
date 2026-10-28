"""HTTP bridge to vaio-analysis-core (C++ standalone service)."""

from __future__ import annotations

import os
from typing import Any

import httpx

from vaio_analysis.task_config import ensure_task_payload_defence

DEFAULT_CORE_BASE = os.environ.get("VAIO_CORE_BASE", "http://127.0.0.1:9200")
DEFAULT_TIMEOUT = float(os.environ.get("VAIO_CORE_TIMEOUT", "30"))


class VaioCoreBridge:
    def __init__(self, base_url: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base_url = (base_url or DEFAULT_CORE_BASE).rstrip("/")
        self.timeout = timeout

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def health(self) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(self._url("/health"))
            resp.raise_for_status()
            return resp.json()

    def list_algorithms(self) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(self._url("/v1/algorithms"))
            resp.raise_for_status()
            return resp.json()

    def get_algorithm(self, algorithm_id: int | str) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(self._url(f"/v1/algorithms/{algorithm_id}"))
            resp.raise_for_status()
            return resp.json()

    def start_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = ensure_task_payload_defence(payload)
        with httpx.Client(timeout=max(self.timeout, 60.0)) as client:
            resp = client.post(self._url("/v1/tasks"), json=body)
            if resp.status_code >= 400:
                return {"error": resp.text, "status_code": resp.status_code}
            return resp.json()

    def stop_task(self, task_id: str) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.delete(self._url(f"/v1/tasks/{task_id}"))
            if resp.status_code >= 400:
                return {"error": resp.text, "status_code": resp.status_code}
            return resp.json()

    def list_events(self, task_id: str = "", limit: int = 50) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if task_id:
            params["task_id"] = task_id
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(self._url("/v1/events"), params=params)
            resp.raise_for_status()
            return resp.json()
