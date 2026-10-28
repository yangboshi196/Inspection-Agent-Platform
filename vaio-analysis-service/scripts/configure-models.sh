#!/usr/bin/env bash
# 配置 vaio-analysis-service/x86_64/model 下 TensorRT engine，并同步 AlgModelConf.xml。
#
# 用法:
#   ./configure-models.sh                 # 检查 + 写配置 + 校验 engine
#   ./configure-models.sh --build-missing # 在本机 GPU 重新编译 engine（sm_86 / TRT7.2）
#   ./configure-models.sh --check-only    # 仅检查文件与 XML，不跑 trtexec
#   ./configure-models.sh --enable-face   # 启用 1031 人脸识别（需 dface 授权）
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_ROOT="${VAIO_SKILLS_ROOT:-$(cd "$SERVICE_ROOT/../agent_skills" 2>/dev/null && pwd || echo "")}"
MODEL_DIR="$SERVICE_ROOT/x86_64/model"
CONF_DIR="$SERVICE_ROOT/x86_64/conf/VLAISvr_BP"
ALG_CONF="$CONF_DIR/AlgModelConf.xml"
REF_MODEL_DIR="${VAIO_REF_MODEL_DIR:-$SKILLS_ROOT/VAIGateway/bin/x86_64/model}"

DO_BUILD=0
CHECK_ONLY=0
ENABLE_FACE=0

usage() {
  sed -n '2,10p' "$0"
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build-missing) DO_BUILD=1 ;;
    --check-only) CHECK_ONLY=1 ;;
    --enable-face) ENABLE_FACE=1 ;;
    -h|--help) usage 0 ;;
    *) echo "未知参数: $1" >&2; usage 1 ;;
  esac
  shift
done

# modelid -> engine 相对路径 | wts(可选) | 是否 YOLO 插件
DEFAULT_YOLOV5M_WTS="/home/sia/tzb/WMAutoTrainPlat/wm-1.1/backend-v1.1/train/models/pre/x86/detection/yolov5/yolov5-5.0/yolov5m.wts"
HRNET_ONNX="${VAIO_HRNET_ONNX:-$SKILLS_ROOT/VAIGateway/vsmartaisdk/build/hrnet.onnx}"

declare -A MODEL_ENGINE=(
  [1004]="yolov5m_person.engine"
  [1005]="hrnet.engine"
  [1006]="yolov5m.engine"
)
declare -A MODEL_WTS=(
  [1004]="yolov5m_person.wts"
  [1006]="yolov5m.wts"
)
declare -A MODEL_WTS_FALLBACK=(
  [1006]="$DEFAULT_YOLOV5M_WTS"
)
declare -A MODEL_YOLO=(
  [1004]=1
  [1005]=0
  [1006]=1
)
declare -A JSON_MODELID=(
  [1004]=4
  [1005]=5
  [1006]=6
  [1031]=31
)

ok()  { echo "  OK   $*"; }
warn(){ echo "  WARN $*"; }
fail(){ echo "  FAIL $*" >&2; }

check_ptrt_magic() {
  local f="$1"
  [[ -f "$f" ]] || return 1
  head -c 4 "$f" | xxd -p | grep -q 70747274
}

sync_ref_engine() {
  local name="$1"
  local dst="$MODEL_DIR/$name"
  [[ -f "$dst" ]] && return 0
  [[ -d "$REF_MODEL_DIR" ]] || return 1
  [[ -f "$REF_MODEL_DIR/$name" ]] || return 1
  install -m 644 "$REF_MODEL_DIR/$name" "$dst"
  ok "已从参考目录同步 $name"
}

ensure_yolo_engine() {
  local modelid="$1"
  local engine_name="${MODEL_ENGINE[$modelid]}"
  local wts_name="${MODEL_WTS[$modelid]:-}"
  local engine_path="$MODEL_DIR/$engine_name"

  if [[ "$DO_BUILD" -eq 0 ]]; then
    if [[ -f "$engine_path" ]] && check_ptrt_magic "$engine_path"; then
      ok "$engine_name 已存在"
      return 0
    fi
    sync_ref_engine "$engine_name" || true
    if [[ -f "$engine_path" ]] && check_ptrt_magic "$engine_path"; then
      return 0
    fi
    fail "$engine_name 缺失；加 --build-missing 从 wts 编译"
    return 1
  fi

  local wts_path=""
  if [[ -n "$wts_name" ]]; then
    wts_path="$MODEL_DIR/$wts_name"
    if [[ ! -f "$wts_path" ]]; then
      wts_path="${MODEL_WTS_FALLBACK[$modelid]:-}"
    fi
  fi
  if [[ -z "$wts_path" || ! -f "$wts_path" ]]; then
    fail "$engine_name 无法编译：缺少 wts (${wts_name:-<无>})"
    return 1
  fi

  echo "==> 编译 $engine_name (modelid $modelid)"
  bash "$SCRIPT_DIR/build-engine-trt72-sdk.sh" \
    "$wts_path" \
    "$engine_path"
}

