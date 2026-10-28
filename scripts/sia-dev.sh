#!/usr/bin/env bash
# sia dev stack control (webui + inspection_platform)
# Usage:
#   ./scripts/sia-dev.sh start|stop|restart|status [all|platform|webui]
#   ./scripts/restart.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_DIR="$REPO_ROOT/.run"
WEBUI_DIR="$REPO_ROOT/webui"
HERMES_DIR="$REPO_ROOT/inspection_platform/hermes_agent"

CONDA_ENV="${SIA_CONDA_ENV:-SIA_agent}"
PLATFORM_PORT="${inspection_platform_PORT:-8001}"
WEBUI_PORT="${SIA_WEBUI_PORT:-5173}"
WEBUI_HOST="${SIA_WEBUI_HOST:-0.0.0.0}"
GO2RTC_PORT="${SIA_GO2RTC_PORT:-1984}"
GO2RTC_RTSP_PORT="${SIA_GO2RTC_RTSP_PORT:-8554}"

ACTION="status"
TARGET="all"

info() { printf '[sia-dev] %s\n' "$*"; }
warn() { printf '[sia-dev] %s\n' "$*" >&2; }
die() { printf '[sia-dev] %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Usage:
  ./scripts/sia-dev.sh <start|stop|restart|status> [all|platform|webui|go2rtc]
  ./scripts/sia-dev.sh <start|stop|restart|status> --target <all|platform|webui|go2rtc>
  ./scripts/restart.sh

Services:
  go2rtc    go2rtc media bridge   (api ${GO2RTC_PORT}, rtsp ${GO2RTC_RTSP_PORT})
  platform  inspection_platform backend (port ${PLATFORM_PORT}, conda env ${CONDA_ENV})
  webui     Vite dev server      (port ${WEBUI_PORT})

Environment overrides:
  SIA_CONDA_ENV       conda env name (default: SIA_agent)
  inspection_platform_PORT   backend port   (default: 8001)
  SIA_WEBUI_PORT      frontend port  (default: 5173)
  SIA_NODE            node binary    (auto-detect if unset)
  SIA_NPM_CLI         npm-cli.js path (auto-detect if unset)
  HERMES_PYTHON          set automatically to ${CONDA_ENV} python when starting platform
  SIA_RTSP_ENV        RTSP/NVDEC env file (default: .tools/rtsp-nvdec.env, auto-sourced if present)
  SIA_FFMPEG          ffmpeg with NVDEC (set by install-rtsp-nvdec-SIA_agent.sh)
  SIA_RTSP_HWACCEL    cuda|soft — RTSP decode mode (default soft if unset)
  SIA_GO2RTC_PORT     go2rtc API port (default 1984)
  SIA_GO2RTC_RTSP_PORT go2rtc RTSP port (default 8554)
EOF
}

parse_args() {
    if [[ $# -gt 0 && "$1" != --* ]]; then
        ACTION="$1"
        shift
    fi

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --target|-Target)
                [[ $# -ge 2 ]] || die "missing value for $1"
                TARGET="$2"
                shift 2
                ;;
            all|platform|webui|go2rtc)
                TARGET="$1"
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                die "unknown argument: $1"
                ;;
        esac
    done

    case "$ACTION" in
        start|stop|restart|status) ;;
        *) die "unknown action: $ACTION (use start|stop|restart|status)" ;;
    esac

    case "$TARGET" in
        all|platform|webui|go2rtc) ;;
        *) die "unknown target: $TARGET (use all|platform|webui|go2rtc)" ;;
    esac
}

ensure_run_dir() {
    mkdir -p "$RUN_DIR"
}

service_name() {
    case "$1" in
        go2rtc) printf 'go2rtc' ;;
        platform) printf 'inspection_platform' ;;
        webui) printf 'webui' ;;
        *) die "internal error: unknown service key $1" ;;
    esac
}

service_port() {
    case "$1" in
        go2rtc) printf '%s' "$GO2RTC_PORT" ;;
        platform) printf '%s' "$PLATFORM_PORT" ;;
        webui) printf '%s' "$WEBUI_PORT" ;;
        *) die "internal error: unknown service key $1" ;;
    esac
}

