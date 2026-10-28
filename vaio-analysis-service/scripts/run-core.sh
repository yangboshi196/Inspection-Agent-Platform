#!/usr/bin/env bash
# Run vaio-analysis-core from vaio-analysis-service/x86_64 with agent_skills runtime deps.
set -euo pipefail

SERVICE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_ROOT="${VAIO_SKILLS_ROOT:-$(cd "$SERVICE_ROOT/../agent_skills" && pwd)}"
BIN="${VAIO_CORE_DIR:-$SERVICE_ROOT/x86_64}"
CUDNN81="${CUDNN81:-$SKILLS_ROOT/deps/cudnn-8.1.0.77/lib}"
OPENCV44="$SKILLS_ROOT/deps/opencv-4.4.0_cuda11/build/lib"
TENSORRT_DIR="${TENSORRT_DIR:-${TENSORRT_HOME:-$SKILLS_ROOT/deps/TensorRT-7.2.3.4/targets/x86_64-linux-gnu/lib}}"
CUDA11_NVRTC="$SKILLS_ROOT/deps/cuda11.0/usr/local/cuda-11.0/targets/x86_64-linux/lib"
RUNTIME="$SKILLS_ROOT/deps/runtime-ubuntu-focal/usr/lib"
RUNTIME64="$SKILLS_ROOT/deps/runtime-ubuntu-focal/usr/lib/x86_64-linux-gnu"
TBB="$SKILLS_ROOT/deps/tbb2020/usr/lib/x86_64-linux-gnu"
OPENCV42="$SKILLS_ROOT/deps/opencv-focal/usr/lib/x86_64-linux-gnu"

if [[ ! -x "$BIN/vaio-analysis-core" ]]; then
  echo "Binary not found: $BIN/vaio-analysis-core" >&2
  echo "Copy from agent_skills build output or rebuild:" >&2
  echo "  cd $SKILLS_ROOT/VAIGateway/VAIOpsSvr_BP && make -f Makefile.standalone TARGETPLATFORM=x86_64" >&2
  exit 1
fi

export VAIO_HTTP_PORT="${VAIO_HTTP_PORT:-9200}"
export LD_LIBRARY_PATH="$CUDNN81:\
$TBB:\
$BIN:\
$SKILLS_ROOT/deps:\
$SKILLS_ROOT/VAIGateway/3rdparty/vsmartaisdk/lib:\
$SKILLS_ROOT/vlinker_base/x86_64:\
$SKILLS_ROOT/vlinker_sdk/VLDevPlayer/linux_libs:\
$OPENCV44:\
$TENSORRT_DIR:\
$CUDA11_NVRTC:\
$RUNTIME:\
$RUNTIME64:\
$OPENCV42:\
$SKILLS_ROOT/wm_eventmodel/x86_64:\
$SKILLS_ROOT/sdk_linux_v2/x86_64:\
/usr/local/cuda-11.1/lib64:\
${LD_LIBRARY_PATH:-}"

missing=()
for lib in libnvinfer.so.7 libnvinfer_plugin.so.7 libnvonnxparser.so.7 libdface.so; do
  if ! ldconfig -p 2>/dev/null | grep -q "$lib" && ! find "$SKILLS_ROOT/deps" "$TENSORRT_DIR" -name "$lib" 2>/dev/null | grep -q .; then
    missing+=("$lib")
  fi
done
if ((${#missing[@]})); then
  echo "Missing runtime libraries under $SKILLS_ROOT/deps (or set TENSORRT_DIR):" >&2
  printf '  - %s\n' "${missing[@]}" >&2
  exit 127
fi

cd "$BIN"
exec ./vaio-analysis-core "$@"