ensure_hrnet_onnx() {
  local onnx_path="$MODEL_DIR/hrnet.onnx"
  if [[ -f "$onnx_path" ]]; then
    ok "hrnet.onnx 已存在"
    return 0
  fi
  if [[ -f "$HRNET_ONNX" ]]; then
    ln -sf "$HRNET_ONNX" "$onnx_path"
    ok "hrnet.onnx -> $HRNET_ONNX"
    return 0
  fi
  fail "hrnet.onnx 缺失（SDK 需 .onnx 路径以加载 hrnet.engine）"
  return 1
}

ensure_hrnet_engine() {
  local engine_path="$MODEL_DIR/hrnet.engine"
  ensure_hrnet_onnx || return 1

  if [[ "$DO_BUILD" -eq 0 ]]; then
    if [[ -f "$engine_path" ]] && check_ptrt_magic "$engine_path"; then
      ok "hrnet.engine 已存在 ($(du -h "$engine_path" | awk '{print $1}'))"
      return 0
    fi
    fail "hrnet.engine 缺失；加 --build-missing 从 hrnet.onnx 编译"
    return 1
  fi

  if [[ ! -f "$HRNET_ONNX" ]]; then
    fail "hrnet.onnx 不存在: $HRNET_ONNX"
    return 1
  fi

  echo "==> 编译 hrnet.engine"
  bash "$SCRIPT_DIR/build-hrnet-engine.sh" "$HRNET_ONNX" "$engine_path"
}

write_alg_model_conf() {
  local face_use=0
  [[ "$ENABLE_FACE" -eq 1 ]] && face_use=1

  local backup=""
  if [[ -f "$ALG_CONF" ]]; then
    backup="${ALG_CONF}.bak-$(date +%Y%m%d-%H%M%S)"
    cp -a "$ALG_CONF" "$backup"
    ok "已备份原配置 -> $(basename "$backup")"
  fi

  cat > "$ALG_CONF" <<EOF
<?xml version="1.0" encoding="utf-8" ?>
<AlgModelConf>

	<!-- x86 + TensorRT 7.2 / sm_86：Algorithm_*.json 中 modelid N 映射为 AlgModelConf modelid 1000+N -->
	<!-- modeluse: 1=检测, 2=识别(姿态); type: 2=x86 GPU -->
	<!-- 由 scripts/configure-models.sh 生成/更新 -->
	<!-- model 须为 .wts/.onnx，vsmartaisdk 映射同名 .engine（勿直接写 .engine） -->
	<ModelConf modelid="1004" name="人体检测(YOLOv5m)" version="v1.0.1" modeluse="1" type="2" model="./model/yolov5m_person.wts" classfile="./label/coco.txt" recthreshold="0.5" strthreshold="0.45" />
	<ModelConf modelid="1005" name="姿态估计(HRNet)" version="v1.0.1" modeluse="2" type="2" model="./model/hrnet.onnx" classfile="hrnet" recthreshold="0.5" strthreshold="0.085" />
	<ModelConf modelid="1006" name="COCO通用检测(YOLOv5m)" version="v1.0.1" modeluse="1" type="2" model="./model/yolov5m.wts" classfile="./label/coco.txt" recthreshold="0.5" strthreshold="0.3" />
	<!-- 1031 需 dface 授权；无 license 时 modeluse=0 避免启动 segfault -->
	<ModelConf modelid="1031" name="人脸识别" version="v1.0.1" modeluse="${face_use}" type="2" model="./model/dface" classfile="face" recthreshold="0.5" strthreshold="0.45" />
</AlgModelConf>
EOF
  ok "已写入 $ALG_CONF"
}

verify_yolo_engine() {
  local engine_path="$1"
  bash "$SCRIPT_DIR/verify-yolov5m-engine.sh" "$engine_path"
}

