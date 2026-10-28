#!/usr/bin/env bash
# 启动 vLLM OpenAI 兼容 embedding 服务（Qwen3-Embedding-0.6B，默认 8100 端口）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_DIR="$REPO_ROOT/.run"
mkdir -p "$RUN_DIR"

CONDA_ENV="${SIA_CONDA_ENV:-SIA_agent}"
HOST="${SIA_VLLM_EMBED_HOST:-127.0.0.1}"
PORT="${SIA_VLLM_EMBED_PORT:-8100}"
DTYPE="${SIA_VLLM_EMBED_DTYPE:-float16}"
MAX_LEN="${SIA_VLLM_EMBED_MAX_MODEL_LEN:-8192}"
GPU_UTIL="${SIA_VLLM_EMBED_GPU_MEMORY_UTILIZATION:-0.35}"

resolve_model() {
  if [[ -n "${SIA_VLLM_EMBED_MODEL:-}" ]]; then
    echo "$SIA_VLLM_EMBED_MODEL"
    return
  fi
  if [[ -n "${SIA_EMBEDDING_MODEL_PATH:-}" && -d "$SIA_EMBEDDING_MODEL_PATH" ]]; then
    echo "$SIA_EMBEDDING_MODEL_PATH"
    return
  fi
  local save="$REPO_ROOT/models/qwen3-embedding-0.6b"
  if [[ -f "$save/config.json" ]]; then
    echo "$save"
    return
  fi
  local cache_root="$REPO_ROOT/models/models--Qwen--Qwen3-Embedding-0.6B/snapshots"
  if [[ -d "$cache_root" ]]; then
    local snap
    snap="$(find "$cache_root" -mindepth 1 -maxdepth 1 -type d | head -1)"
    if [[ -f "$snap/config.json" ]]; then
      echo "$snap"
      return
    fi
  fi
  echo "Qwen/Qwen3-Embedding-0.6B"
}

MODEL="$(resolve_model)"
LOG="$RUN_DIR/vllm-embedding.log"
PID_FILE="$RUN_DIR/vllm-embedding.pid"

if command -v conda >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate "$CONDA_ENV"
fi

if ! python -c "import vllm" 2>/dev/null; then
  echo "[vllm-embed] 未安装 vllm，请先运行: bash scripts/install_vllm_embedding.sh" >&2
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "[vllm-embed] 已在运行 pid=$old_pid url=http://${HOST}:${PORT}/v1"
    exit 0
  fi
fi

echo "[vllm-embed] model=$MODEL"
echo "[vllm-embed] listen=http://${HOST}:${PORT}/v1"
echo "[vllm-embed] log=$LOG"

nohup vllm serve "$MODEL" \
  --runner pooling \
  --host "$HOST" \
  --port "$PORT" \
  --dtype "$DTYPE" \
  --max-model-len "$MAX_LEN" \
  --gpu-memory-utilization "$GPU_UTIL" \
  --trust-remote-code \
  >>"$LOG" 2>&1 &

echo $! >"$PID_FILE"
echo "[vllm-embed] started pid=$(cat "$PID_FILE")"
