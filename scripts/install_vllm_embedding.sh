#!/usr/bin/env bash
# 在 SIA_agent 环境中安装 vLLM（用于 GPU 加速 embedding 推理服务）
set -euo pipefail

CONDA_ENV="${SIA_CONDA_ENV:-SIA_agent}"

if command -v conda >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate "$CONDA_ENV"
fi

echo "[install-vllm] env=$(which python)"
echo "[install-vllm] 安装 vLLM（体积较大，请耐心等待）…"

# 与 RTX 3080 + 驱动 535 匹配：优先 cu124 版 torch，再装 vllm
python -m pip install -U pip
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
python -m pip install "vllm>=0.8.0"

python - <<'PY'
import torch
print("torch", torch.__version__, "cuda_available", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu", torch.cuda.get_device_name(0))
try:
    import vllm
    print("vllm", vllm.__version__)
except Exception as e:
    print("vllm import failed:", e)
PY

echo "[install-vllm] 完成。启动服务: bash scripts/start_vllm_embedding.sh"
