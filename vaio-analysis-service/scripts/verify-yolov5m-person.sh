#!/usr/bin/env bash
# 校验 yolov5m_person 模型是否满足 vaio-analysis-core（TRT 7.2.3.4 / RTX 3080 SM8.6）
set -euo pipefail

SERVICE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_DIR="$SERVICE_ROOT/x86_64/model"
SKILLS_ROOT="${VAIO_SKILLS_ROOT:-$(cd "$SERVICE_ROOT/../agent_skills" && pwd)}"
TRT="$SKILLS_ROOT/deps/TensorRT-7.2.3.4/targets/x86_64-linux-gnu"
NVRTC="$SKILLS_ROOT/deps/cuda11.0/usr/local/cuda-11.0/targets/x86_64-linux/lib"
TRTEXEC="$TRT/bin/trtexec"
ENGINE="$MODEL_DIR/yolov5m_person.engine"
WTS="$MODEL_DIR/yolov5m_person.wts"

export LD_LIBRARY_PATH="$TRT/lib:$NVRTC:/usr/local/cuda-11.1/lib64:${LD_LIBRARY_PATH:-}"

echo "=== 文件检查 ==="
for f in "$ENGINE" "$WTS" "$SERVICE_ROOT/x86_64/label/coco.txt" "$SERVICE_ROOT/x86_64/label/custom.txt"; do
  if [[ -f "$f" ]]; then
    echo "OK  $(basename "$f")  $(ls -lh "$f" | awk '{print $5}')"
  else
    echo "MISS $(basename "$f")"
  fi
done

if [[ -f "$ENGINE" ]]; then
  echo ""
  echo "=== trtexec 加载 engine（TRT 7.2.3.4）==="
  if "$TRTEXEC" --loadEngine="$ENGINE" --iterations=1 --duration=0 2>&1 | tee /tmp/verify_yolov5m_person.log | tail -8; then
    echo "RESULT: engine OK"
  else
    echo "RESULT: engine FAIL (见 /tmp/verify_yolov5m_person.log)"
  fi
fi

echo ""
echo "=== 配置 ==="
grep -E 'modelid="1004"' "$SERVICE_ROOT/x86_64/conf/VLAISvr_BP/AlgModelConf.xml" || true