service_url() {
    case "$1" in
        go2rtc) printf 'http://127.0.0.1:%s/' "$GO2RTC_PORT" ;;
        platform) printf 'http://127.0.0.1:%s/' "$PLATFORM_PORT" ;;
        webui) printf 'http://127.0.0.1:%s/' "$WEBUI_PORT" ;;
        *) die "internal error: unknown service key $1" ;;
    esac
}

service_workdir() {
    case "$1" in
        go2rtc) printf '%s' "$REPO_ROOT" ;;
        platform) printf '%s' "$REPO_ROOT" ;;
        webui) printf '%s' "$WEBUI_DIR" ;;
        *) die "internal error: unknown service key $1" ;;
    esac
}

pid_file() {
    printf '%s/%s.pid' "$RUN_DIR" "$1"
}

log_file() {
    printf '%s/%s.log' "$RUN_DIR" "$1"
}

read_stored_pid() {
    local file
    file="$(pid_file "$1")"
    if [[ -f "$file" ]]; then
        tr -d '[:space:]' <"$file"
    fi
}

remove_stored_pid() {
    rm -f "$(pid_file "$1")"
}

get_listen_pids() {
    local port="$1"
    local pids=""

    if command -v ss >/dev/null 2>&1; then
        pids="$(ss -ltnpH "sport = :${port}" 2>/dev/null \
            | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' \
            | sort -u)"
    elif command -v lsof >/dev/null 2>&1; then
        pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u)"
    elif command -v netstat >/dev/null 2>&1; then
        pids="$(netstat -tlnp 2>/dev/null \
            | awk -v port=":${port}" '$4 ~ port"$" && $6 == "LISTEN" { split($7, parts, "/"); print parts[1] }' \
            | sort -u)"
    else
        die "need ss, lsof, or netstat to detect listening ports"
    fi

    if [[ -n "$pids" ]]; then
        printf '%s\n' "$pids"
    fi
}

is_listening() {
    local port
    port="$(service_port "$1")"
    [[ -n "$(get_listen_pids "$port")" ]]
}

stop_process_safe() {
    local process_id="$1"
    if [[ -z "$process_id" || "$process_id" -le 0 ]]; then
        return 0
    fi
    if kill -0 "$process_id" 2>/dev/null; then
        kill "$process_id" 2>/dev/null || true
        for _ in $(seq 1 20); do
            kill -0 "$process_id" 2>/dev/null || return 0
            sleep 0.2
        done
        kill -9 "$process_id" 2>/dev/null || true
    fi
}

stop_service() {
    local key="$1"
    local name port stored_pid process_id stopped=0

    name="$(service_name "$key")"
    port="$(service_port "$key")"
    stored_pid="$(read_stored_pid "$key" || true)"

    if [[ -n "$stored_pid" ]]; then
        stop_process_safe "$stored_pid"
        stopped=1
    fi

    while IFS= read -r process_id; do
        [[ -n "$process_id" ]] || continue
        stop_process_safe "$process_id"
        stopped=1
    done < <(get_listen_pids "$port")

    # Also stop child processes started by nohup/shell wrappers.
    case "$key" in
        go2rtc)
            pkill -f "${REPO_ROOT}/.tools/go2rtc" 2>/dev/null || true
            ;;
        platform)
            pkill -f "uvicorn inspection_platform.app.main:app.*--port ${port}" 2>/dev/null || true
            pkill -f "uvicorn inspection_platform.app:app.*--port ${port}" 2>/dev/null || true
            ;;
        webui)
            pkill -f "vite.*--port ${port}" 2>/dev/null || true
            ;;
    esac

    remove_stored_pid "$key"

    if [[ "$stopped" -eq 1 ]]; then
        info "stopped $name (port $port)"
    else
        info "$name is not running"
    fi
}

