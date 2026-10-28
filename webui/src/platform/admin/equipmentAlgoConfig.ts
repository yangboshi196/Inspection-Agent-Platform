import type { InspectionWorkEntity } from "../types";
import {
  readDetectionRoiFromParams,
  serializeDetectionRoi,
  type DetectionRoiBundle,
} from "./detectionRoi";

export type AlgoParamField = {
  key: string;
  label: string;
  type: "number" | "boolean" | "select" | "text";
  unit?: string;
  hint?: string;
  min?: number;
  max?: number;
  step?: number;
  options?: Array<{ value: string; label: string }>;
  defaultValue: string | number | boolean;
};

export type EquipmentAlgoParams = Record<string, string | number | boolean>;

const COMMON_VIDEO_FIELDS: AlgoParamField[] = [
  {
    key: "confidence",
    label: "置信度阈值",
    type: "number",
    min: 0.5,
    max: 0.99,
    step: 0.01,
    defaultValue: 0.85,
  },
  {
    key: "frame_interval",
    label: "抽帧间隔",
    type: "number",
    unit: "秒",
    min: 1,
    max: 60,
    step: 1,
    defaultValue: 5,
  },
  {
    key: "alert_cooldown",
    label: "告警冷却",
    type: "number",
    unit: "秒",
    min: 10,
    max: 600,
    step: 10,
    defaultValue: 60,
  },
];

const SCHEMA_BY_ALGO: Record<string, AlgoParamField[]> = {
  "algo-1": [
    ...COMMON_VIDEO_FIELDS,
    {
      key: "min_head_size",
      label: "最小人头像素",
      type: "number",
      min: 16,
      max: 128,
      step: 4,
      defaultValue: 32,
      hint: "过小目标将被忽略",
    },
    {
      key: "require_badge",
      label: "必须佩戴工牌",
      type: "boolean",
      defaultValue: true,
    },
  ],
  "algo-5": [...COMMON_VIDEO_FIELDS],
  "algo-6": [...COMMON_VIDEO_FIELDS],
  "algo-7": [
    {
      key: "delta_celsius",
      label: "温升阈值",
      type: "number",
      unit: "℃",
      min: 1,
      max: 20,
      step: 0.5,
      defaultValue: 5,
    },
  ],
  "algo-8": [...COMMON_VIDEO_FIELDS],
  "algo-2": [
    ...COMMON_VIDEO_FIELDS,
    {
      key: "sensitivity",
      label: "灵敏度",
      type: "select",
      options: [
        { value: "low", label: "低" },
        { value: "medium", label: "中" },
        { value: "high", label: "高" },
      ],
      defaultValue: "medium",
    },
    {
      key: "roi_only",
      label: "仅检测 ROI 区域",
      type: "boolean",
      defaultValue: false,
    },
  ],
  "algo-3": [
    ...COMMON_VIDEO_FIELDS,
    {
      key: "dwell_seconds",
      label: "停留触发时长",
      type: "number",
      unit: "秒",
      min: 1,
      max: 120,
      step: 1,
      defaultValue: 3,
    },
    {
      key: "track_direction",
      label: "方向过滤",
      type: "select",
      options: [
        { value: "any", label: "任意方向" },
        { value: "in", label: "仅进入" },
        { value: "out", label: "仅离开" },
      ],
      defaultValue: "in",
    },
  ],
  "algo-4": [
    {
      key: "threshold",
      label: "告警阈值",
      type: "number",
      min: 0,
      max: 120,
      step: 0.5,
      defaultValue: 70,
      unit: "dB(A)",
    },
    {
      key: "window_seconds",
      label: "统计窗口",
      type: "number",
      unit: "秒",
      min: 30,
      max: 900,
      step: 30,
      defaultValue: 300,
    },
    {
      key: "baseline_auto",
      label: "自动基线校准",
      type: "boolean",
      defaultValue: true,
    },
  ],
};

const VAIO_SENSITIVITY_BY_LEVEL: Record<string, number> = {
  low: 30,
  medium: 50,
  high: 70,
};

const VAIO_THRESHOLD_KEY = "detection/person/threshold";

