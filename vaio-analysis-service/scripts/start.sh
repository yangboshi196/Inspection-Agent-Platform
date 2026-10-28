#!/usr/bin/env bash
# Start vaio-analysis stack: C++ core + optional Python REST + MCP hint.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE_BIN="${VAIO_CORE_BIN:-$ROOT/x86_64/vaio-analysis-core}"
HTTP_PORT="${VAIO_HTTP_PORT:-9200}"
API_PORT="${VAIO_API_PORT:-9201}"

start_core() {
  if [[ ! -x "$CORE_BIN" ]]; then
    echo "Core binary not found: $CORE_BIN" >&2
    echo "Build or sync x86_64 bundle into $ROOT/x86_64" >&2
    return 1
  fi
  export VAIO_HTTP_PORT="$HTTP_PORT"
  echo "Starting vaio-analysis-core on :$HTTP_PORT ..."
  "$ROOT/scripts/run-core.sh" &
  echo $! > /tmp/vaio-analysis-core.pid
}

start_api() {
  export VAIO_CORE_BASE="http://127.0.0.1:${HTTP_PORT}"
  echo "Starting Python REST on :$API_PORT ..."
  cd "$ROOT"
  python3 -m uvicorn vaio_analysis.api_app:app --host 127.0.0.1 --port "$API_PORT" &
  echo $! > /tmp/vaio-analysis-api.pid
}

case "${1:-all}" in
  core)
    start_core
    ;;
  api)
    start_api
    ;;
  all)
    start_core
    sleep 2
    start_api
    echo "MCP (Hermes config): command=python3 args=[-m, vaio_analysis.mcp_server] cwd=$ROOT env VAIO_CORE_BASE=http://127.0.0.1:$HTTP_PORT"
    ;;
  stop)
    for f in /tmp/vaio-analysis-core.pid /tmp/vaio-analysis-api.pid; do
      if [[ -f "$f" ]]; then
        kill "$(cat "$f")" 2>/dev/null || true
        rm -f "$f"
      fi
    done
    ;;
  *)
    echo "Usage: $0 {core|api|all|stop}" >&2
    exit 1
    ;;
esac
