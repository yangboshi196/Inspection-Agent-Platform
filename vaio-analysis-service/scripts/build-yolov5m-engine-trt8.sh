#!/usr/bin/env bash
# Build yolov5m.engine for RTX 3080 with TensorRT 8.5 + tensorrtx (Plan B).
set -euo pipefail

SERVICE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_ROOT="${VAIO_SKILLS_ROOT:-$(cd "$SERVICE_ROOT/../agent_skills" && pwd)}"
DEPS="$SKILLS_ROOT/deps"
TRT8="$DEPS/TensorRT-8.5.3.1"
TRT8_LIB="$TRT8/lib"
TRT8_INC="$TRT8/include"
TRTEXEC="$TRT8/bin/trtexec"
CUDA118="${CUDA118_HOME:-/usr/local/cuda-11.8}"
WTS="${1:-/home/sia/tzb/WMAutoTrainPlat/wm-1.1/backend-v1.1/train/models/pre/x86/detection/yolov5/yolov5-5.0/yolov5m.wts}"
ENGINE="${2:-$SERVICE_ROOT/x86_64/model/yolov5m.engine}"
SIZE="${3:-m}"
TRTX_ROOT="${TRTX_ROOT:-/tmp/tensorrtx_yolov5_trt8}"
TRTX_BIN="$TRTX_ROOT/yolov5/build/yolov5"

if [[ ! -f "$WTS" ]]; then
  echo "Missing wts: $WTS" >&2
  exit 1
fi
if [[ ! -x "$TRTEXEC" ]]; then
  echo "Missing TRT8 trtexec: $TRTEXEC — run install-trt8-stack.sh first" >&2
  exit 1
fi

# Build tensorrtx yolov5 against TRT8 if needed
if [[ ! -x "$TRTX_BIN" ]]; then
  echo "[setup] clone/build tensorrtx yolov5 for TRT8..."
  rm -rf "$TRTX_ROOT"
  git clone --depth 1 https://github.com/wang-xinyu/tensorrtx.git "$TRTX_ROOT/src"
  cp -a "$TRTX_ROOT/src/yolov5" "$TRTX_ROOT/"
  cat > "$TRTX_ROOT/yolov5/CMakeLists.txt" <<CMEOF
cmake_minimum_required(VERSION 3.10)
project(yolov5)
add_definitions(-std=c++14 -DAPI_EXPORTS -O2 -pthread)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_BUILD_TYPE Release)
find_package(CUDA REQUIRED)
include_directories(\${PROJECT_SOURCE_DIR}/include)
include_directories(${TRT8_INC})
include_directories(${CUDA118}/include)
link_directories(${TRT8_LIB})
link_directories(${CUDA118}/lib64)
cuda_add_library(myplugins SHARED \${PROJECT_SOURCE_DIR}/yololayer.cu)
target_link_libraries(myplugins nvinfer cudart)
add_executable(yolov5 \${PROJECT_SOURCE_DIR}/yolov5.cpp)
target_link_libraries(yolov5 nvinfer cudart myplugins dl pthread)
CMEOF
  cd "$TRTX_ROOT/yolov5" && mkdir -p build && cd build
  cmake .. -DCUDA_TOOLKIT_ROOT_DIR="$CUDA118"
  make -j"$(nproc)"
  TRTX_BIN="$TRTX_ROOT/yolov5/build/yolov5"
fi

CUDNN_LIB="${CUDNN86_LIB:-$DEPS/cudnn-8.6.0/lib}"
[[ -d "$CUDNN_LIB" ]] || CUDNN_LIB="/usr/lib/x86_64-linux-gnu"

export LD_LIBRARY_PATH="${CUDNN_LIB}:${TRT8_LIB}:${CUDA118}/lib64:${LD_LIBRARY_PATH:-}"
unset NVIDIA_TF32_OVERRIDE LD_PRELOAD 2>/dev/null || true

echo "[1/2] wts -> engine: $ENGINE (size=$SIZE, TRT8)"
echo "      GPU: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null || echo unknown)"
"$TRTX_BIN" -s "$WTS" "$ENGINE" "$SIZE" 2>&1 | tee /tmp/yolov5m_build_trt8.log

echo "[2/2] verify with trtexec (TRT8)"
"$TRTEXEC" --loadEngine="$ENGINE" --iterations=1 --duration=0 2>&1 | tee /tmp/verify_yolov5m_engine_trt8.log
grep -q PASSED /tmp/verify_yolov5m_engine_trt8.log && echo "RESULT: PASS" || { echo "RESULT: FAIL"; exit 2; }