find_conda_root() {
    if [[ -n "${CONDA_EXE:-}" && -x "${CONDA_EXE}" ]]; then
        dirname "$(dirname "$CONDA_EXE")"
        return 0
    fi
    local candidate
    for candidate in \
        "${HOME}/miniconda3" \
        "${HOME}/anaconda3" \
        "/home/test/miniconda3"; do
        if [[ -x "${candidate}/bin/conda" ]]; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

resolve_python() {
    local conda_root env_python
    if conda_root="$(find_conda_root)"; then
        env_python="${conda_root}/envs/${CONDA_ENV}/bin/python"
        if [[ -x "$env_python" ]]; then
            printf '%s' "$env_python"
            return 0
        fi
        die "conda env '${CONDA_ENV}' not found at ${conda_root}/envs/${CONDA_ENV}; run: conda create -n ${CONDA_ENV} python=3.10 -y && pip install -e ."
    fi

    if command -v python3 >/dev/null 2>&1; then
        printf 'python3'
    elif command -v python >/dev/null 2>&1; then
        printf 'python'
    else
        die "Python not found in PATH"
    fi
}

find_node_bin() {
    if [[ -n "${SIA_NODE:-}" && -x "${SIA_NODE}" ]]; then
        printf '%s' "${SIA_NODE}"
        return 0
    fi

    local candidate cursor_node
    cursor_node="$(ls -td "${HOME}/.cursor-server/bin/linux-x64/"*/node 2>/dev/null | head -1 || true)"
    for candidate in \
        "$cursor_node" \
        "${HOME}/miniconda3/envs/yolov5_py38/bin/node" \
        "/home/test/miniconda3/envs/yolov5_py38/bin/node" \
        "$(command -v node 2>/dev/null || true)"; do
        [[ -n "$candidate" && -x "$candidate" ]] || continue
        printf '%s' "$candidate"
        return 0
    done
    return 1
}

find_npm_cli_js() {
    if [[ -n "${SIA_NPM_CLI:-}" && -f "${SIA_NPM_CLI}" ]]; then
        printf '%s' "${SIA_NPM_CLI}"
        return 0
    fi

    local candidate
    for candidate in \
        "${HOME}/miniconda3/envs/yolov5_py38/lib/node_modules/npm/bin/npm-cli.js" \
        "/home/test/miniconda3/envs/yolov5_py38/lib/node_modules/npm/bin/npm-cli.js"; do
        [[ -f "$candidate" ]] || continue
        printf '%s' "$candidate"
        return 0
    done
    return 1
}

run_npm() {
    local node_bin npm_cli

    node_bin="$(find_node_bin)" || die "node not found; set SIA_NODE to a node binary"
    npm_cli="$(find_npm_cli_js)" || die "npm-cli.js not found; set SIA_NPM_CLI"
    "$node_bin" "$npm_cli" "$@"
}

ensure_npm_shim() {
    local node_bin npm_cli shim_dir shim

    node_bin="$(find_node_bin)" || return 1
    npm_cli="$(find_npm_cli_js)" || return 1
    shim_dir="$RUN_DIR/bin"
    shim="$shim_dir/npm"
    mkdir -p "$shim_dir"
    cat >"$shim" <<EOF
#!/usr/bin/env bash
exec "$node_bin" "$npm_cli" "\$@"
EOF
    chmod +x "$shim"
    printf '%s' "$shim_dir"
}

load_llm_env() {
    local env_file
    for env_file in \
        "${SIA_ENV_FILE:-}" \
        "${REPO_ROOT}/.env" \
        "${HOME}/.hermes/.env"; do
        [[ -n "$env_file" && -f "$env_file" ]] || continue
        set -a
        # shellcheck disable=SC1090
        source "$env_file"
        set +a
        info "loaded LLM env from $env_file"
        return 0
    done
}

load_rtsp_nvdec_env() {
    local env_file="${SIA_RTSP_ENV:-$REPO_ROOT/.tools/rtsp-nvdec.env}"
    [[ -f "$env_file" ]] || return 0
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
    info "loaded RTSP/NVDEC env from $env_file"
}

setup_dev_env() {
    local node_bin node_dir npm_shim_dir python_bin

    load_llm_env
    load_rtsp_nvdec_env

    node_bin="$(find_node_bin)" || die "node not found; set SIA_NODE to a node binary"
    node_dir="$(dirname "$node_bin")"
    npm_shim_dir="$(ensure_npm_shim || true)"
    python_bin="$(resolve_python)"

    if [[ -n "$npm_shim_dir" ]]; then
        export PATH="${npm_shim_dir}:${node_dir}:${PATH}"
    else
        export PATH="${node_dir}:${PATH}"
    fi
    export HERMES_NODE="$node_bin"
    export HERMES_PYTHON="$python_bin"
    export HERMES_PYTHON_SRC_ROOT="$HERMES_DIR"
}

sync_hermes_ui_tui() {
    local tui_dir="$HERMES_DIR/ui-tui"
    local entry="$tui_dir/dist/entry.js"
    local bundled="$HERMES_DIR/hermes_cli/tui_dist/entry.js"
    local tmp tarball src

    [[ -f "$entry" || -f "$bundled" ]] && return 0

    info "syncing ui-tui from NousResearch/hermes-agent (first run may take a few minutes) ..."
    tmp="$(mktemp -d)"
    tarball="$tmp/hermes-agent-main.tar.gz"
    if ! curl -fsSL --connect-timeout 30 --max-time 600 \
        -o "$tarball" \
        "https://codeload.github.com/NousResearch/hermes-agent/tar.gz/refs/heads/main"; then
        rm -rf "$tmp"
        die "failed to download ui-tui (check network/GitHub access)"
    fi

    tar xzf "$tarball" -C "$tmp"
    src="$(find "$tmp" -maxdepth 2 -type d -name ui-tui | head -1)"
    [[ -n "$src" && -d "$src" ]] || die "ui-tui not found in downloaded hermes-agent archive"
    rm -rf "$tui_dir"
    mv "$src" "$tui_dir"
    rm -rf "$tmp"

    info "building Hermes TUI (npm install + build) ..."
    (cd "$tui_dir" && run_npm install --no-fund --no-audit && run_npm run build)
    [[ -f "$entry" ]] || die "Hermes TUI build failed: $entry not found"
    info "Hermes TUI ready: $entry"
}

ensure_go2rtc_binary() {
    local bin="$REPO_ROOT/.tools/go2rtc"
    if [[ -x "$bin" ]]; then
        return 0
    fi
    info "go2rtc not found; running scripts/install-go2rtc.sh ..."
    bash "$REPO_ROOT/scripts/install-go2rtc.sh"
}

assert_prerequisites() {
    local key="$1"
    local python node_bin

    setup_dev_env

    case "$key" in
        go2rtc)
            ensure_go2rtc_binary
            [[ -f "$REPO_ROOT/deploy/go2rtc.yaml" ]] || die "deploy/go2rtc.yaml not found"
            ;;
        platform)
            python="$(resolve_python)"
            if ! (cd "$REPO_ROOT" && "$python" -c "import inspection_platform" >/dev/null 2>&1); then
                die "Cannot import inspection_platform; run: conda activate ${CONDA_ENV} && pip install -e ."
            fi
            sync_hermes_ui_tui
            ;;
        webui)
            [[ -f "$WEBUI_DIR/package.json" ]] || die "webui/package.json not found"
            if [[ ! -d "$WEBUI_DIR/node_modules" || ! -f "$WEBUI_DIR/node_modules/vite/bin/vite.js" ]]; then
                warn "webui dependencies missing or incomplete; running npm install --legacy-peer-deps ..."
                (cd "$WEBUI_DIR" && run_npm install --legacy-peer-deps)
            fi
            ;;
    esac
}

