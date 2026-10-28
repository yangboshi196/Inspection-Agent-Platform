#!/usr/bin/env bash
# 针对 cam-001 等摔倒误报视频：VAIO 1018 + 平台 LLM 复核 联合验证
set -euo pipefail

VIDEO="${1:-/home/sia/tzb/WMAutoTrainPlat/sia/data/equipment_simulate/cam-001/video.mp4}"
WORK_ID="${2:-iw-ai-1782193181844-0}"
CORE="${VAIO_CORE_BASE:-http://127.0.0.1:9200}"
PY="${PY:-/home/test/miniconda3/envs/SIA_agent/bin/python}"
SERVICE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIA_ROOT="$(cd "$SERVICE_ROOT/.." && pwd)"

if [[ ! -f "$VIDEO" ]]; then
  echo "视频不存在: $VIDEO" >&2
  exit 1
fi
VIDEO="$(readlink -f "$VIDEO")"

echo "========================================"
echo "摔倒误报测试"
echo "  视频: $VIDEO"
echo "  业务: $WORK_ID"
echo "========================================"

echo ""
echo "==> [1/3] VAIO 1018（posetype=[6], fps=1, 约 20s 轮询）"
TASK_ID="fall-fp-1018-$(date +%s)"
DEF='{"areaattr":0,"points":[{"x":0,"y":0},{"x":100,"y":0},{"x":100,"y":100},{"x":0,"y":100}]}'
START=$(curl -s -X POST "$CORE/v1/tasks" -H 'Content-Type: application/json' -d "{
  \"task_id\":\"$TASK_ID\",
  \"video_url\":\"$VIDEO\",
  \"src_data_type\":2,
  \"algorithms\":[{\"detecttype\":1018,\"activerec\":0,\"config\":{
    \"fps\":1,
    \"holddowntime\":60,
    \"suppressEnabled\":1,
    \"detection/person/threshold\":0.5,
    \"posetype\":[6],
    \"person/minlength\":80,
    \"defence\":[$DEF]
  }}]
}")
echo "$START" | "$PY" -m json.tool 2>/dev/null || echo "$START"
for i in $(seq 1 20); do
  sleep 1
  EV=$(curl -s "$CORE/v1/events?task_id=$TASK_ID&limit=5")
  count=$(echo "$EV" | "$PY" -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('events') or []))")
  if [[ "$count" -gt 0 ]]; then
    echo "VAIO 事件 ($count 条):"
    echo "$EV" | "$PY" -m json.tool
    break
  fi
done
curl -s -X DELETE "$CORE/v1/tasks/$TASK_ID" >/dev/null || true
if [[ "${count:-0}" -eq 0 ]]; then
  echo "VAIO: 20s 内无姿态告警（posetype=仅摔倒）"
fi

echo ""
echo "==> [2/3] LLM 关键帧抽测（4s / 22s）"
"$PY" <<PY
import base64, json, subprocess, os, urllib.request
from pathlib import Path
video = "$VIDEO"
api = os.environ.get("SIA_LLM_RULE_API", "http://10.19.155.38:8848/api/process-rule")
prompt = (
    "仅当画面中能清晰辨认完整人体且处于意外跌倒、失去平衡倒地状态时判定为阳性。"
    "正常站立、行走、弯腰、蹲姿、跪姿作业一律为阴性；阴性时不得输出检测框。"
)
import sys
sys.path.insert(0, "$SIA_ROOT")
from inspection_platform.inspection_work.runner import _is_fall_llm_positive

for t in (4, 22):
    out = f"/tmp/fall_fp_{int(t)}s.jpg"
    subprocess.run(["ffmpeg","-y","-ss",str(t),"-i",video,"-frames:v","1","-q:v","2",out],
                   capture_output=True, timeout=30, check=False)
    if not os.path.isfile(out):
        print(f"  t={t}s: 抽帧失败")
        continue
    b64 = base64.b64encode(Path(out).read_bytes()).decode()
    payload = {"rule":[{"id":0,"prompt":prompt,"threshold":0.5}],
               "images":[{"image_name":str(int(t*1000)),"url":f"data:image/jpeg;base64,{b64}"}]}
    req = urllib.request.Request(api, data=json.dumps(payload).encode(),
        headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode())
    dets = (body.get("processedImages") or [{}])[0].get("detections") or []
    if not dets:
        print(f"  t={t}s: LLM 无检出 ✓")
        continue
    d = dets[0]
    desc = str(d.get("description") or "")
    ok = _is_fall_llm_positive(desc)
    flag = "误报入库" if ok else "已过滤 ✓"
    print(f"  t={t}s: conf={d.get('confidence')} valid={ok} ({flag})")
    print(f"         {desc[:100]}...")
PY

echo ""
echo "==> [3/3] 平台完整触发（InspectionWorkRunner.run_manual）"
cd "$SIA_ROOT/inspection_platform"
"$PY" <<PY
import json, sys
sys.path.insert(0, "$SIA_ROOT")
from inspection_platform.inspection_work.runner import InspectionWorkRunner
r = InspectionWorkRunner()
out = r.run_manual("$WORK_ID")
ev = (out.get("events") or [{}])[-1]
print("events_created:", out.get("events_created"))
print("title:", ev.get("title"))
print("status:", ev.get("status"))
print("outcome:", ev.get("resolution_outcome") or "(pending告警)")
print("detail:", (ev.get("resolution_detail") or "")[:120])
dj = ev.get("detection_json") or ""
if "video_time_sec" in dj:
    import json as J
    d = J.loads(dj)
    print("video_time_sec:", d.get("video_time_sec"), "size:", d.get("source_width"), "x", d.get("source_height"))
PY

echo ""
echo "完成。期望：status=resolved / outcome=未检出异常（误报已过滤）"