function clampNumber(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

/** UI 抽帧间隔（每 N 秒抽 1 帧）→ vaio `config.fps`（每秒抽帧频率）。 */
export function frameIntervalToVaioFps(frameIntervalSec: number): number {
  const interval = clampNumber(frameIntervalSec, 1, 3600);
  return Number((1 / interval).toFixed(4));
}

/** UI 置信度阈值（0–1）→ vaio `detection/person/threshold`。 */
export function confidenceToVaioThreshold(confidence: number): number {
  return Number(clampNumber(confidence, 0, 1).toFixed(4));
}

/** 将 UI 基本参数映射为 vaio 任务 config 中的运行时字段。 */
export function vaioRuntimeConfigFromParams(
  params: EquipmentAlgoParams,
): Record<string, number> {
  const frameInterval = Number(params.frame_interval ?? 5);
  const confidence = Number(params.confidence ?? 0.85);
  const holddown = Number(params.alert_cooldown ?? 60);

  const runtime: Record<string, number> = {
    fps: frameIntervalToVaioFps(frameInterval),
    holddowntime: Math.round(clampNumber(holddown, 1, 86400)),
    suppressEnabled: 1,
    [VAIO_THRESHOLD_KEY]: confidenceToVaioThreshold(confidence),
  };

  const rawSens = params.sensitivity;
  if (typeof rawSens === "string" && rawSens in VAIO_SENSITIVITY_BY_LEVEL) {
    runtime.sensitivity = VAIO_SENSITIVITY_BY_LEVEL[rawSens];
  } else if (typeof rawSens === "number") {
    runtime.sensitivity = Math.round(clampNumber(rawSens, 0, 100));
  } else {
    runtime.sensitivity = Math.round(confidenceToVaioThreshold(confidence) * 100);
  }

  return runtime;
}

/** 合并 ROI、基本参数，生成可直接用于 vaio `algorithms[].config` 的入参。 */
export function applyVaioAlgorithmConfig(
  params: EquipmentAlgoParams,
  algorithmId: string,
): EquipmentAlgoParams {
  const withRoi = {
    ...params,
    ...serializeDetectionRoi(readDetectionRoiFromParams(params, algorithmId)),
  };
  if (!isVideoAlgo(algorithmId)) {
    return withRoi;
  }

  const runtime = vaioRuntimeConfigFromParams(withRoi);
  let defence: unknown[] = [];
  try {
    const parsed = JSON.parse(String(withRoi.defence ?? "[]"));
    if (Array.isArray(parsed)) defence = parsed;
  } catch {
    defence = [];
  }

  const vaioConfig = { ...runtime, defence };

  return {
    ...withRoi,
    fps: runtime.fps,
    holddowntime: runtime.holddowntime,
    suppressEnabled: runtime.suppressEnabled,
    sensitivity: runtime.sensitivity,
    [VAIO_THRESHOLD_KEY]: runtime[VAIO_THRESHOLD_KEY],
    vaio_config: JSON.stringify(vaioConfig),
  };
}

export function algoParamFields(algorithmId: string): AlgoParamField[] {
  return SCHEMA_BY_ALGO[algorithmId] ?? COMMON_VIDEO_FIELDS;
}

export function defaultParamsForAlgo(algorithmId: string): EquipmentAlgoParams {
  const fields = algoParamFields(algorithmId);
  return Object.fromEntries(fields.map((f) => [f.key, f.defaultValue]));
}

export function getEquipmentAlgoParams(
  work: InspectionWorkEntity,
  equipmentId: string,
  algorithmId: string,
): EquipmentAlgoParams {
  const stored = work.equipment_algo_params?.[equipmentId]?.[algorithmId];
  const base = { ...defaultParamsForAlgo(algorithmId), ...(stored ?? {}) };
  return applyVaioAlgorithmConfig(base, algorithmId);
}

export function applyDetectionRoiToParams(
  params: EquipmentAlgoParams,
  roi: DetectionRoiBundle,
  algorithmId: string,
): EquipmentAlgoParams {
  return applyVaioAlgorithmConfig({ ...params, ...serializeDetectionRoi(roi) }, algorithmId);
}

export function roiShapeCount(params: EquipmentAlgoParams, algorithmId: string): number {
  const roi = readDetectionRoiFromParams(params, algorithmId);
  return roi.detection.length + roi.inverse.length;
}

export function isVideoAlgo(algorithmId: string): boolean {
  return algorithmId !== "algo-4";
}

export function mergeEquipmentAlgoParams(
  work: InspectionWorkEntity,
  equipmentId: string,
  algorithmId: string,
  params: EquipmentAlgoParams,
): InspectionWorkEntity["equipment_algo_params"] {
  return {
    ...work.equipment_algo_params,
    [equipmentId]: {
      ...(work.equipment_algo_params?.[equipmentId] ?? {}),
      [algorithmId]: params,
    },
  };
}

export function isAlgoEnabled(params: EquipmentAlgoParams): boolean {
  return params.enabled !== false;
}

export function paramPreviewLine(algorithmId: string, params: EquipmentAlgoParams): string {
  const fields = algoParamFields(algorithmId);
  const pick =
    fields.find((f) => f.key === "confidence") ??
    fields.find((f) => f.key === "threshold") ??
    fields.find((f) => f.type === "number") ??
    fields[0];
  if (!pick) return "";
  const val = params[pick.key] ?? pick.defaultValue;
  let line = "";
  if (pick.type === "boolean") line = val ? pick.label : `${pick.label}：关`;
  else if (pick.type === "select") {
    const opt = pick.options?.find((o) => o.value === String(val));
    line = `${pick.label} ${opt?.label ?? val}`;
  } else {
    line = `${pick.label} ${val}${pick.unit ?? ""}`;
  }
  if (isVideoAlgo(algorithmId)) {
    const count = roiShapeCount(params, algorithmId);
    if (count > 0) line += ` · ${count} 个检测区域`;
  }
  return line;
}

export type EquipmentAlgoSummary = {
  algorithmId: string;
  algorithmName: string;
  enabled: boolean;
  preview: string;
  configured: boolean;
};

export function summarizeEquipmentAlgoConfig(
  work: InspectionWorkEntity,
  equipmentId: string,
): EquipmentAlgoSummary[] {
  return work.algorithm_set.map((algo) => {
    const params = getEquipmentAlgoParams(work, equipmentId, algo.algorithm_id);
    const configured = Boolean(work.equipment_algo_params?.[equipmentId]?.[algo.algorithm_id]);
    return {
      algorithmId: algo.algorithm_id,
      algorithmName: algo.name,
      enabled: isAlgoEnabled(params),
      preview: paramPreviewLine(algo.algorithm_id, params),
      configured,
    };
  });
}