verify_hrnet_engine() {
  local engine_path="$1"
  local trtexec="${SKILLS_ROOT}/deps/TensorRT-7.2.3.4/targets/x86_64-linux-gnu/bin/trtexec"
  local trt_lib="${SKILLS_ROOT}/deps/TensorRT-7.2.3.4/targets/x86_64-linux-gnu/lib"
  local cudnn="${SKILLS_ROOT}/deps/cudnn-8.1.0.77/lib"
  local nvrtc="${SKILLS_ROOT}/deps/cuda11.0/usr/local/cuda-11.0/targets/x86_64-linux/lib"

  [[ -f "$trtexec" ]] || { warn "跳过 hrnet trtexec 校验（未找到 TRT）"; return 0; }

  export LD_LIBRARY_PATH="${cudnn}:${nvrtc}:${trt_lib}:/usr/local/cuda-11.1/lib64:${LD_LIBRARY_PATH:-}"
  unset NVIDIA_TF32_OVERRIDE LD_PRELOAD 2>/dev/null || true

  echo "--- trtexec 加载 hrnet.engine ---"
  if "$trtexec" --loadEngine="$engine_path" --iterations=1 --duration=0 2>&1 \
    | tee /tmp/verify_hrnet_engine.log | grep -q "PASSED"; then
    ok "hrnet.engine PASS"
    return 0
  fi
  fail "hrnet.engine FAIL — 见 /tmp/verify_hrnet_engine.log"
  grep -iE 'error|fail|Version tag|compute|PASSED' /tmp/verify_hrnet_engine.log | tail -10 || true
  return 2
}

print_mapping() {
  echo ""
  echo "=== modelid 对照（Algorithm JSON -> AlgModelConf -> engine）==="
  printf "%-8s %-8s %-10s %-28s %s\n" "JSON id" "Conf id" "modeluse" "engine" "用途"
  printf "%-8s %-8s %-10s %-28s %s\n" "-------" "-------" "--------" "----------------------------" "----"
  printf "%-8s %-8s %-10s %-28s %s\n" "4" "1004" "1(检测)" "yolov5m_person.engine" "人体检测"
  printf "%-8s %-8s %-10s %-28s %s\n" "5" "1005" "2(姿态)" "hrnet.engine" "姿态估计(1018等)"
  printf "%-8s %-8s %-10s %-28s %s\n" "6" "1006" "1(检测)" "yolov5m.engine" "COCO通用(1003船只等)"
  printf "%-8s %-8s %-10s %-28s %s\n" "31" "1031" "face" "dface/" "人脸识别(1019,默认关闭)"
  echo ""
  echo "专用 engine（按需手工加入 AlgModelConf）："
  ls -1 "$MODEL_DIR"/yolov5m_*.engine 2>/dev/null | xargs -n1 basename || true
}

main() {
  echo "=== vaio-analysis-service 模型配置 ==="
  echo "MODEL_DIR: $MODEL_DIR"
  echo "ALG_CONF:  $ALG_CONF"
  echo ""

  mkdir -p "$MODEL_DIR" "$CONF_DIR"

  local err=0
  ensure_yolo_engine 1004 || err=1
  ensure_hrnet_engine || err=1
  ensure_yolo_engine 1006 || err=1

  if [[ ! -f "$SERVICE_ROOT/x86_64/label/coco.txt" ]]; then
    fail "缺少 label/coco.txt"
    err=1
  else
    ok "label/coco.txt"
  fi

  write_alg_model_conf

  echo ""
  echo "=== 补齐 Algorithm 配方（upload.suppressEnabled / tracker.labels）==="
  bash "$SERVICE_ROOT/scripts/patch-algorithm-config.sh"

  if [[ "$CHECK_ONLY" -eq 1 ]]; then
    print_mapping
    exit "$err"
  fi

  echo ""
  echo "=== engine 校验 (trtexec) ==="
  verify_yolo_engine "$MODEL_DIR/yolov5m_person.engine" || err=1
  verify_hrnet_engine "$MODEL_DIR/hrnet.engine" || err=1
  verify_yolo_engine "$MODEL_DIR/yolov5m.engine" || err=1

  print_mapping

  if [[ "$err" -ne 0 ]]; then
    echo ""
    if [[ "$DO_BUILD" -eq 0 ]]; then
      warn "若 trtexec 报 incompatible device / compute 7.5，请执行: $0 --build-missing"
    fi
    fail "部分步骤未通过，请根据上方输出修复"
    exit "$err"
  fi

  echo ""
  ok "模型配置完成，可启动: bash scripts/run-core.sh"
}

main "$@"