wait_for_listen() {
    local key="$1"
    local process_id="$2"
    local log="$3"
    local i

    for i in $(seq 1 60); do
        if is_listening "$key"; then
            return 0
        fi
        if ! kill -0 "$process_id" 2>/dev/null; then
            die "$(service_name "$key") failed to start; see log: $log"
        fi
        sleep 0.5
    done

    die "$(service_name "$key") start timed out after 30s; see log: $log"
}

wait_for_health() {
    local i
    for i in $(seq 1 20); do
        if curl -sf "http://127.0.0.1:${PLATFORM_PORT}/api/health" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.5
    done
    warn "backend health check did not pass yet; see log: $(log_file platform)"
}

start_service() {
    local key="$1"
    local name port url workdir log pidfile python process_id node_bin

    name="$(service_name "$key")"
    port="$(service_port "$key")"
    url="$(service_url "$key")"
    workdir="$(service_workdir "$key")"
    log="$(log_file "$key")"
    pidfile="$(pid_file "$key")"

    if is_listening "$key"; then
        warn "$name already listening on port $port; skip"
        return 0
    fi

    assert_prerequisites "$key"
    ensure_run_dir
    : >"$log"

    case "$key" in
        go2rtc)
            ensure_go2rtc_binary
            (
                cd "$workdir"
                exec "$REPO_ROOT/.tools/go2rtc" -config "$REPO_ROOT/deploy/go2rtc.yaml"
            ) >>"$log" 2>&1 &
            process_id=$!
            ;;
        platform)
            python="$(resolve_python)"
            setup_dev_env
            (
                cd "$workdir"
                exec "$python" -m uvicorn inspection_platform.app.main:app \
                    --host 127.0.0.1 --port "$port" --reload
            ) >>"$log" 2>&1 &
            process_id=$!
            ;;
        webui)
            setup_dev_env
            node_bin="$(find_node_bin)"
            (
                cd "$workdir"
                exec "$node_bin" "$workdir/node_modules/vite/bin/vite.js" \
                    --host "$WEBUI_HOST" --port "$port"
            ) >>"$log" 2>&1 </dev/null &
            process_id=$!
            ;;
    esac

    printf '%s\n' "$process_id" >"$pidfile"
    wait_for_listen "$key" "$process_id" "$log"
    if [[ "$key" == "platform" ]]; then
        wait_for_health
    fi
    info "started $name -> $url (pid $process_id)"
    info "log: $log"
}

