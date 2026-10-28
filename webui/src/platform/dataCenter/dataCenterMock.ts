import {
  DASHBOARD_STATS,
  MOCK_REGIONS,
  MOCK_INSPECTION_WORKS,
  MOCK_SENSOR_RESULTS,
  MOCK_VIDEO_RESULTS,
} from "../mockData";
import type { InspectionScheduleMode } from "../types";
import { INITIAL_INSPECTION_REPORTS } from "./reportPlanMock";
import type { EventDetectionFrame } from "./eventDetection";

export type { EventDetectionBox, EventDetectionFrame } from "./eventDetection";

export type TrendPoint = { label: string; alerts: number; resolved: number; inspections: number };

export type RegionCompliance = {
  regionId: string;
  regionName: string;
  score: number;
  works: number;
  alerts: number;
  trend: "up" | "down" | "flat";
  trendDelta: number;
};

export type WorkRuntimeStatus = {
  workId: string;
  name: string;
  regionName: string;
  scheduleMode: InspectionScheduleMode;
  health: "healthy" | "warning" | "critical" | "idle";
  lastRun: string;
  nextRun: string;
  compliance: number;
  alerts7d: number;
  alertResolutionRate: number;
};

export type DataCenterReport = {
  id: string;
  title: string;
  period: string;
  type: "weekly" | "monthly" | "special";
  status: "draft" | "published" | "archived";
  updatedAt: string;
  summary: string;
  sections: Array<{ title: string; body: string }>;
};

export const DC_WEEKLY_TREND: TrendPoint[] = [
  { label: "周一", alerts: 4, resolved: 3, inspections: 28 },
  { label: "周二", alerts: 6, resolved: 5, inspections: 32 },
  { label: "周三", alerts: 3, resolved: 3, inspections: 30 },
  { label: "周四", alerts: 8, resolved: 6, inspections: 35 },
  { label: "周五", alerts: 5, resolved: 4, inspections: 31 },
  { label: "周六", alerts: 2, resolved: 2, inspections: 18 },
  { label: "周日", alerts: 3, resolved: 2, inspections: 16 },
];

export const DC_REGION_COMPLIANCE: RegionCompliance[] = [
  { regionId: "r1a", regionName: "A座大堂与公区", score: 94, works: 1, alerts: 2, trend: "up", trendDelta: 1.2 },
  { regionId: "r3", regionName: "地下停车场", score: 88, works: 1, alerts: 3, trend: "flat", trendDelta: 0 },
  { regionId: "r4", regionName: "园区外围与卸货区", score: 82, works: 1, alerts: 4, trend: "down", trendDelta: -1.5 },
  { regionId: "r2", regionName: "B座商业裙楼", score: 91, works: 1, alerts: 1, trend: "up", trendDelta: 0.8 },
];

export const DC_WORK_RUNTIME: WorkRuntimeStatus[] = MOCK_INSPECTION_WORKS.map((w, i) => ({
  workId: w.work_id,
  name: w.name,
  regionName: w.region_name,
  scheduleMode: w.schedule_mode,
  health: (["healthy", "warning", "healthy", "idle"] as const)[i % 4],
  lastRun: ["2026-05-19 08:00", "2026-05-19 14:00", "2026-05-19 11:30", "2026-05-15 09:00"][i],
  nextRun: ["2026-05-19 12:00", "2026-05-19 18:00", "持续运行", "手动触发"][i],
  compliance: [94, 87, 91, 72][i],
  alerts7d: [2, 4, 1, 0][i],
  alertResolutionRate: [100, 75, 100, 100][i],
}));

