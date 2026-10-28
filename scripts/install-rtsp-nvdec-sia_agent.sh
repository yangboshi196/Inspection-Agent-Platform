#!/usr/bin/env bash
# 为 SIA_agent 安装 RTSP 预览依赖 + 可选 NVDEC ffmpeg（jellyfin-ffmpeg）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONDA_ENV="${SIA_CONDA_ENV:-SIA_agent}"
TOOLS_DIR="${SIA_TOOLS_DIR:-$REPO_ROOT/.tools}"
FF_VERSION="${JELLYFIN_FFMPEG_VERSION:-7.1.4-3}"
FF_DIR="$TOOLS_DIR/jellyfin-ffmpeg"
ENV_FILE="$TOOLS_DIR/rtsp-nvdec.env"

info() { printf '[rtsp-nvdec] %s\n' "$*"; }
warn() { printf '[rtsp-nvdec] %s\n' "$*" >&2; }

if ! command -v conda >/dev/null 2>&1; then
  warn "未找到 conda，请手动安装 PyAV/opencv 与 NVDEC ffmpeg"
  exit 1
fi

# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$CONDA_ENV"

info "环境: $CONDA_ENV"
pip install -U "av>=12.0.0" "opencv-python-headless>=4.8.0"

mkdir -p "$TOOLS_DIR"
ARCHIVE="$TOOLS_DIR/jellyfin-ffmpeg_${FF_VERSION}_portable_linux64-gpl.tar.xz"
LOCAL_ARCHIVE="$REPO_ROOT/scripts/jellyfin-ffmpeg_${FF_VERSION}_portable_linux64-gpl.tar.xz"
EXPECTED_SIZE=58599712

download_urls=(
  "https://repo.jellyfin.org/files/ffmpeg/linux/latest-7.x/amd64/jellyfin-ffmpeg_${FF_VERSION}_portable_linux64-gpl.tar.xz"
  "https://github.com/jellyfin/jellyfin-ffmpeg/releases/download/v${FF_VERSION}/jellyfin-ffmpeg_${FF_VERSION}_portable_linux64-gpl.tar.xz"
)

download_ffmpeg_archive() {
  local url attempt
  for url in "${download_urls[@]}"; do
    for attempt in 1 2 3; do
      info "下载 (${attempt}/3): $url"
      if curl -L --connect-timeout 30 --max-time 900 -C - "$url" -o "$ARCHIVE"; then
        local size
        size="$(stat -c '%s' "$ARCHIVE" 2>/dev/null || echo 0)"
        if [[ "$size" -ge "$EXPECTED_SIZE" ]]; then
          if xz -t "$ARCHIVE" 2>/dev/null; then
            return 0
          fi
          warn "压缩包损坏，重新下载…"
          rm -f "$ARCHIVE"
          continue
        fi
        warn "文件不完整 (${size}/${EXPECTED_SIZE})，断点续传…"
      else
        warn "下载失败，换源重试…"
      fi
    done
  done
  return 1
}

if [[ ! -x "$FF_DIR/ffmpeg" ]]; then
  if [[ -f "$LOCAL_ARCHIVE" ]] && xz -t "$LOCAL_ARCHIVE" 2>/dev/null; then
    info "使用本地包: $LOCAL_ARCHIVE"
    cp -f "$LOCAL_ARCHIVE" "$ARCHIVE"
  elif [[ ! -f "$ARCHIVE" ]] || ! xz -t "$ARCHIVE" 2>/dev/null; then
    info "下载 jellyfin-ffmpeg v${FF_VERSION}（含 NVDEC）…"
    if ! download_ffmpeg_archive; then
      warn "自动下载未完成。可手动下载后重跑本脚本，或放入:"
      warn "  $LOCAL_ARCHIVE"
      exit 1
    fi
  fi
  rm -rf "$FF_DIR"
  mkdir -p "$FF_DIR"
  tar -xJf "$ARCHIVE" -C "$FF_DIR"
fi

if ! "$FF_DIR/ffmpeg" -hide_banner -decoders 2>/dev/null | grep -q cuvid; then
  warn "jellyfin-ffmpeg 未检测到 hevc_cuvid/h264_cuvid，请检查 GPU 驱动"
fi

cat >"$ENV_FILE" <<EOF
# RTSP 预览 / NVDEC 硬解（sia-dev.sh 自动加载）
export SIA_FFMPEG="$FF_DIR/ffmpeg"
export SIA_RTSP_HWACCEL=cuda
export PATH="$FF_DIR:\$PATH"
EOF

info "已写入 $ENV_FILE"
info "下一步: source $ENV_FILE && ./scripts/verify-rtsp-nvdec-SIA_agent.sh"
info "启动 Platform 前执行: source $ENV_FILE"
