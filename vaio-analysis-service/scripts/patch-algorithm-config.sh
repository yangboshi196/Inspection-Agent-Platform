#!/usr/bin/env bash
# 修补 VAIO Algorithm_*.json 配方，避免 C++ 核心创建任务失败。
# 1. upload 缺少 suppressEnabled（传 holddowntime 时必填）
# 2. tracker 缺少 labels（人员/目标跟踪类算法必填）
set -euo pipefail

SERVICE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF_DIR="${VAIO_ALGO_CONF:-$SERVICE_ROOT/x86_64/conf/VAIConfig}"

export CONF_DIR
python3 <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["CONF_DIR"])
suppress_param = {
    "defaultvalue": 1,
    "describe": "是否启用事件抑制（配合holddowntime使用）",
    "label": "事件抑制开关",
    "prop": "suppressEnabled",
    "required": False,
    "valuetype": 2,
}

def detection_classes(data):
    for comp in data.get("aiparams", []):
        if comp.get("type") != "detection":
            continue
        for p in comp.get("params", []):
            if p.get("prop") == "classes":
                val = p.get("defaultvalue")
                if isinstance(val, list):
                    return [x for x in val if isinstance(x, dict)]
    return []


def tracker_labels_param(classes):
    if not classes:
        return None
    labels = []
    for c in classes:
        labels.append(
            {
                "id": c.get("id", 0),
                "name": str(c.get("name") or "object"),
                "minstep": c.get("minstep", 0),
                "maxstep": c.get("maxstep", 3),
            }
        )
    return {
        "label": "选择标签",
        "prop": "labels",
        "describe": "配置不同类别目标的跟踪参数",
        "required": False,
        "valuetype": 5,
        "defaultvalue": labels,
    }

upload_patched = 0
tracker_patched = 0
for path in sorted(root.glob("Algorithm_*.json")):
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    classes = detection_classes(data)
    labels_param = tracker_labels_param(classes)

    for comp in data.get("aiparams", []):
        if comp.get("type") == "upload":
            params = comp.setdefault("params", [])
            if not any(x.get("prop") == "suppressEnabled" for x in params):
                params.append(suppress_param)
                changed = True
                upload_patched += 1
        if comp.get("type") == "tracker" and labels_param:
            params = comp.setdefault("params", [])
            if not any(x.get("prop") == "labels" for x in params):
                params.append(labels_param)
                changed = True
                tracker_patched += 1

    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")
        print("patched", path.name)

print(f"done upload={upload_patched} tracker={tracker_patched}")

PY
