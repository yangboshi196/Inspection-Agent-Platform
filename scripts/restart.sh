#!/usr/bin/env bash
# Restart sia dev stack (backend + frontend).
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/sia-dev.sh" restart "$@"
