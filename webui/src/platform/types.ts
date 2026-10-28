export type Region = {
  id: string;
  code: string;
  name: string;
  parentId: string | null;
  parentName?: string;
  description: string;
  cameraCount: number;
  childCount?: number;
};

export type CameraDevice = {
  id: string;
  name: string;
  description: string;
  regionId: string;
  regionName: string;
  streamUrl?: string;
  platformName?: string;
  platformAddress?: string;
  thumbnail: string;
  online: boolean;
  simulateVideoUrl?: string;
};

export type SensorDevice = {
  id: string;
  name: string;
  description: string;
  regionId: string;
  regionName: string;
  dataType: string;
  unit: string;
  platformName?: string;
  platformAddress?: string;
  online: boolean;
};

export type SensorReading = {
  time: string;
  value: number;
  status: "normal" | "warning" | "critical";
};

export type AlgorithmItem = {
  id: string;
  name: string;
  version: string;
  description: string;
  uploadedAt: string;
  health: "healthy" | "degraded" | "unknown";
};

export type KnowledgeRule = {
  id: string;
  name: string;
  scenario: string;
  requirements: string;
  sourceFile: string;
  recommendedAlgorithms: string[];
  recommendedRegions: string[];
  status: "draft" | "published";
  /** 关联文档库主键 */
  docId?: string;
  /** 适用区域说明（智能推荐） */
  regionReasoning?: string;
  /** 推荐算法说明（智能推荐） */
  algorithmReasoning?: string;
  extractedAt?: string;
};

/** 巡检业务时间维度：周期 / 定时 / 持续 / 手动 */
export type InspectionScheduleMode = "periodic" | "scheduled" | "continuous" | "manual";

/** AI 生成时的检索命中摘要（仅前端会话，不入库） */
export type AiGenerationTraceRuleHit = {
  index: number;
  rule_id: string;
  name: string;
  summary: string;
  similarity: number;
  recall_rate?: number;
  path?: "vector";
};

export type AiGenerationTrace = {
  rule_path?: "vector" | "none";
  /** 向量路未命中已发布规范时的首行提示 */
  rules_miss_message?: string;
  /** 命中阈值后的规范（带相似度） */
  rules: AiGenerationTraceRuleHit[];
  /** 未命中时相似度最高的近义规范（带相似度，仅展示） */
  rule_near_misses?: AiGenerationTraceRuleHit[];
  algorithms: string[];
  regions: string[];
  devices: string[];
};

export type InspectionWorkEntity = {
  work_id: string;
  name: string;
  /** 主区域（region_ids 首项） */
  region_id: string;
  region_name: string;
  /** 业务作用区域（可手动多选；未指定时由 equipment_set 推导） */
  region_ids?: string[];
  work_status?: "online" | "offline";
  desc: string;
  rule_set: Array<{ rule_id: string; name: string; level?: string }>;
  algorithm_set: Array<{ algorithm_id: string; name: string; health?: string }>;
  equipment_set: Array<{ equipment_id: string; name: string; role?: string }>;
  /** 设备 × 算法的运行参数；equipment_id → algorithm_id → 参数键值 */
  equipment_algo_params?: Record<string, Record<string, Record<string, string | number | boolean>>>;
  source: "ai" | "manual";
  /** AI 生成时附带的检索命中信息，手动新建无此字段 */
  ai_generation_trace?: AiGenerationTrace;
  schedule_mode: InspectionScheduleMode;
  /** 周期检查：如 每4小时、每日、每周 */
  schedule_interval?: string;
  /** 定时检查：如 08:00,14:00 或 cron 表达式 */
  schedule_times?: string;
  updated_at: string;
};

export type VideoAnalysisResult = {
  id: string;
  eventType: string;
  algorithmName: string;
  cameraName: string;
  cameraId: string;
  taskName: string;
  taskId: string;
  time: string;
  status: "pending" | "processing" | "resolved" | "ignored";
  snapshot: string;
};

export type SensorAnomalyResult = {
  id: string;
  sensorName: string;
  sensorId: string;
  time: string;
  anomalyType: string;
  ruleName: string;
  value: number;
  threshold: string;
  status: "pending" | "processing" | "resolved" | "ignored";
};

export type ReportSection = {
  id: string;
  title: string;
  content: string;
  order: number;
};

export type OperationReport = {
  id: string;
  title: string;
  period: string;
  status: "draft" | "published";
  sections: ReportSection[];
  updatedAt: string;
};
