"""Load Hermes .env and probe embedding providers (no secrets printed)."""
from __future__ import annotations

import os
from pathlib import Path

import httpx


def load_hermes_env() -> None:
    p = Path(r"E:/Agent/.hermes/.hermes/.env")
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def main() -> None:
    load_hermes_env()
    key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    base = (os.environ.get("SILICONFLOW_BASE_URL") or "https://maas-openapi.wanjiedata.com/api").rstrip("/")
    print("has_key", bool(key), "base", base)

    if not key:
        print("no_api_key")
        return

    models = [
        "Qwen/Qwen3-Embedding-8B",
        "BAAI/bge-m3",
        "Pro/BAAI/bge-m3",
        "text-embedding-v3",
    ]
    for model in models:
        r = httpx.post(
            f"{base}/v1/embeddings",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "input": ["test"]},
            timeout=30,
        )
        text = r.text[:200]
        try:
            data = r.json()
        except Exception:
            print(model, "status", r.status_code, "non_json", text)
            continue
        items = data.get("data") or []
        err = data.get("error")
        msg = ""
        if isinstance(err, dict):
            msg = str(err.get("message") or "")[:100]
        dim = len(items[0].get("embedding") or []) if items else 0
        print(model, "status", r.status_code, "n", len(items), "dim", dim, "err", msg)


if __name__ == "__main__":
    main()
