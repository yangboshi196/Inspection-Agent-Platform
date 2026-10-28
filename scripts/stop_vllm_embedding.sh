#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$REPO_ROOT/.run/vllm-embedding.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "[vllm-embed] 未运行（无 pid 文件）"
  exit 0
fi

pid="$(cat "$PID_FILE")"
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  echo "[vllm-embed] stopped pid=$pid"
else
  echo "[vllm-embed] 进程不存在 pid=$pid"
fi
rm -f "$PID_FILE"
