#!/usr/bin/env bash
# Install/sync Hermes CLI source files and core Python deps for /chat.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HERMES_DIR="$REPO_ROOT/inspection_platform/hermes_agent"
CONDA_ENV="${SIA_CONDA_ENV:-SIA_agent}"

SOURCE_FILES=(
  cli.py
  hermes_bootstrap.py
  hermes_cli/mcp_startup.py
  hermes_cli/partial_compress.py
  hermes_cli/prompt_size.py
)

info() { printf '[install-hermes-cli] %s\n' "$*"; }
die() { printf '[install-hermes-cli] %s\n' "$*" >&2; exit 1; }

find_conda_root() {
    if [[ -n "${CONDA_EXE:-}" && -x "${CONDA_EXE}" ]]; then
        dirname "$(dirname "$CONDA_EXE")"
        return 0
    fi
    for candidate in "${HOME}/miniconda3" "${HOME}/anaconda3" "/home/test/miniconda3"; do
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
    fi
    command -v python3 || command -v python || die "Python not found"
}

resolve_pip() {
    local py pip
    py="$(resolve_python)"
    pip="$(dirname "$py")/pip"
    [[ -x "$pip" ]] || die "pip not found for $py"
    printf '%s' "$pip"
}

fetch_upstream_file() {
    local rel="$1"
    local api_json out
    api_json="$(mktemp)"
    out="$HERMES_DIR/$rel"
    info "sync $rel ..."
    if ! curl -fsSL --connect-timeout 20 --max-time 120 \
        "https://api.github.com/repos/NousResearch/hermes-agent/contents/${rel}?ref=main" \
        -o "$api_json"; then
        rm -f "$api_json"
        die "failed to download ${rel} (check network/GitHub access)"
    fi
    "$(resolve_python)" - <<'PY' "$api_json" "$out"
import base64, json, pathlib, sys
src = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
data = json.loads(src.read_text())
content = base64.b64decode(data["content"]).decode("utf-8")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(content)
print(f"written {out} ({len(content.splitlines())} lines)")
PY
    rm -f "$api_json"
}

main() {
    [[ -d "$HERMES_DIR" ]] || die "hermes_agent directory not found: $HERMES_DIR"

    for rel in "${SOURCE_FILES[@]}"; do
        local out="$HERMES_DIR/$rel"
        if [[ ! -f "$out" ]] || ! "$(resolve_python)" -m py_compile "$out" 2>/dev/null; then
            [[ -f "$out" ]] && warn "repairing invalid file: $rel"
            fetch_upstream_file "$rel"
        else
            info "present: $rel"
        fi
    done

    info "installing Hermes core Python deps in ${CONDA_ENV} ..."
    "$(resolve_pip)" install \
        prompt_toolkit rich openai pyyaml fire croniter psutil \
        'PyJWT[crypto]' jinja2 ruamel.yaml python-dotenv tenacity ptyprocess

    info "verifying cli import ..."
    (
        cd "$HERMES_DIR"
        "$(resolve_python)" -c "
import cli
from hermes_cli.mcp_startup import wait_for_mcp_discovery
assert hasattr(cli, 'main') and hasattr(cli, 'HermesCLI')
print('cli import ok')
"
    )

    info "done. restart dev stack if it is already running:"
    info "  ./scripts/restart.sh"
    info "On first platform start, ui-tui is synced and built automatically for /chat."
}

main "$@"
