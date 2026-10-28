import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "../components/Badge";
import { DeltaText } from "./components/StatusPill";
import { DailyEventBarChart } from "./components/DailyEventBarChart";
import { DayEventTimeline } from "./components/DayEventTimeline";
import { EventCategoryBreakdown } from "./components/EventCategoryBreakdown";
import {
  buildBucketBreakdownAt,
  buildCategoryBreakdown,
  buildDailyTotals,
  EVENT_TREND_GROUP_OPTIONS,
  EVENT_TREND_KIND_OPTIONS,
  EVENT_TREND_RANGES,
  EVENT_TREND_STATUS_OPTIONS,
  eventTrendGroupLabel,
  eventTrendKindLabel,
  eventTrendRangeLabel,
  eventTrendStatusLabel,
  filterReportsByPeriod,
  reportPeriodLabel,
  type EventTrendGroupBy,
  type EventTrendKindFilter,
  type EventTrendRange,
  type EventTimeScope,
  type EventTrendRegionFilter,
  type EventTrendStatusFilter,
  type ReportPeriod,
  type WeeklyRiskFilter,
  type WeeklyWorkFilter,
} from "./dashboardTrend";
import { frequencyLabel } from "./reportPlanMock";
import { useReportData } from "./ReportDataContext";
import { loadDashboardStats, type DashboardStatsResponse } from "./inspectionEventApi";
import { loadInspectionWorksCatalog, type InspectionWorkEntity } from "./reportApi";
import { loadRegions, type RegionRow } from "../regionApi";

const TREND_DEBOUNCE_MS = 320;

