#!/usr/bin/env bash
# Verify yolov5m.engine: file, TRT plan version, GPU SM, optional inference smoke test.
set -euo pipefail

SERVICE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_ROOT="${VAIO_SKILLS_ROOT:-$(cd "$SERVICE_ROOT/../agent_skills" && pwd)}"
ENGINE="${1:-$SERVICE_ROOT/x86_64/model/yolov5m.engine}"
TRTEXEC="${SKILLS_ROOT}/deps/TensorRT-7.2.3.4/targets/x86_64-linux-gnu/bin/trtexec"
CUDNN81="${SKILLS_ROOT}/deps/cudnn-8.1.0.77/lib"
NVRTC="${SKILLS_ROOT}/deps/cuda11.0/usr/local/cuda-11.0/targets/x86_64-linux/lib"
TRT_LIB="${SKILLS_ROOT}/deps/TensorRT-7.2.3.4/targets/x86_64-linux-gnu/lib"
YOLO_PLUGIN="${YOLO_PLUGIN:-$SKILLS_ROOT/VAIGateway/vsmartaisdk/build-trt72/libyoloplugin.so}"
if [[ ! -f "$YOLO_PLUGIN" ]]; then
  YOLO_PLUGIN="$SKILLS_ROOT/VAIGateway/3rdparty/vsmartaisdk/lib/libyoloplugin.so"
fi

export LD_LIBRARY_PATH="${CUDNN81}:${NVRTC}:${TRT_LIB}:/usr/local/cuda-11.1/lib64:${LD_LIBRARY_PATH:-}"
unset NVIDIA_TF32_OVERRIDE LD_PRELOAD 2>/dev/null || true

echo "Engine: $ENGINE"
if [[ ! -f "$ENGINE" ]]; then
  echo "FAIL: engine file not found"
  exit 1
fi
if [[ ! -f "$YOLO_PLUGIN" ]]; then
  echo "FAIL: YoloLayer plugin not found: $YOLO_PLUGIN" >&2
  exit 1
fi

echo "Size: $(du -h "$ENGINE" | awk '{print $1}')"
head -c 4 "$ENGINE" | xxd -p | grep -q 70747274 && echo "Magic: ptrt (TensorRT plan) OK" || echo "WARN: unexpected magic"

echo "GPU: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null || echo unknown)"
echo "Plugin: $YOLO_PLUGIN"
echo "--- trtexec load (with YoloLayer plugin) ---"
if "$TRTEXEC" --plugins="$YOLO_PLUGIN" --loadEngine="$ENGINE" --iterations=1 --duration=0 2>&1 | tee /tmp/verify_yolov5m_engine.log | grep -q "PASSED"; then
  echo "RESULT: PASS (load + 1 iteration)"
  exit 0
fi

echo "RESULT: FAIL — see /tmp/verify_yolov5m_engine.log"
grep -iE 'error|fail|Version tag|compute|PASSED' /tmp/verify_yolov5m_engine.log | tail -10 || true
exit 2
