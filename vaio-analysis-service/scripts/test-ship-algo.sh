#!/usr/bin/env bash
# 一键验证船只检测 (detecttype=1003) — 需 vaio-analysis-core 已在 :9200 运行
set -euo pipefail

CORE="${VAIO_CORE_BASE:-http://127.0.0.1:9200}"
VIDEO="${1:-$(cd "$(dirname "$0")/.." && pwd)/x86_64/test.mp4}"
TASK_ID="ship-test-$(date +%s)"
POLL_SEC="${POLL_SEC:-90}"
INTERVAL="${INTERVAL:-5}"

if [[ ! -f "$VIDEO" && "$VIDEO" != rtsp://* && "$VIDEO" != http://* && "$VIDEO" != https://* ]]; then
  echo "视频不存在: $VIDEO" >&2
  echo "用法: $0 [/path/to/video.mp4|rtsp://...]" >&2
  exit 1
fi

if [[ "$VIDEO" == rtsp://* || "$VIDEO" == http://* || "$VIDEO" == https://* ]]; then
  SRC_TYPE=1
else
  VIDEO="$(readlink -f "$VIDEO" 2>/dev/null || realpath "$VIDEO" 2>/dev/null || echo "$VIDEO")"
  SRC_TYPE=2
fi

echo "==> 健康检查 $CORE"
curl -sf "$CORE/health" | python3 -m json.tool || { echo "核心未就绪，请先: ./scripts/run-core.sh" >&2; exit 1; }

echo "==> 启动任务 $TASK_ID"
echo "    视频: $VIDEO (src_data_type=$SRC_TYPE)"
START=$(curl -s -X POST "$CORE/v1/tasks" \
  -H 'Content-Type: application/json' \
  -d "{
    \"task_id\": \"$TASK_ID\",
    \"video_url\": \"$VIDEO\",
    \"src_data_type\": $SRC_TYPE,
    \"task_name\": \"船只检测验证\",
    \"algorithms\": [{
      \"detecttype\": 1003,
      \"activerec\": 0,
      \"config\": {
        \"holddowntime\": 60,
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
  echo "任务启动失败" >&2
  exit 1
fi

echo "==> 轮询事件 (${POLL_SEC}s, 每 ${INTERVAL}s)"
deadline=$((SECONDS + POLL_SEC))
last_count=0
while (( SECONDS < deadline )); do
  sleep "$INTERVAL"
  if ! curl -sf "$CORE/health" >/dev/null 2>&1; then
    echo "警告: 核心进程可能已崩溃 (139)，请查看 run-core 终端日志" >&2
    exit 139
  fi
  EV=$(curl -s "$CORE/v1/events?task_id=$TASK_ID&limit=50")
  count=$(echo "$EV" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('events',d if isinstance(d,list) else [])))" 2>/dev/null || echo 0)
  if [[ "$count" != "$last_count" ]]; then
    echo "--- events (count=$count) ---"
    echo "$EV" | python3 -m json.tool 2>/dev/null || echo "$EV"
    last_count=$count
  fi
done

echo "==> 停止任务"
curl -s -X DELETE "$CORE/v1/tasks/$TASK_ID" | python3 -m json.tool 2>/dev/null || true
echo "完成。若无事件，请换含船只的视频再试。"