export const DC_REPORTS: DataCenterReport[] = [
  {
    id: "rep-w18",
    title: "2026-W20 安全运行周报",
    period: "2026-05-12 — 2026-05-18",
    type: "weekly",
    status: "published",
    updatedAt: "2026-05-18 16:30",
    summary:
      "本周 4 条在线巡检业务共执行 52 次，综合合规率 91.6%。地库消防通道与外围工牌告警占比较高，已同步物业项目周例会。",
    sections: [
      {
        title: "运行概况",
        body: "周期/定时巡检 3 条、持续监控 1 条。设备在线率 93%，A座公区与商业裙楼表现稳定。",
      },
      {
        title: "告警与处置",
        body: "视频分析 4 起（工牌 1、消防通道 1、入侵 1、垃圾满溢 1），传感异常 2 起。已关闭 3 起，在办 2 起。",
      },
      {
        title: "区域差异",
        body: "园区外围合规指数 82，低于全场均值；主要受卸货噪声与门岗工牌检出影响。",
      },
      {
        title: "建议措施",
        body: "地库高峰增加巡更；屋面摄像头恢复在线；协调商业区装修时段。",
      },
    ],
  },
  {
    id: "rep-w17",
    title: "2026-W19 安全运行周报",
    period: "2026-05-05 — 2026-05-11",
    type: "weekly",
    status: "archived",
    updatedAt: "2026-05-11 17:00",
    summary: "合规率 91.5%，无重大隐患。配电间烟火识别阈值完成一轮标定。",
    sections: [
      { title: "运行概况", body: "巡检 48 次，巡检业务覆盖率 94%。A座公区与地库秩序巡检运行平稳。" },
      { title: "重点事件", body: "本周无未关闭重大告警；温湿度接近上限 1 次，已自动恢复。" },
    ],
  },
  {
    id: "rep-m05",
    title: "2026年5月 月度合规报告",
    period: "2026-05-01 — 2026-05-31",
    type: "monthly",
    status: "draft",
    updatedAt: "2026-05-19 09:00",
    summary: "月度汇总编制中，当前已归集 19 日前的运行与告警数据。",
    sections: [
      { title: "编制进度", body: "视频与传感明细已对齐；外围噪声整改闭环材料待商户签字。" },
      { title: "初步结论", body: "月内合规率预计 88–90%，较 4 月略升；算法误报率下降 0.6 个百分点。" },
    ],
  },
  {
    id: "rep-sp1",
    title: "重大活动前专项排查报告",
    period: "2026-05-15 专项",
    type: "special",
    status: "published",
    updatedAt: "2026-05-15 18:00",
    summary: "配电间人工专项排查完成，烟火与入侵检测链路验证通过。",
    sections: [
      { title: "排查范围", body: "电气间配电柜单点位，绑定规范 1 条、算法 2 个，执行窗口 09:00–11:30。" },
      { title: "结论", body: "未发现开放隐患；传感与视频链路延迟 < 800ms，符合活动保障要求。" },
    ],
  },
];

export const DC_KPI = {
  activeWorks: MOCK_INSPECTION_WORKS.filter((w) => w.schedule_mode !== "manual").length,
  inspectionsToday: 47,
  inspectionsDelta: +12,
  inspectionTrend: [32, 38, 35, 41, 44, 39, 47],
  alertOpen: DASHBOARD_STATS.pendingAlerts,
  alertDelta: -1,
  alertTrend: [4, 5, 3, 6, 4, 2, 3],
  reportPublished: INITIAL_INSPECTION_REPORTS.filter((r) => r.status === "published").length,
  cameraCount: DASHBOARD_STATS.cameras,
  sensorCount: DASHBOARD_STATS.sensors,
  deviceTotal: DASHBOARD_STATS.cameras + DASHBOARD_STATS.sensors,
  deviceOnline: DASHBOARD_STATS.cameras + DASHBOARD_STATS.sensors - 2,
  regions: MOCK_REGIONS.filter((r) => r.id !== "r0").length,
};

export type EventSnapshot = {
  capturedAt: string;
  gradient: string;
  videoUrl?: string;
  imageUrl?: string;
  aiLabel?: string;
  confidence?: number;
  detection?: EventDetectionFrame | null;
};

export type EventRecording = {
  duration: string;
  startAt: string;
  endAt: string;
  gradient: string;
  videoUrl?: string;
  sizeLabel: string;
};

export type EventLiveStream = {
  cameraName: string;
  cameraId: string;
  online: boolean;
  gradient: string;
  videoUrl?: string;
  latencyMs: number;
};

export type EventResolution = {
  outcome: string;
  handler?: string;
  handledAt?: string;
  detail: string;
};

export type DataCenterEvent = {
  id: string;
  type: "video" | "sensor";
  title: string;
  source: string;
  work: string;
  /** 算法/规则检出时间 */
  time: string;
  /** 平台上报时间 */
  reportedAt: string;
  status: "pending" | "processing" | "resolved" | "ignored";
  algorithmName?: string;
  cameraId?: string;
  sensorId?: string;
  value?: number;
  threshold?: string;
  snapshot: EventSnapshot;
  recording: EventRecording | null;
  live: EventLiveStream | null;
  resolution: EventResolution;
  /** 设备已配置 RTSP，直播走 go2rtc WebRTC */
  hasRtsp?: boolean;
};

