import type { InspectionReport } from "./reportPlanMock";

export type ReportPeriod = "month" | "week";

export type ReportTimeFilter = "all" | "7d" | "14d" | "30d" | "month";

export const REPORT_TIME_FILTERS: ReportTimeFilter[] = ["all", "7d", "14d", "30d", "month"];

export type EventTrendRange = 7 | 14 | 30;

export type EventTimeScope = "range" | "day";

export type EventTrendGroupBy = "event_type" | "work" | "region";

export type EventTrendStatusFilter = "all" | "open" | "pending" | "processing" | "resolved";

export type EventTrendKindFilter = "all" | "video" | "sensor";

export type EventTrendRegionFilter = "all" | string;

export type WeeklyWorkFilter = "all" | string;

export type WeeklyRiskFilter = "all" | string;

export type DashboardTrendQuery = {
  trend_days: EventTrendRange;
  trend_group_by: EventTrendGroupBy;
  trend_status?: EventTrendStatusFilter;
  trend_kind?: EventTrendKindFilter;
  trend_region_id?: string;
  trend_date?: string;
};

export const EVENT_TREND_GROUP_OPTIONS: EventTrendGroupBy[] = ["event_type", "work", "region"];

export const EVENT_TREND_STATUS_OPTIONS: EventTrendStatusFilter[] = [
  "all",
  "open",
  "pending",
  "processing",
  "resolved",
];

export const EVENT_TREND_KIND_OPTIONS: EventTrendKindFilter[] = ["all", "video", "sensor"];

export type TrendSeries = {
  id: string;
  label: string;
  color: string;
  values: number[];
};

export const EVENT_CHART_COLORS = [
  "#2563eb",
  "#0891b2",
  "#059669",
  "#d97706",
  "#7c3aed",
  "#94a3b8",
] as const;

export const DC_EVENT_TREND_LABELS = ["05-13", "05-14", "05-15", "05-16", "05-17", "05-18", "05-19"];

export const EVENT_TREND_RANGES: EventTrendRange[] = [7, 14, 30];

export const DC_EVENT_TREND_BY_TYPE: Record<string, number[]> = {
  未佩戴安全帽: [2, 1, 3, 2, 4, 3, 5],
  烟雾疑似: [1, 2, 1, 0, 2, 3, 1],
  区域入侵: [0, 1, 1, 2, 1, 1, 2],
  温度超限: [1, 0, 2, 1, 1, 2, 1],
  噪声超标: [2, 3, 2, 4, 3, 2, 4],
  扬尘超标: [1, 1, 0, 1, 2, 1, 0],
  振动异常: [0, 0, 1, 0, 1, 0, 1],
};

export const DC_EVENT_TREND_BY_REGION: Record<string, number[]> = {
  "A座大堂与公区": [3, 4, 5, 3, 6, 5, 7],
  "地下停车场": [4, 5, 3, 6, 4, 5, 6],
  "B座商业裙楼": [2, 2, 3, 2, 3, 4, 3],
  "园区外围与卸货区": [2, 3, 2, 4, 3, 3, 4],
  电气间周边: [1, 1, 2, 1, 2, 1, 2],
  施工通道: [2, 2, 1, 3, 2, 2, 3],
  材料装卸区: [1, 0, 1, 1, 1, 0, 1],
};

const DEMO_NOW = new Date("2026-05-19T12:00:00");

