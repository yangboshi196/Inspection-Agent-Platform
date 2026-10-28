#!/usr/bin/env bash
# 兼容旧名：转发到 patch-algorithm-config.sh
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/patch-algorithm-config.sh" "$@"
