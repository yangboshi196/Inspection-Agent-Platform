#!/usr/bin/env bash
# 验证摔倒相关算法 (1005/1016/1018) — 需 vaio-analysis-core 已在 :9200 运行
set -euo pipefail

CORE="${VAIO_CORE_BASE:-http://127.0.0.1:9200}"
SERVICE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIDEO="${1:-$SERVICE_ROOT/x86_64/shuaidao.mp4}"
ALGO="${2:-1018}"
POLL_SEC="${POLL_SEC:-120}"
INTERVAL="${INTERVAL:-5}"

if [[ ! -f "$VIDEO" && "$VIDEO" != rtsp://* && "$VIDEO" != http://* && "$VIDEO" != https://* ]]; then
  echo "视频不存在: $VIDEO" >&2
  echo "用法: $0 [/path/to/video.mp4] [detecttype]" >&2
  exit 1
fi

if [[ "$VIDEO" == rtsp://* || "$VIDEO" == http://* || "$VIDEO" == https://* ]]; then
  SRC_TYPE=1
else
  VIDEO="$(readlink -f "$VIDEO" 2>/dev/null || realpath "$VIDEO" 2>/dev/null || echo "$VIDEO")"
  SRC_TYPE=2
fi

TASK_ID="fall-test-${ALGO}-$(date +%s)"

echo "==> 健康检查 $CORE"
curl -sf "$CORE/health" | python3 -m json.tool || { echo "核心未就绪，请先: ./scripts/run-core.sh" >&2; exit 1; }

echo "==> 启动算法 $ALGO  任务 $TASK_ID"
echo "    视频: $VIDEO"
START=$(curl -s -X POST "$CORE/v1/tasks" \
  -H 'Content-Type: application/json' \
  -d "{
    \"task_id\": \"$TASK_ID\",
    \"video_url\": \"$VIDEO\",
    \"src_data_type\": $SRC_TYPE,
    \"task_name\": \"摔倒检测验证-$ALGO\",
    \"algorithms\": [{
      \"detecttype\": $ALGO,
      \"activerec\": 0,
      \"config\": {
        \"holddowntime\": 10,
        \"sensitivity\": 50,
        \"defence\": [{
          \"areaattr\": 0,
          \"points\": [
            {\"x\": 0, \"y\": 0},
            {\"x\": 100, \"y\": 0},
            {\"x\": 100, \"y\": 100},
            {\"x\": 0, \"y\": 100}
          ]
        }]
      }
    }]
  }")
echo "$START" | python3 -m json.tool 2>/dev/null || echo "$START"

if echo "$START" | grep -q '"error"'; then
  echo "任务启动失败（核心应仍在运行）" >&2
  curl -sf "$CORE/health" >/dev/null && echo "核心 health: OK" || echo "核心 health: FAIL" >&2
  exit 1
fi

sleep 2
if ! curl -sf "$CORE/health" >/dev/null 2>&1; then
  echo "FAIL: 任务启动后核心崩溃 (segfault)" >&2
  exit 139
fi
echo "OK: 任务已启动，核心未崩溃"

echo "==> 轮询事件 (${POLL_SEC}s)"
deadline=$((SECONDS + POLL_SEC))
last_count=0
while (( SECONDS < deadline )); do
  sleep "$INTERVAL"
  if ! curl -sf "$CORE/health" >/dev/null 2>&1; then
    echo "FAIL: 运行中核心崩溃" >&2
    exit 139
  fi
  EV=$(curl -s "$CORE/v1/events?task_id=$TASK_ID&limit=20")
  count=$(echo "$EV" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('events',d if isinstance(d,list) else [])))" 2>/dev/null || echo 0)
  if [[ "$count" != "$last_count" ]]; then
    echo "--- events (count=$count) ---"
    echo "$EV" | python3 -m json.tool 2>/dev/null || echo "$EV"
    last_count=$count
    if [[ "$count" -gt 0 ]]; then
      echo "==> 已收到事件，提前停止任务（避免长视频持续推理触发核心崩溃）"
      curl -s -X DELETE "$CORE/v1/tasks/$TASK_ID" | python3 -m json.tool 2>/dev/null || true
      echo "完成 (算法 $ALGO, 事件数=$last_count)"
      exit 0
    fi
  fi
done

echo "==> 停止任务"
curl -s -X DELETE "$CORE/v1/tasks/$TASK_ID" | python3 -m json.tool 2>/dev/null || true
echo "完成 (算法 $ALGO, 事件数=$last_count)"
