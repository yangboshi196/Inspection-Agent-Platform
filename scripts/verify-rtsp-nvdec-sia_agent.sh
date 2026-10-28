#!/usr/bin/env bash
# 验证 SIA_agent RTSP 预览：PyAV 软解 + 可选 NVDEC
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONDA_ENV="${SIA_CONDA_ENV:-SIA_agent}"
ENV_FILE="${SIA_RTSP_ENV:-$REPO_ROOT/.tools/rtsp-nvdec.env}"
RTSP_URL="${RTSP_TEST_URL:-rtsp://admin:sia123@192.168.1.47:554/Streaming/Channels/101}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$CONDA_ENV"

echo "=== 环境 ==="
echo "conda: $CONDA_ENV"
echo "python: $(which python)"
python -c "import av, cv2; print('PyAV', av.__version__, 'OpenCV', cv2.__version__)"

FFMPEG="${SIA_FFMPEG:-$(command -v ffmpeg)}"
echo "ffmpeg: $FFMPEG"
"$FFMPEG" -hide_banner -decoders 2>/dev/null | grep -E 'cuvid|hevc_cuvid|h264_cuvid' || echo "(无 cuvid 解码器)"
echo "SIA_RTSP_HWACCEL=${SIA_RTSP_HWACCEL:-<unset>}"

echo
echo "=== PyAV 软解测试 ==="
python <<PY
import time
import av
url = "$RTSP_URL"
t0 = time.time()
c = av.open(url, options={"rtsp_transport": "tcp", "stimeout": "8000000"}, timeout=15.0)
for pkt in c.demux(c.streams.video[0]):
    for fr in pkt.decode():
        img = fr.to_ndarray(format="bgr24")
        print("OK soft", img.shape, f"{time.time()-t0:.2f}s")
        c.close()
        break
    else:
        continue
    break
PY

if [[ "${SIA_RTSP_HWACCEL:-}" == "cuda" ]] && "$FFMPEG" -hide_banner -decoders 2>/dev/null | grep -q hevc_cuvid; then
  echo
  echo "=== ffmpeg NVDEC 抓帧测试 ==="
  timeout 20 "$FFMPEG" -hide_banner -loglevel error -rtsp_transport tcp -stimeout 8000000 \
    -hwaccel cuda -c:v hevc_cuvid -i "$RTSP_URL" -frames:v 1 -f image2pipe -c:v mjpeg - \
    | head -c 3 | xxd
fi

echo
echo "=== OpenCV 单帧测试 ==="
python <<PY
import time
from inspection_platform.equipment.rtsp_opencv import capture_jpeg_opencv
url = "$RTSP_URL"
t0 = time.time()
data = capture_jpeg_opencv(url)
print("OK opencv", len(data), "bytes", f"{time.time()-t0:.2f}s")
PY

echo
echo "=== Platform grab_rtsp_snapshot ==="
cd "$REPO_ROOT"
PYTHONPATH="$REPO_ROOT/inspection_platform" python <<PY
from inspection_platform.equipment.rtsp_live import grab_rtsp_snapshot
import time
t0 = time.time()
data = grab_rtsp_snapshot("$RTSP_URL")
print("OK snapshot", len(data), "bytes", f"{time.time()-t0:.2f}s")
PY

echo
echo "全部检查完成"
