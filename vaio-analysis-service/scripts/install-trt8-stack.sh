#!/usr/bin/env bash
# Plan B: RTX 3080 stack — driver 535 + CUDA 11.8 + cuDNN 8.6 + TensorRT 8.5 (deps/)
set -euo pipefail

SERVICE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_ROOT="${VAIO_SKILLS_ROOT:-$(cd "$SERVICE_ROOT/../agent_skills" && pwd)}"
DEPS="$SKILLS_ROOT/deps"
TRT8_DIR="$DEPS/TensorRT-8.5.3.1"
CUDNN_DIR="$DEPS/cudnn-8.6.0"
CUDA118="/usr/local/cuda-11.8"

log() { echo "[install-trt8] $*"; }

if [[ $(id -u) -ne 0 ]]; then
  echo "Run with sudo: sudo bash $0" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

# Disable broken third-party apt sources if present
for f in /etc/apt/sources.list.d/*xorg* /etc/apt/sources.list.d/*docker*; do
  [[ -f "$f" && "$f" != *.disabled ]] && mv "$f" "${f}.disabled" 2>/dev/null || true
done

apt-get update -qq

log "Installing NVIDIA driver 535 (reboot required to activate)..."
apt-get install -y nvidia-driver-535 || apt-get install -y nvidia-driver-535-server

if [[ ! -f /etc/apt/sources.list.d/cuda-ubuntu2004.list ]]; then
  log "Adding NVIDIA CUDA 11.8 repository..."
  wget -q https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/cuda-keyring_1.1-1_all.deb -O /tmp/cuda-keyring.deb
  dpkg -i /tmp/cuda-keyring.deb
  apt-get update -qq
fi

log "Installing CUDA 11.8 toolkit..."
apt-get install -y cuda-toolkit-11-8

log "Installing cuDNN 8.6 for CUDA 11.x..."
apt-get install -y libcudnn8=8.6.0.*-1+cuda11.8 libcudnn8-dev=8.6.0.*-1+cuda11.8 2>/dev/null \
  || apt-get install -y libcudnn8 libcudnn8-dev

mkdir -p "$CUDNN_DIR/lib"
if [[ -d /usr/lib/x86_64-linux-gnu ]]; then
  cp -a /usr/lib/x86_64-linux-gnu/libcudnn.so.8* "$CUDNN_DIR/lib/" 2>/dev/null || true
fi

log "Deploying TensorRT 8.5 from NGC container..."
if [[ ! -x "$TRT8_DIR/bin/trtexec" ]]; then
  mkdir -p "$TRT8_DIR"
  if ! docker image inspect nvcr.io/nvidia/tensorrt:22.12-py3 >/dev/null 2>&1; then
    docker pull nvcr.io/nvidia/tensorrt:22.12-py3
  fi
  cid="$(docker create nvcr.io/nvidia/tensorrt:22.12-py3)"
  docker cp "$cid:/usr/src/tensorrt" "$TRT8_DIR/tensorrt-src" 2>/dev/null || true
  docker cp "$cid:/usr/lib/x86_64-linux-gnu/libnvinfer.so.8" "$TRT8_DIR/lib/" 2>/dev/null || true
  docker cp "$cid:/usr/lib/x86_64-linux-gnu/" "$TRT8_DIR/lib/" 2>/dev/null || true
  docker cp "$cid:/usr/bin/trtexec" "$TRT8_DIR/bin/" 2>/dev/null || true
  docker cp "$cid:/usr/include/x86_64-linux-gnu/" "$TRT8_DIR/include/" 2>/dev/null || true
  docker rm "$cid" >/dev/null

  # Normalize layout
  mkdir -p "$TRT8_DIR"/{bin,lib,include}
  for f in libnvinfer.so.8 libnvinfer_plugin.so.8 libnvonnxparser.so.8 libnvparsers.so.8 libnvinfer_builder_resource.so.8.5.3; do
    find "$TRT8_DIR" -name "$f" -exec cp -a {} "$TRT8_DIR/lib/" \; 2>/dev/null || true
  done
  find "$TRT8_DIR" -name trtexec -type f -exec cp -a {} "$TRT8_DIR/bin/" \; 2>/dev/null || true
  find "$TRT8_DIR" -path '*/NvInfer.h' -exec cp -a {} "$TRT8_DIR/include/" \; 2>/dev/null || true
  chmod +x "$TRT8_DIR/bin/trtexec" 2>/dev/null || true
fi

if [[ -L /usr/local/cuda ]] || [[ ! -e /usr/local/cuda-11.8 ]]; then
  ln -sfn "$CUDA118" /usr/local/cuda 2>/dev/null || true
fi

log "Done. Versions:"
nvidia-smi 2>/dev/null | head -3 || echo "  (reboot needed for new driver)"
"$CUDA118/bin/nvcc" --version 2>/dev/null | tail -1 || true
ls -la "$TRT8_DIR/bin/trtexec" 2>/dev/null || echo "  TRT8 trtexec: missing — check docker pull"
echo "TRT8_DIR=$TRT8_DIR"
echo "Reboot if driver was upgraded: sudo reboot"
