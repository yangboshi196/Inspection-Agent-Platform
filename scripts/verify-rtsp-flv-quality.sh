#!/usr/bin/env bash
# 对比 FLV preview（子码流）与 hd（主码流）转码参数，并可选探测在线流分辨率。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/sia" 2>/dev/null || cd "$ROOT"

export PYTHONPATH="${ROOT}/sia:${PYTHONPATH:-}"

python3 <<'PY'
from inspection_platform.equipment.rtsp_flv import _pick_flv_cmd
from inspection_platform.equipment.rtsp_live import pick_stream_url, stream_url_candidates

sample = "rtsp://192.168.1.64:554/Streaming/Channels/101"
sub = pick_stream_url(sample, stream="sub")
main = pick_stream_url(sample, stream="main")
print("=== 码流 URL（海康示例）===")
print(f"  main: {main}")
print(f"  sub:  {sub}")
print(f"  candidates(sub first): {stream_url_candidates(sample, prefer_sub=True)}")
print(f"  candidates(main first): {stream_url_candidates(sample, prefer_sub=False)}")

preview_cmd = _pick_flv_cmd(sub, profile="preview")
hd_cmd = _pick_flv_cmd(main, profile="hd")
print("\n=== preview 转码参数（子码流）===")
print(" ", " ".join(preview_cmd[preview_cmd.index("-i") + 2:]))

print("\n=== hd 转码参数（主码流）===")
print(" ", " ".join(hd_cmd[hd_cmd.index("-i") + 2:]))
PY

BASE_URL="${SIA_VERIFY_BASE_URL:-http://127.0.0.1:8001}"
EQUIP_ID="${SIA_VERIFY_EQUIPMENT_ID:-}"
TOKEN="${SIA_VERIFY_TOKEN:-}"
if [[ -z "$TOKEN" && -n "${SIA_VERIFY_ACCOUNT:-}" ]]; then
  TOKEN="$(curl -sf -X POST "${BASE_URL}/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"account\":\"${SIA_VERIFY_ACCOUNT}\",\"password\":\"${SIA_VERIFY_PASSWORD:-demo1234}\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")"
fi

if [[ -z "$EQUIP_ID" ]]; then
  EQUIP_ID="$(python3 <<'PY' 2>/dev/null || true
import sqlite3
from pathlib import Path
for p in [
    Path("data/equipment.db"),
    Path("sia/data/equipment.db"),
    Path("../data/equipment.db"),
]:
    if not p.is_file():
        continue
    conn = sqlite3.connect(p)
    row = conn.execute(
        "SELECT id FROM equipment WHERE kind='camera' AND platform_address != '' LIMIT 1"
    ).fetchone()
    if row:
        print(row[0])
        break
PY
)"
fi

if [[ -z "$EQUIP_ID" ]]; then
  echo ""
  echo "跳过在线探测：未找到 RTSP 摄像头（可设 SIA_VERIFY_EQUIPMENT_ID）"
  exit 0
fi

FFMPEG="${SIA_FFMPEG:-ffmpeg}"
if ! command -v "$FFMPEG" >/dev/null 2>&1; then
  FFMPEG="ffmpeg"
fi

probe_flv() {
  local label="$1"
  local qs="$2"
  local url="${BASE_URL}/api/equipment/${EQUIP_ID}/live/flv?${qs}"
  if [[ -n "$TOKEN" ]]; then
    url="${url}&access_token=${TOKEN}"
  fi
  echo ""
  echo "=== 在线探测: $label ==="
  echo "URL: $url"
  tmp="$(mktemp)"
  # 拉约 3MB 或 8 秒
  if curl -sf --max-time 25 -o "$tmp" "$url"; then
    sz=$(wc -c <"$tmp" | tr -d ' ')
    echo "  收到 FLV 字节: $sz"
    if [[ "$sz" -gt 50000 ]]; then
      "$FFMPEG" -hide_banner -loglevel error -i "$tmp" -frames:v 1 -f null - 2>&1 | head -5 || true
      "$FFMPEG" -hide_banner -i "$tmp" 2>&1 | grep -E "Stream|Video:" | head -3 || true
    else
      echo "  数据过小，可能鉴权失败或服务未就绪"
    fi
  else
    echo "  请求失败（检查 Platform 是否运行、TOKEN、设备 RTSP）"
  fi
  rm -f "$tmp"
}

echo ""
echo "设备 ID: $EQUIP_ID"
echo "平台: $BASE_URL"

probe_flv "preview/sub" "stream=sub&quality=preview"
probe_flv "hd/main" "stream=main&quality=hd"

echo ""
echo "完成。请在事件详情「实时视频」tab 对比清晰度（应使用 hd/main）。"