function shiftReportedAt(detectedAt: string, seconds = 3): string {
  const normalized = detectedAt.length === 16 ? `${detectedAt}:00` : detectedAt;
  const d = new Date(normalized.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return detectedAt;
  d.setSeconds(d.getSeconds() + seconds);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function clipWindow(detectedAt: string, secondsBefore = 8, secondsAfter = 24) {
  const normalized = detectedAt.length === 16 ? `${detectedAt}:00` : detectedAt;
  const end = new Date(normalized.replace(" ", "T"));
  const start = new Date(end);
  start.setSeconds(start.getSeconds() - secondsBefore);
  end.setSeconds(end.getSeconds() + secondsAfter);
  const fmt = (d: Date) => {
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  };
  const durationSec = secondsBefore + secondsAfter;
  const mm = String(Math.floor(durationSec / 60)).padStart(2, "0");
  const ss = String(durationSec % 60).padStart(2, "0");
  return { startAt: fmt(start), endAt: fmt(end), duration: `${mm}:${ss}` };
}

export function buildEventResolution(
  status: DataCenterEvent["status"],
  type: "video" | "sensor",
  title: string,
  eventTime: string,
): EventResolution {
  if (status === "pending") {
    return {
      outcome: "待处理",
      detail:
        type === "video"
          ? `「${title}」告警已推送至安环值班组，等待现场确认与处置。`
          : `「${title}」传感读数异常，等待运维人员复核并确认处置方案。`,
    };
  }
  if (status === "processing") {
    return {
      outcome: "处理中",
      handler: "李敏",
      handledAt: shiftReportedAt(eventTime, 1800),
      detail:
        type === "video"
          ? "已通知现场班组到场核查，正在复核 AI 告警有效性并调取同期录像。"
          : "已联系现场值班人员排查设备与工况，持续跟踪读数变化。",
    };
  }
  return {
    outcome: "已关闭",
    handler: type === "video" ? "张工" : "王审计",
    handledAt: shiftReportedAt(eventTime, 5400),
    detail:
      type === "video"
        ? "经现场核实确认违规情况属实，已督促整改并完成安全教育，告警闭环归档。"
        : "异常读数已恢复至正常区间，完成原因说明与记录归档，无需进一步处置。",
  };
}

function buildVideoEvent(v: (typeof MOCK_VIDEO_RESULTS)[number]): DataCenterEvent {
  const clip = clipWindow(v.time);
  return {
    id: v.id,
    type: "video",
    title: v.eventType,
    source: v.cameraName,
    work: v.taskName,
    time: v.time,
    reportedAt: shiftReportedAt(v.time, 4),
    status: v.status,
    algorithmName: v.algorithmName,
    cameraId: v.cameraId,
    snapshot: {
      capturedAt: v.time,
      gradient: v.snapshot,
      aiLabel: v.eventType,
      confidence: 0.94,
    },
    recording: {
      ...clip,
      gradient: v.snapshot,
      sizeLabel: "4.8 MB",
    },
    live: {
      cameraName: v.cameraName,
      cameraId: v.cameraId,
      online: v.status !== "resolved",
      gradient: "linear-gradient(145deg, #0f172a, #1e3a5f)",
      latencyMs: 680,
    },
    resolution: buildEventResolution(v.status, "video", v.eventType, v.time),
  };
}

function buildSensorEvent(s: (typeof MOCK_SENSOR_RESULTS)[number]): DataCenterEvent {
  const gradient = "linear-gradient(135deg, #ea580c22, #f9731644)";
  return {
    id: s.id,
    type: "sensor",
    title: s.anomalyType,
    source: s.sensorName,
    work: s.ruleName,
    time: s.time.length === 16 ? `${s.time}:00` : s.time,
    reportedAt: shiftReportedAt(s.time.length === 16 ? `${s.time}:00` : s.time, 6),
    status: s.status,
    sensorId: s.sensorId,
    value: s.value,
    threshold: s.threshold,
    snapshot: {
      capturedAt: s.time.length === 16 ? `${s.time}:00` : s.time,
      gradient,
      aiLabel: `${s.anomalyType} · ${s.value}`,
      confidence: 0.91,
    },
    recording: null,
    live: {
      cameraName: `${s.sensorName} 关联监控`,
      cameraId: "cam-linked",
      online: s.status !== "resolved",
      gradient: "linear-gradient(145deg, #1e293b, #334155)",
      latencyMs: 920,
    },
    resolution: buildEventResolution(
      s.status,
      "sensor",
      s.anomalyType,
      s.time.length === 16 ? `${s.time}:00` : s.time,
    ),
  };
}

export const DC_RECENT_EVENTS: DataCenterEvent[] = [
  ...MOCK_VIDEO_RESULTS.map(buildVideoEvent),
  ...MOCK_SENSOR_RESULTS.map(buildSensorEvent),
].sort((a, b) => b.time.localeCompare(a.time));
