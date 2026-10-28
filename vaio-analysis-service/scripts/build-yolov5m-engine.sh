#!/usr/bin/env bash
# Build yolov5m.engine for vaio-analysis-core (TRT 7.2.3.4 + YoloLayer_TRT).
# Requires: tensorrtx yolov5 binary, yolov5m.wts, cuDNN 8.1.x, RTX GPU.
set -euo pipefail

SERVICE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_ROOT="${VAIO_SKILLS_ROOT:-$(cd "$SERVICE_ROOT/../agent_skills" && pwd)}"
WTS="${1:-/home/sia/tzb/WMAutoTrainPlat/wm-1.1/backend-v1.1/train/models/pre/x86/detection/yolov5/yolov5-5.0/yolov5m.wts}"
ENGINE="${2:-$SERVICE_ROOT/x86_64/model/yolov5m.engine}"
SIZE="${3:-m}"

TRTX_BIN="${TRTX_YOLOV5_BIN:-/tmp/tensorrtx_yolov5_build/build/yolov5}"
TRT_LIB="${SKILLS_ROOT}/deps/TensorRT-7.2.3.4/targets/x86_64-linux-gnu/lib"
NVRTC="${SKILLS_ROOT}/deps/cuda11.0/usr/local/cuda-11.0/targets/x86_64-linux/lib"
CUDNN81="${CUDNN81_LIB:-${SKILLS_ROOT}/deps/cudnn-8.1.0.77/lib}"
TRTEXEC="${SKILLS_ROOT}/deps/TensorRT-7.2.3.4/targets/x86_64-linux-gnu/bin/trtexec"

if [[ ! -f "$WTS" ]]; then
  echo "Missing wts: $WTS" >&2
  echo "Generate: bash wm-1.1/.../yolov5-5.0/pt2engine.sh" >&2
  exit 1
fi
if [[ ! -x "$TRTX_BIN" ]]; then
  echo "Missing tensorrtx builder: $TRTX_BIN" >&2
  exit 1
fi
if [[ ! -f "$CUDNN81/libcudnn.so.8.1.0" && ! -f "$CUDNN81/libcudnn.so.8" ]]; then
  echo "Missing cuDNN 8.1 libs under: $CUDNN81" >&2
  echo "Install from NVIDIA repo deb:" >&2
  echo "  libcudnn8_8.1.0.77-1+cuda11.2_amd64.deb" >&2
  exit 1
fi

export LD_LIBRARY_PATH="${CUDNN81}:${NVRTC}:${TRT_LIB}:/usr/local/cuda-11.1/lib64:/usr/local/cuda-11.1/targets/x86_64-linux/lib:${LD_LIBRARY_PATH:-}"
unset NVIDIA_TF32_OVERRIDE LD_PRELOAD 2>/dev/null || true

echo "[1/2] wts -> engine: $ENGINE (size=$SIZE)"
echo "      GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo unknown)"
if ! "$TRTX_BIN" -s "$WTS" "$ENGINE" "$SIZE" 2>&1 | tee /tmp/yolov5m_build.log; then
  echo "FAIL: tensorrtx build aborted — see /tmp/yolov5m_build.log" >&2
  grep -iE 'PwgenException|error|fail' /tmp/yolov5m_build.log | tail -5 >&2 || true
  echo "Hint: RTX 3080 + TRT 7.2 + driver 470.x often hits Myelin PwgenException." >&2
  echo "      Need driver 510+ or build on another RTX3080 machine / NGC container with GPU." >&2
  exit 134
fi

echo "[2/2] verify with trtexec"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/verify-yolov5m-engine.sh" "$ENGINE"
