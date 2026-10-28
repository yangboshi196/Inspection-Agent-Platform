#!/usr/bin/env bash
# 批量验证 VAIO 算法任务能否创建（result=0），默认跳过 1019 人脸识别。
set -euo pipefail

CORE="${VAIO_CORE_BASE:-http://127.0.0.1:9200}"
SERVICE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIDEO="${1:-/home/sia/tzb/WMAutoTrainPlat/sia/data/equipment_simulate/cam-001/video.mp4}"
SKIP_FACE="${SKIP_FACE:-1019}"

curl -sf "$CORE/health" >/dev/null || {
  echo "VAIO 核心未就绪: $CORE" >&2
  echo "请先: bash scripts/run-core.sh" >&2
  exit 1
}

export CORE VIDEO SKIP_FACE SERVICE_ROOT
python3 <<'PY'
import json
import os
import sys
import time
import urllib.request

core = os.environ["CORE"]
video = os.environ["VIDEO"]
skip = int(os.environ.get("SKIP_FACE", "1019"))
service_root = os.environ["SERVICE_ROOT"]
boat = f"{service_root}/x86_64/boat.mp4"
fall = f"{service_root}/x86_64/shuaidao.mp4"
special = {1003: boat, 1005: fall, 1016: fall, 1018: fall}
cfg = {
    "fps": 1,
    "holddowntime": 10,
    "suppressEnabled": 1,
    "sensitivity": 50,
    "defence": [{
        "areaattr": 0,
        "points": [
            {"x": 0, "y": 0}, {"x": 100, "y": 0},
            {"x": 100, "y": 100}, {"x": 0, "y": 100},
        ],
    }],
}


def req(method, path, body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(core + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=60) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw.strip() else {}


failed = []
for aid in range(1000, 1020):
    if aid == skip:
        print(f"skip {aid} (face)")
        continue
    tid = f"algo-test-{aid}-{int(time.time())}"
    v = special.get(aid, video)
    try:
        start = req("POST", "/v1/tasks", {
            "task_id": tid,
            "video_url": v,
            "src_data_type": 2,
            "algorithms": [{"detecttype": aid, "activerec": 0, "config": cfg}],
        })
        rc = start.get("result")
        ok = not start.get("error") and rc is not None and int(rc) == 0
        print(f"{'OK' if ok else 'FAIL':4s} {aid} result={rc}")
        if not ok:
            failed.append((aid, rc, start.get("error")))
    except Exception as e:
        print(f"FAIL {aid} {e}")
        failed.append((aid, None, str(e)))
    finally:
        try:
            req("DELETE", f"/v1/tasks/{tid}")
        except Exception:
            pass

if failed:
    print("\nFailed algorithms:")
    for row in failed:
        print(" ", row)
    sys.exit(1)
print("\nAll tested algorithms created tasks successfully.")
PY