export function DataCenterDashboardPage() {
  const { reports } = useReportData();
  const [loading, setLoading] = useState(true);
  const [chartLoading, setChartLoading] = useState(false);
  const [stats, setStats] = useState<DashboardStatsResponse | null>(null);
  const [regions, setRegions] = useState<RegionRow[]>([]);
  const [hint, setHint] = useState("");
  const [reportPeriod, setReportPeriod] = useState<ReportPeriod>("month");
  const [eventTrendRange, setEventTrendRange] = useState<EventTrendRange>(7);
  const [timeScope, setTimeScope] = useState<EventTimeScope>("range");
  const [selectedDate, setSelectedDate] = useState("");
  const [eventTrendGroup, setEventTrendGroup] = useState<EventTrendGroupBy>("event_type");
  const [eventTrendStatus, setEventTrendStatus] = useState<EventTrendStatusFilter>("all");
  const [eventTrendKind, setEventTrendKind] = useState<EventTrendKindFilter>("all");
  const [eventTrendRegion, setEventTrendRegion] = useState<EventTrendRegionFilter>("all");
  const [weeklyWork, setWeeklyWork] = useState<WeeklyWorkFilter>("all");
  const [weeklyRisk, setWeeklyRisk] = useState<WeeklyRiskFilter>("all");
  const [worksCatalog, setWorksCatalog] = useState<InspectionWorkEntity[]>([]);

  const trendQuery = useMemo(
    () => ({
      trend_days: eventTrendRange,
      trend_group_by: eventTrendGroup,
      trend_status: eventTrendStatus,
      trend_kind: eventTrendKind,
      trend_region_id: eventTrendRegion === "all" ? undefined : eventTrendRegion,
      trend_date: timeScope === "day" && selectedDate ? selectedDate : undefined,
      weekly_work_id: weeklyWork === "all" ? undefined : weeklyWork,
      weekly_risk_type: weeklyRisk === "all" ? undefined : weeklyRisk,
    }),
    [
      eventTrendRange,
      eventTrendGroup,
      eventTrendStatus,
      eventTrendKind,
      eventTrendRegion,
      timeScope,
      selectedDate,
      weeklyWork,
      weeklyRisk,
    ],
  );

  const hasLoadedRef = useRef(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [regs, works] = await Promise.all([
          loadRegions(),
          loadInspectionWorksCatalog().catch(() => [] as InspectionWorkEntity[]),
        ]);
        if (!cancelled) {
          setRegions(regs.filter((r) => r.id !== "r0"));
          setWorksCatalog(works);
        }
      } catch {
        /* 区域/业务列表可选 */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      if (hasLoadedRef.current) setChartLoading(true);
      else setLoading(true);
      void (async () => {
        try {
          const data = await loadDashboardStats(trendQuery);
          if (!cancelled) {
            setStats(data);
            setHint("");
            hasLoadedRef.current = true;
          }
        } catch (e) {
          if (!cancelled) setHint(String(e));
        } finally {
          if (!cancelled) {
            setLoading(false);
            setChartLoading(false);
          }
        }
      })();
    }, TREND_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [trendQuery]);

  const kpi = stats?.kpi;
  const weeklyTrend = stats?.weekly_trend ?? [];
  const riskTypeOptions = stats?.risk_type_options ?? [];
  const weeklyTotals = useMemo(
    () =>
      weeklyTrend.reduce(
        (acc, d) => ({
          inspections: acc.inspections + d.inspections,
          alerts: acc.alerts + d.alerts,
          resolved: acc.resolved + d.resolved,
        }),
        { inspections: 0, alerts: 0, resolved: 0 },
      ),
    [weeklyTrend],
  );

  const reportsInPeriod = useMemo(
    () => filterReportsByPeriod(reports, reportPeriod),
    [reports, reportPeriod],
  );
  const reportTotal = reports.length;
  const pendingEvents = kpi?.pending_events ?? 0;

  const trendRaw = stats?.event_trend ?? {};
  const trendLabels = stats?.trend_labels;

  const isHourly = stats?.trend_meta?.granularity === "hour";
  const chartBucketCount = isHourly ? 24 : eventTrendRange;

  const dailyChart = useMemo(
    () => buildDailyTotals(trendRaw, chartBucketCount, trendLabels),
    [trendRaw, chartBucketCount, trendLabels],
  );

  const breakdown = useMemo(
    () => buildCategoryBreakdown(trendRaw, chartBucketCount, 6),
    [trendRaw, chartBucketCount],
  );

  const bucketBreakdowns = useMemo(
    () =>
      dailyChart.labels.map((_, index) =>
        buildBucketBreakdownAt(trendRaw, chartBucketCount, index, 6),
      ),
    [trendRaw, chartBucketCount, dailyChart.labels],
  );

  const availableDates = stats?.available_dates ?? [];
  const dayEvents = stats?.day_events ?? [];

  useEffect(() => {
    if (!stats) return;
    const anchor = stats.trend_meta?.anchor_date;
    if (timeScope === "day" && !selectedDate && anchor) {
      setSelectedDate(anchor);
    }
  }, [stats, timeScope, selectedDate]);

  const timeSelectValue = timeScope === "day" ? "day" : String(eventTrendRange);

  const weeklySummaryText = useMemo(() => {
    const start = stats?.weekly_meta?.week_start;
    const end = stats?.weekly_meta?.week_end;
    const rangeHint = start && end ? `${start.slice(5)}—${end.slice(5)}` : "";
    const parts = [rangeHint];
    if (weeklyWork !== "all") {
      const name = worksCatalog.find((w) => w.work_id === weeklyWork)?.name ?? weeklyWork;
      parts.push(name);
    }
    if (weeklyRisk !== "all") parts.push(weeklyRisk);
    return parts.join(" · ");
  }, [stats?.weekly_meta?.week_start, stats?.weekly_meta?.week_end, weeklyWork, weeklyRisk, worksCatalog]);

  const summaryText = useMemo(() => {
    if (isHourly && selectedDate) {
      return (
        <>
          <strong>{selectedDate}</strong> 共 <strong>{dailyChart.total}</strong> 起（按小时）
        </>
      );
    }
    return (
      <>
        {eventTrendRangeLabel(eventTrendRange)}共 <strong>{dailyChart.total}</strong> 起
      </>
    );
  }, [isHourly, selectedDate, dailyChart.total, eventTrendRange]);

  return (
    <div className="pf-dc-dashboard">
      {hint ? <div className="pf-usr-status">{hint}</div> : null}
      {loading ? <div className="pf-usr-status">加载看板数据…</div> : null}

      <section className="pf-dc-kpi-grid" aria-label="巡检概览">
        <article className="pf-dc-kpi-card pf-dc-kpi-card-blue">
          <div className="pf-dc-kpi-body">
            <strong className="pf-dc-kpi-value">{kpi?.inspections_today ?? "—"}</strong>
            <h3>今日事件</h3>
            <DeltaText value={kpi?.inspections_delta ?? 0} suffix=" 起" />
            <p className="pf-dc-kpi-foot">7 日 {kpi?.alerts_week ?? 0} 起</p>
          </div>
        </article>
        <article className="pf-dc-kpi-card pf-dc-kpi-card-purple">
          <div className="pf-dc-kpi-body">
            <strong className="pf-dc-kpi-value">{reportsInPeriod.length}</strong>
            <h3>巡检报告</h3>
            <p className="pf-dc-kpi-foot">
              <span className="pf-dc-kpi-period-switch" role="tablist" aria-label="报告统计周期">
                {(["month", "week"] as const).map((period) => (
                  <button
                    key={period}
                    type="button"
                    role="tab"
                    aria-selected={reportPeriod === period}
                    className={`pf-dc-kpi-period-link${reportPeriod === period ? " is-active" : ""}`}
                    onClick={() => setReportPeriod(period)}
                  >
                    {reportPeriodLabel(period)}
                  </button>
                ))}
              </span>
              <span className="pf-dc-kpi-foot-sep">·</span>
              共 {reportTotal} 份
            </p>
          </div>
        </article>
        <article className="pf-dc-kpi-card pf-dc-kpi-card-orange">
          <div className="pf-dc-kpi-body">
            <strong className="pf-dc-kpi-value">{pendingEvents}</strong>
            <h3>待处理事件</h3>
            <DeltaText value={kpi?.alert_delta ?? 0} suffix=" 起" />
            <p className="pf-dc-kpi-foot">
              本周 {kpi?.alerts_week ?? 0} · 已处置 {kpi?.resolved_week ?? 0}
            </p>
          </div>
        </article>
        <article className="pf-dc-kpi-card pf-dc-kpi-card-slate">
          <div className="pf-dc-kpi-body">
            <strong className="pf-dc-kpi-value">{kpi?.device_total ?? "—"}</strong>
            <h3>设备数量</h3>
            <p className="pf-dc-kpi-device-split">
              <span>监控数量 {kpi?.camera_count ?? 0}</span>
              <span>传感数量 {kpi?.sensor_count ?? 0}</span>
            </p>
          </div>
        </article>
      </section>

      <section className="pf-dc-panel pf-dc-panel-events pf-dc-panel-chart pf-dc-dashboard-chart">
        <div className="pf-dc-panel-head pf-dc-panel-head-chart">
          <div className="pf-dc-chart-head-row">
            <div className="pf-dc-chart-title-block">
              <h2>
                巡检事件统计
                <span className="pf-dc-chart-title-meta">{summaryText}</span>
              </h2>
            </div>
            {chartLoading ? <span className="pf-dc-chart-loading-text">更新中…</span> : null}
          </div>

          <div className="pf-dc-chart-toolbar pf-dc-filter-bar" aria-label="筛选条件">
            <label className="pf-dc-toolbar-field pf-dc-toolbar-field-time">
              <span>时间</span>
              <div className="pf-dc-toolbar-time-row">
                <select
                  value={timeSelectValue}
                  onChange={(e) => {
                    const v = e.target.value;
                    if (v === "day") {
                      setTimeScope("day");
                      setSelectedDate(
                        (cur) =>
                          cur ||
                          stats?.trend_meta?.anchor_date ||
                          availableDates[0] ||
                          "",
                      );
                    } else {
                      setTimeScope("range");
                      setEventTrendRange(Number(v) as EventTrendRange);
                    }
                  }}
                >
                  {EVENT_TREND_RANGES.map((range) => (
                    <option key={range} value={range}>
                      {eventTrendRangeLabel(range)}
                    </option>
                  ))}
                  <option value="day">指定日期</option>
                </select>
                {timeScope === "day" ? (
                  <input
                    type="date"
                    className="pf-dc-toolbar-date"
                    value={selectedDate}
                    min={availableDates[availableDates.length - 1]}
                    max={availableDates[0] ?? stats?.trend_meta?.anchor_date}
                    onChange={(e) => setSelectedDate(e.target.value)}
                  />
                ) : null}
              </div>
            </label>
            <label className="pf-dc-toolbar-field">
              <span>状态</span>
              <select
                value={eventTrendStatus}
                onChange={(e) => setEventTrendStatus(e.target.value as EventTrendStatusFilter)}
              >
                {EVENT_TREND_STATUS_OPTIONS.map((status) => (
                  <option key={status} value={status}>
                    {eventTrendStatusLabel(status)}
                  </option>
                ))}
              </select>
            </label>
            <label className="pf-dc-toolbar-field">
              <span>来源</span>
              <select
                value={eventTrendKind}
                onChange={(e) => setEventTrendKind(e.target.value as EventTrendKindFilter)}
              >
                {EVENT_TREND_KIND_OPTIONS.map((kind) => (
                  <option key={kind} value={kind}>
                    {eventTrendKindLabel(kind)}
                  </option>
                ))}
              </select>
            </label>
            <label className="pf-dc-toolbar-field">
              <span>区域</span>
              <select
                value={eventTrendRegion}
                onChange={(e) => setEventTrendRegion(e.target.value as EventTrendRegionFilter)}
              >
                <option value="all">全部</option>
                {regions.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="pf-dc-toolbar-field">
              <span>分布</span>
              <select
                value={eventTrendGroup}
                onChange={(e) => setEventTrendGroup(e.target.value as EventTrendGroupBy)}
              >
                {EVENT_TREND_GROUP_OPTIONS.map((group) => (
                  <option key={group} value={group}>
                    {eventTrendGroupLabel(group)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className={`pf-dc-chart-body${chartLoading ? " is-loading" : ""}`}>
          {dailyChart.total > 0 ? (
            <>
              <DailyEventBarChart
                labels={dailyChart.labels}
                values={dailyChart.values}
                dense={isHourly}
                bucketBreakdowns={bucketBreakdowns}
                groupTitle={eventTrendGroupLabel(eventTrendGroup)}
                slotLabel={isHourly ? "时段" : "日期"}
                isHourly={isHourly}
                dayEvents={isHourly ? dayEvents : undefined}
              />
              <EventCategoryBreakdown
                title={`${eventTrendGroupLabel(eventTrendGroup)}分布`}
                items={breakdown}
              />
              {isHourly && selectedDate ? (
                <DayEventTimeline date={selectedDate} events={dayEvents} />
              ) : null}
            </>
          ) : isHourly && selectedDate ? (
            <DayEventTimeline date={selectedDate} events={dayEvents} />
          ) : (
            <div className="pf-dc-chart-empty pf-dc-chart-empty-rich">
              <p>暂无事件</p>
            </div>
          )}
        </div>
      </section>

      <div className="pf-dc-dashboard-body">
        <section className="pf-dc-panel pf-dc-panel-table">
          <div className="pf-dc-panel-head">
            <h2>最新巡检报告</h2>
            <Link to="/user/reports" className="pf-btn pf-btn-sm">
              全部报告
            </Link>
          </div>
          <div className="pf-dc-table-wrap">
            <table className="pf-dc-table pf-dc-table-dense">
              <thead>
                <tr>
                  <th>类型</th>
                  <th>标题</th>
                  <th>周期</th>
                  <th>更新</th>
                </tr>
              </thead>
              <tbody>
                {reports.slice(0, 5).map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Badge tone="info">{frequencyLabel(r.frequency)}</Badge>
                    </td>
                    <td className="pf-dc-cell-strong">{r.title}</td>
                    <td className="pf-dc-cell-muted">{r.period}</td>
                    <td className="pf-dc-cell-muted">{r.updatedAt.slice(5, 16)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="pf-dc-panel pf-dc-panel-table pf-dc-panel-weekly">
          <div className="pf-dc-panel-head pf-dc-panel-head-weekly">
            <h2>
              本周巡检执行
              {weeklySummaryText ? (
                <span className="pf-dc-panel-sub pf-dc-panel-sub-inline">{weeklySummaryText}</span>
              ) : null}
            </h2>
            <div className="pf-dc-week-summary">
              <span>
                巡检 <strong>{weeklyTotals.inspections}</strong>
              </span>
              <span>
                告警 <strong>{weeklyTotals.alerts}</strong>
              </span>
            </div>
          </div>
          <div className="pf-dc-chart-toolbar pf-dc-filter-bar" aria-label="本周巡检执行筛选">
            <label className="pf-dc-toolbar-field">
              <span>业务</span>
              <select
                value={weeklyWork}
                onChange={(e) => setWeeklyWork(e.target.value as WeeklyWorkFilter)}
              >
                <option value="all">全部</option>
                {worksCatalog.map((w) => (
                  <option key={w.work_id} value={w.work_id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="pf-dc-toolbar-field">
              <span>风险类型</span>
              <select
                value={weeklyRisk}
                onChange={(e) => setWeeklyRisk(e.target.value as WeeklyRiskFilter)}
              >
                <option value="all">全部</option>
                {riskTypeOptions.map((title) => (
                  <option key={title} value={title}>
                    {title}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="pf-dc-table-wrap">
            <table className="pf-dc-table pf-dc-table-dense">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>巡检</th>
                  <th>告警</th>
                  <th>已处置</th>
                </tr>
              </thead>
              <tbody>
                {weeklyTrend.map((d) => (
                  <tr key={d.date}>
                    <td className="pf-dc-cell-strong">{d.label}</td>
                    <td>{d.inspections}</td>
                    <td className={d.alerts >= 6 ? "pf-dc-cell-warn" : ""}>{d.alerts}</td>
                    <td>{d.resolved}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
