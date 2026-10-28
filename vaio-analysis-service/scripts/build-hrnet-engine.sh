#!/usr/bin/env bash
# TRT 7.2: 从 hrnet.onnx 在本机 GPU (sm_86) 编译 hrnet.engine
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_ROOT="${VAIO_SKILLS_ROOT:-$(cd "$SERVICE_ROOT/../agent_skills" && pwd)}"
SDK_BUILD="$SKILLS_ROOT/VAIGateway/vsmartaisdk/build"
ONNX="${1:-$SDK_BUILD/hrnet.onnx}"
ENGINE="${2:-$SERVICE_ROOT/x86_64/model/hrnet.engine}"
TRTEXEC="$SKILLS_ROOT/deps/TensorRT-7.2.3.4/targets/x86_64-linux-gnu/bin/trtexec"
TRT_LIB="$SKILLS_ROOT/deps/TensorRT-7.2.3.4/targets/x86_64-linux-gnu/lib"
CUDNN81="$SKILLS_ROOT/deps/cudnn-8.1.0.77/lib"
NVRTC="$SKILLS_ROOT/deps/cuda11.0/usr/local/cuda-11.0/targets/x86_64-linux/lib"

export LD_LIBRARY_PATH="${CUDNN81}:${NVRTC}:${TRT_LIB}:/usr/local/cuda-11.1/lib64:${LD_LIBRARY_PATH:-}"
unset NVIDIA_TF32_OVERRIDE LD_PRELOAD 2>/dev/null || true

if [[ ! -f "$ONNX" ]]; then
  echo "FAIL: hrnet.onnx 不存在: $ONNX" >&2
  exit 1
fi

if [[ ! -x "$TRTEXEC" ]]; then
  echo "FAIL: trtexec 不存在: $TRTEXEC" >&2
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
BAK=""
if [[ -f "$ENGINE" ]]; then
  BAK="${ENGINE}.bak-$(date +%Y%m%d-%H%M%S)"
  cp -a "$ENGINE" "$BAK"
  echo "已备份旧 engine -> $BAK"
fi

echo "==> hrnet.onnx -> engine (fp16, workspace 1G)"
echo "    ONNX:   $ONNX"
echo "    ENGINE: $ENGINE"
echo "    GPU:    $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo unknown)"

"$TRTEXEC" \
  --onnx="$ONNX" \
  --saveEngine="$WORK/hrnet.engine" \
  --fp16 \
  --workspace=1024 \
  --explicitBatch \
  --iterations=1 \
  --duration=0 2>&1 | tee /tmp/build_hrnet_engine.log

if [[ ! -f "$WORK/hrnet.engine" ]]; then
  echo "FAIL: engine 未生成，见 /tmp/build_hrnet_engine.log" >&2
  exit 2
fi

mkdir -p "$(dirname "$ENGINE")"
install -m 644 "$WORK/hrnet.engine" "$ENGINE"
echo "Engine: $ENGINE ($(du -h "$ENGINE" | awk '{print $1}'))"

echo "==> 校验加载"
if "$TRTEXEC" --loadEngine="$ENGINE" --iterations=1 --duration=0 2>&1 | grep -q "PASSED"; then
  echo "RESULT: PASS"
else
  echo "RESULT: FAIL — 见 /tmp/build_hrnet_engine.log"
  exit 3
fi
