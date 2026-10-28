#!/usr/bin/env bash
# Verify yolov5m.engine with TensorRT 8.5 (Plan B / RTX 3080 SM8.6).
set -euo pipefail

SERVICE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_ROOT="${VAIO_SKILLS_ROOT:-$(cd "$SERVICE_ROOT/../agent_skills" && pwd)}"
TRT8="$SKILLS_ROOT/deps/TensorRT-8.5.3.1"
ENGINE="${1:-$SERVICE_ROOT/x86_64/model/yolov5m.engine}"
TRTEXEC="$TRT8/bin/trtexec"
CUDA118="${CUDA118_HOME:-/usr/local/cuda-11.8}"
CUDNN_LIB="${CUDNN86_LIB:-$SKILLS_ROOT/deps/cudnn-8.6.0/lib}"
[[ -d "$CUDNN_LIB" ]] || CUDNN_LIB="/usr/lib/x86_64-linux-gnu"

export LD_LIBRARY_PATH="${CUDNN_LIB}:${TRT8}/lib:${CUDA118}/lib64:${LD_LIBRARY_PATH:-}"
unset NVIDIA_TF32_OVERRIDE LD_PRELOAD 2>/dev/null || true

echo "Engine: $ENGINE"
[[ -f "$ENGINE" ]] || { echo "FAIL: not found"; exit 1; }
echo "Size: $(du -h "$ENGINE" | awk '{print $1}')"
echo "GPU: $(nvidia-smi --query-gpu=name,driver_version,compute_cap --format=csv,noheader 2>/dev/null)"
echo "TRT: $TRTEXEC"
"$TRTEXEC" --loadEngine="$ENGINE" --iterations=3 --duration=0 2>&1 | tee /tmp/verify_yolov5m_engine_trt8.log
grep -q PASSED /tmp/verify_yolov5m_engine_trt8.log && echo "RESULT: PASS" || exit 2
