#!/usr/bin/env bash
# Extract TensorRT 8.5 libs/headers/trtexec from NGC container into agent_skills/deps.
set -euo pipefail

SERVICE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_ROOT="${VAIO_SKILLS_ROOT:-$(cd "$SERVICE_ROOT/../agent_skills" && pwd)}"
TRT8="$SKILLS_ROOT/deps/TensorRT-8.5.3.1"
IMAGE="${TRT8_DOCKER_IMAGE:-nvcr.io/nvidia/tensorrt:22.12-py3}"

mkdir -p "$TRT8"/{bin,lib,include}
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "[1/4] pull $IMAGE"
docker pull "$IMAGE"

echo "[2/4] extract from container"
cid="$(docker create "$IMAGE")"
docker cp "$cid:/usr/lib/x86_64-linux-gnu/." "$TMP/lib/"
docker cp "$cid:/usr/include/x86_64-linux-gnu/." "$TMP/inc/" 2>/dev/null || true
docker cp "$cid:/usr/src/tensorrt/include/." "$TMP/trtinc/" 2>/dev/null || true
docker cp "$cid:/usr/src/tensorrt/bin/trtexec" "$TMP/trtexec" 2>/dev/null || \
  docker cp "$cid:/usr/bin/trtexec" "$TMP/trtexec" 2>/dev/null || true
docker rm "$cid" >/dev/null

echo "[3/4] install to $TRT8"
for f in libnvinfer.so.8 libnvinfer_plugin.so.8 libnvonnxparser.so.8 libnvparsers.so.8 \
         libnvinfer_builder_resource.so.8.5.3 libnvinfer_builder_resource.so.8.5.2; do
  [[ -f "$TMP/lib/$f" ]] && cp -a "$TMP/lib/$f" "$TRT8/lib/"
done
for f in "$TMP/lib"/libnvinfer.so.8.* "$TMP/lib"/libnvinfer_plugin.so.8.*; do
  [[ -f "$f" ]] && cp -a "$f" "$TRT8/lib/" 2>/dev/null || true
done
cp -a "$TMP/trtinc/"*.h "$TRT8/include/" 2>/dev/null || cp -a "$TMP/inc/"*.h "$TRT8/include/" 2>/dev/null || true
[[ -f "$TMP/trtexec" ]] && cp -a "$TMP/trtexec" "$TRT8/bin/" && chmod +x "$TRT8/bin/trtexec"

echo "[4/4] verify"
ls -la "$TRT8/lib/libnvinfer.so.8" "$TRT8/bin/trtexec"
"$TRT8/bin/trtexec" --version 2>&1 | head -3 || true
echo "TRT8 ready: $TRT8"
