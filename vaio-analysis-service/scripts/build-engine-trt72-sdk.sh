#!/usr/bin/env bash
# TRT 7.2: rebuild sm_86 yoloplugin + SDK wts->engine for vaio-analysis-core.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_ROOT="${VAIO_SKILLS_ROOT:-$(cd "$SERVICE_ROOT/../agent_skills" && pwd)}"
SDK_ROOT="$SKILLS_ROOT/VAIGateway/vsmartaisdk"
BUILD_DIR="$SDK_ROOT/build-trt72"
TRT_LIB="$SKILLS_ROOT/deps/TensorRT-7.2.3.4/targets/x86_64-linux-gnu/lib"
CUDA_ROOT="${CUDA_ROOT:-/usr/local/cuda-11.1}"
CUDNN81="$SKILLS_ROOT/deps/cudnn-8.1.0.77/lib"
NVRTC="$SKILLS_ROOT/deps/cuda11.0/usr/local/cuda-11.0/targets/x86_64-linux/lib"
OPENCV_LIB="$SKILLS_ROOT/deps/opencv-4.4.0_cuda11/build/lib"
SDK_LIB="$SKILLS_ROOT/VAIGateway/3rdparty/vsmartaisdk/lib"
MODEL_DIR="$SERVICE_ROOT/x86_64/model"
LABEL="$SERVICE_ROOT/x86_64/label/coco.txt"

WTS="${1:-/home/sia/tzb/WMAutoTrainPlat/wm-1.1/backend-v1.1/train/models/pre/x86/detection/yolov5/yolov5-5.0/yolov5m.wts}"
ENGINE="${2:-$MODEL_DIR/yolov5m.engine}"

export LD_LIBRARY_PATH="$BUILD_DIR:\
$SDK_LIB:\
$SKILLS_ROOT/deps:\
$OPENCV_LIB:\
$TRT_LIB:\
$CUDNN81:\
$NVRTC:\
$CUDA_ROOT/lib64:\
${LD_LIBRARY_PATH:-}"
unset NVIDIA_TF32_OVERRIDE LD_PRELOAD OPENCV_INC 2>/dev/null || true

echo "==> [1/4] Build libyoloplugin.so (sm_86)"
bash "$SDK_ROOT/build-yoloplugin-sm86.sh" "$BUILD_DIR/libyoloplugin.so"

VSMART_LIB="$SDK_ROOT/build/libvsmartaisdk.so"
if [[ ! -f "$VSMART_LIB" ]]; then
  VSMART_LIB="$SDK_LIB/libvsmartaisdk.so"
fi

echo "==> [2/4] Build wts2engine tool"
g++ -std=c++11 -O2 -o "$BUILD_DIR/wts2engine" "$SDK_ROOT/wts2engine.cpp" \
  -I"$SDK_ROOT" \
  -I/usr/include/opencv4 \
  -I"$SKILLS_ROOT/sdk_linux_v2/Include" \
  -I"$SKILLS_ROOT/VAIGateway/3rdparty/vsmartaisdk/include" \
  -L"$BUILD_DIR" -L"$(dirname "$VSMART_LIB")" \
  -lvsmartaisdk -lyoloplugin \
  -L"$OPENCV_LIB" -lopencv_world \
  -L"$TRT_LIB" -lnvinfer -lnvinfer_plugin -lnvonnxparser \
  -L"$CUDA_ROOT/lib64" -lcudart \
  -L"$SKILLS_ROOT/deps" -ldface -lMNN \
  -L"$SKILLS_ROOT/sdk_linux_v2/x86_64" -lutility -lcommon \
  -lpthread -ldl -Wl,-rpath,"$BUILD_DIR:$TRT_LIB"

echo "==> [3/4] Sync libyoloplugin.so -> 3rdparty"
install -m 644 "$BUILD_DIR/libyoloplugin.so" "$SDK_LIB/"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp "$WTS" "$WORK/"
cp "$LABEL" "$WORK/coco.txt"
ENGINE_NAME="$(basename "${WTS%.wts}.engine")"
rm -f "$WORK/$ENGINE_NAME"

echo "==> [4/4] wts -> engine on GPU"
echo "      WTS:    $WTS"
echo "      ENGINE: $ENGINE"
echo "      GPU:    $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo unknown)"
cd "$WORK"
"$BUILD_DIR/wts2engine" "$(basename "$WTS")" coco.txt 1

mkdir -p "$(dirname "$ENGINE")"
install -m 644 "$WORK/$ENGINE_NAME" "$ENGINE"
echo "Engine: $ENGINE ($(du -h "$ENGINE" | awk '{print $1}'))"

"$SCRIPT_DIR/verify-yolov5m-engine.sh" "$ENGINE"