function parseReportDate(value: string) {
  const normalized = value.length === 10 ? `${value}T00:00:00` : value.replace(" ", "T");
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function filterReportsByDateRange(
  reports: InspectionReport[],
  startDate: string,
  endDate: string,
) {
  const start = parseReportDate(startDate.trim());
  const end = parseReportDate(endDate.trim());
  if (!start || !end) return reports;

  const rangeStart = new Date(start);
  rangeStart.setHours(0, 0, 0, 0);
  const rangeEnd = new Date(end);
  rangeEnd.setHours(23, 59, 59, 999);

  const from = rangeStart <= rangeEnd ? rangeStart : rangeEnd;
  const to = rangeStart <= rangeEnd ? rangeEnd : rangeStart;

  return reports.filter((r) => {
    const date = parseReportDate(r.updatedAt);
    return date != null && date >= from && date <= to;
  });
}

export function reportPeriodLabel(period: ReportPeriod) {
  return period === "month" ? "本月" : "本周";
}

export function reportTimeFilterLabel(filter: ReportTimeFilter) {
  if (filter === "all") return "全部";
  if (filter === "month") return "本月";
  if (filter === "7d") return "近 7 日";
  if (filter === "14d") return "近 14 日";
  return "近 30 日";
}

export function filterReportsByTime(reports: InspectionReport[], filter: ReportTimeFilter) {
  if (filter === "all") return reports;
  if (filter === "month") return filterReportsByPeriod(reports, "month");
  const days = filter === "7d" ? 7 : filter === "14d" ? 14 : 30;
  const start = new Date(DEMO_NOW);
  start.setDate(DEMO_NOW.getDate() - (days - 1));
  start.setHours(0, 0, 0, 0);
  return reports.filter((r) => {
    const date = parseReportDate(r.updatedAt);
    return date != null && date >= start && date <= DEMO_NOW;
  });
}

export function eventTrendRangeLabel(range: EventTrendRange) {
  return `近${range}日`;
}

export function eventTrendGroupLabel(group: EventTrendGroupBy) {
  if (group === "event_type") return "事件类型";
  if (group === "work") return "巡检业务";
  return "区域";
}

export function eventTrendStatusLabel(status: EventTrendStatusFilter) {
  if (status === "open") return "待办";
  if (status === "pending") return "待处理";
  if (status === "processing") return "处理中";
  if (status === "resolved") return "已处置";
  return "全部";
}

export function eventTrendKindLabel(kind: EventTrendKindFilter) {
  if (kind === "video") return "视频";
  if (kind === "sensor") return "传感";
  return "全部";
}

export function formatTrendSeriesLabel(key: string, groupBy: EventTrendGroupBy) {
  if (groupBy === "kind") {
    if (key === "video") return "视频告警";
    if (key === "sensor") return "传感监测";
  }
  return key;
}

export function buildEventTrendLabels(range: EventTrendRange): string[] {
  return Array.from({ length: range }, (_, index) => {
    const date = new Date(DEMO_NOW);
    date.setDate(DEMO_NOW.getDate() - (range - 1 - index));
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${month}-${day}`;
  });
}

/** 与后端返回序列对齐：截断或右侧补零，不做假数据漂移 */
function alignTrendValues(values: number[], bucketCount: number): number[] {
  if (values.length === bucketCount) return values;
  if (values.length > bucketCount) return values.slice(-bucketCount);
  return [...Array(bucketCount - values.length).fill(0), ...values];
}

function sliceTrendRaw(raw: Record<string, number[]>, bucketCount: number) {
  return Object.fromEntries(
    Object.entries(raw).map(([label, values]) => [label, alignTrendValues(values, bucketCount)]),
  );
}

export function filterReportsByPeriod(reports: InspectionReport[], period: ReportPeriod) {
  if (period === "week") {
    const weekStart = new Date(DEMO_NOW);
    weekStart.setDate(DEMO_NOW.getDate() - 6);
    weekStart.setHours(0, 0, 0, 0);
    return reports.filter((r) => {
      const date = parseReportDate(r.updatedAt);
      return date != null && date >= weekStart && date <= DEMO_NOW;
    });
  }
  return reports.filter((r) => {
    const date = parseReportDate(r.updatedAt);
    return (
      date != null &&
      date.getFullYear() === DEMO_NOW.getFullYear() &&
      date.getMonth() === DEMO_NOW.getMonth()
    );
  });
}

/** @deprecated 用户看板不再区分发布状态，请使用 filterReportsByPeriod */
export function filterPublishedReports(reports: InspectionReport[], period: ReportPeriod) {
  return filterReportsByPeriod(reports, period);
}

export function buildTopTrendSeries(
  raw: Record<string, number[]>,
  range: EventTrendRange = 7,
  topN = 4,
  formatLabel?: (key: string) => string,
  axisLabels?: string[],
): { labels: string[]; series: TrendSeries[]; total: number } {
  const labels =
    axisLabels && axisLabels.length === range ? axisLabels : buildEventTrendLabels(range);
  const slicedRaw = sliceTrendRaw(raw, range);
  const bucketLen = labels.length;

  const ranked = Object.entries(slicedRaw)
    .map(([label, values]) => ({
      label,
      values,
      total: values.reduce((sum, n) => sum + n, 0),
    }))
    .sort((a, b) => b.total - a.total);

  const top = ranked.slice(0, topN);
  const rest = ranked.slice(topN);

  const others =
    rest.length > 0
      ? Array.from({ length: bucketLen }, (_, i) => rest.reduce((sum, item) => sum + item.values[i], 0))
      : null;

  const labelOf = (key: string) => (formatLabel ? formatLabel(key) : key);
  const series: TrendSeries[] = top.map((item, index) => ({
    id: item.label,
    label: labelOf(item.label),
    color: EVENT_CHART_COLORS[index] ?? EVENT_CHART_COLORS[EVENT_CHART_COLORS.length - 1],
    values: item.values,
  }));

  if (others && others.some((n) => n > 0)) {
    series.push({
      id: "__others__",
      label: "其他",
      color: EVENT_CHART_COLORS[5],
      values: others,
    });
  }

  const total = series.reduce((sum, s) => sum + s.values.reduce((a, b) => a + b, 0), 0);
  return { labels, series, total };
}

export type BreakdownItem = {
  id: string;
  label: string;
  value: number;
  color: string;
};

export type BucketBreakdownItem = BreakdownItem;

/** 某一时间桶（日/小时）内按当前分布维度的明细 */
export function buildBucketBreakdownAt(
  raw: Record<string, number[]>,
  bucketCount: number,
  index: number,
  topN = 6,
  formatLabel?: (key: string) => string,
): BucketBreakdownItem[] {
  const sliced = sliceTrendRaw(raw, bucketCount);
  const labelOf = (key: string) => (formatLabel ? formatLabel(key) : key);
  return Object.entries(sliced)
    .map(([id, values], colorIndex) => ({
      id,
      label: labelOf(id),
      value: values[index] ?? 0,
      color: EVENT_CHART_COLORS[colorIndex % EVENT_CHART_COLORS.length],
    }))
    .filter((item) => item.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, topN);
}

/** 按日汇总事件总量（与分组维度无关，用于主趋势柱图） */
export function buildDailyTotals(
  raw: Record<string, number[]>,
  bucketCount: number,
  axisLabels?: string[],
): { labels: string[]; values: number[]; total: number } {
  const labels =
    axisLabels && axisLabels.length === bucketCount
      ? axisLabels
      : bucketCount === 24
        ? Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, "0")}:00`)
        : buildEventTrendLabels(bucketCount as EventTrendRange);
  const sliced = sliceTrendRaw(raw, bucketCount);
  const values = Array.from({ length: labels.length }, (_, i) =>
    Object.values(sliced).reduce((sum, arr) => sum + (arr[i] ?? 0), 0),
  );
  return { labels, values, total: values.reduce((a, b) => a + b, 0) };
}

/** 筛选周期内按维度汇总排行（横向条图） */
export function buildCategoryBreakdown(
  raw: Record<string, number[]>,
  bucketCount: number,
  topN = 6,
  formatLabel?: (key: string) => string,
): BreakdownItem[] {
  const sliced = sliceTrendRaw(raw, bucketCount);
  const labelOf = (key: string) => (formatLabel ? formatLabel(key) : key);
  return Object.entries(sliced)
    .map(([id, values], index) => ({
      id,
      label: labelOf(id),
      value: values.reduce((a, b) => a + b, 0),
      color: EVENT_CHART_COLORS[index % EVENT_CHART_COLORS.length],
    }))
    .filter((item) => item.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, topN);
}
