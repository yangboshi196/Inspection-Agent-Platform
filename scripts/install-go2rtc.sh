#!/usr/bin/env bash
# 安装 go2rtc 到 .tools/go2rtc（Linux amd64）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOLS="$REPO_ROOT/.tools"
BIN="$TOOLS/go2rtc"
VERSION="${GO2RTC_VERSION:-1.9.9}"

if [[ -x "$BIN" ]]; then
  echo "[go2rtc] 已存在: $BIN"
  "$BIN" -version 2>/dev/null || true
  exit 0
fi

mkdir -p "$TOOLS"
TMP="$(mktemp -d)"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) FILE="go2rtc_linux_amd64" ;;
  aarch64|arm64) FILE="go2rtc_linux_arm64" ;;
  *) echo "unsupported arch: $ARCH" >&2; exit 1 ;;
esac

URL="https://github.com/AlexxIT/go2rtc/releases/download/v${VERSION}/${FILE}"
echo "[go2rtc] 下载 $URL"
curl -fsSL "$URL" -o "$TMP/go2rtc"
install -m 755 "$TMP/go2rtc" "$BIN"
rm -rf "$TMP"
echo "[go2rtc] 安装完成: $BIN"
"$BIN" -version 2>/dev/null || true