show_status() {
    local key="$1"
    local name port url stored_pid pids state pid_text extra=""

    name="$(service_name "$key")"
    port="$(service_port "$key")"
    url="$(service_url "$key")"
    stored_pid="$(read_stored_pid "$key" || true)"
    pids="$(get_listen_pids "$port" | paste -sd, - || true)"

    if is_listening "$key"; then
        state="RUNNING"
        pid_text="${pids:-unknown}"
        printf '  %-16s %-7s port=%s pid=%s url=%s\n' "$name" "$state" "$port" "$pid_text" "$url"
    else
        state="STOPPED"
        if [[ -n "$stored_pid" ]]; then
            extra=" (stale pid file: $stored_pid)"
        fi
        printf '  %-16s %-7s port=%s%s\n' "$name" "$state" "$port" "$extra"
    fi
}

invoke_status() {
    info "status (repo: $REPO_ROOT)"
    show_status go2rtc
    show_status platform
    show_status webui
}

should_run() {
    local key="$1"
    [[ "$TARGET" == "all" || "$TARGET" == "$key" ]]
}

invoke_start() {
    if should_run go2rtc || should_run platform || [[ "$TARGET" == "all" ]]; then
        start_service go2rtc
    fi
    if should_run platform; then
        start_service platform
    fi
    if should_run webui; then
        start_service webui
    fi
}

invoke_stop() {
    if should_run webui; then
        stop_service webui
    fi
    if should_run platform; then
        stop_service platform
    fi
    if should_run go2rtc || should_run platform || [[ "$TARGET" == "all" ]]; then
        stop_service go2rtc
    fi
}

main() {
    parse_args "$@"

    case "$ACTION" in
        start)
            invoke_start
            invoke_status
            ;;
        stop)
            invoke_stop
            invoke_status
            ;;
        restart)
            invoke_stop
            sleep 1
            invoke_start
            invoke_status
            ;;
        status)
            invoke_status
            ;;
    esac
}

main "$@"
