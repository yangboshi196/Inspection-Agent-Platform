import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Badge } from "../components/Badge";
import { Modal } from "../components/Modal";
import {
  filterReportsByDateRange,
  filterReportsByTime,
  REPORT_TIME_FILTERS,
  reportTimeFilterLabel,
  type ReportTimeFilter,
} from "./dashboardTrend";
import {
  frequencyLabel,
  inspectionReportStats,
  reportFullText,
  type InspectionReport,
  type ReportContentSection,
} from "./reportPlanMock";
import { useReportData } from "./ReportDataContext";
import { exportReportPdf } from "./reportPdfExport";

type FreqFilter = "all" | InspectionReport["frequency"];

function ReportSectionDetail({ section }: { section: ReportContentSection }) {
  if (!section.detail) {
    return <p className="pf-usr-report-section-detail-lead">{section.body}</p>;
  }

  const lines = section.detail.split("\n").filter(Boolean);
  return (
    <div className="pf-usr-report-section-detail">
      <p className="pf-usr-report-section-detail-lead">{section.body}</p>
      <ul>
        {lines.map((line, index) => (
          <li key={`${index}-${line}`}>{line.replace(/^[·-]\s*/, "")}</li>
        ))}
      </ul>
    </div>
  );
}

export function DataCenterReportsPage() {
  const { loading, error, reports, hasSubscription } = useReportData();
  const [searchParams, setSearchParams] = useSearchParams();

  const [freqFilter, setFreqFilter] = useState<FreqFilter>("all");
  const [timeFilter, setTimeFilter] = useState<ReportTimeFilter>("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(reports[0]?.id ?? null);
  const [kw, setKw] = useState("");
  const [hint, setHint] = useState("");
  const [exportingPdf, setExportingPdf] = useState(false);
  const [sectionModal, setSectionModal] = useState<ReportContentSection | null>(null);

  const reportStats = inspectionReportStats(reports);

  const useCustomRange = Boolean(dateFrom.trim() && dateTo.trim());

  const timeFilteredReports = useMemo(() => {
    if (useCustomRange) return filterReportsByDateRange(reports, dateFrom, dateTo);
    return filterReportsByTime(reports, timeFilter);
  }, [reports, timeFilter, useCustomRange, dateFrom, dateTo]);

  const timeFilterCounts = useMemo(
    () =>
      Object.fromEntries(
        REPORT_TIME_FILTERS.map((id) => [id, filterReportsByTime(reports, id).length]),
      ) as Record<ReportTimeFilter, number>,
    [reports],
  );

  const freqCategories = useMemo(
    () => [
      { id: "all" as const, label: "全部", count: timeFilteredReports.length },
      {
        id: "daily" as const,
        label: "日报",
        count: timeFilteredReports.filter((r) => r.frequency === "daily").length,
      },
      {
        id: "weekly" as const,
        label: "周报",
        count: timeFilteredReports.filter((r) => r.frequency === "weekly").length,
      },
      {
        id: "monthly" as const,
        label: "月报",
        count: timeFilteredReports.filter((r) => r.frequency === "monthly").length,
      },
      {
        id: "adhoc" as const,
        label: "临时",
        count: timeFilteredReports.filter((r) => r.frequency === "adhoc").length,
      },
    ],
    [timeFilteredReports],
  );

  const filtered = useMemo(() => {
    let list = timeFilteredReports;
    if (freqFilter !== "all") list = list.filter((r) => r.frequency === freqFilter);
    const q = kw.trim().toLowerCase();
    if (q) {
      list = list.filter((r) =>
        [r.title, r.period, r.summary, frequencyLabel(r.frequency), r.planName ?? ""]
          .join(" ")
          .toLowerCase()
          .includes(q),
      );
    }
    return list;
  }, [timeFilteredReports, freqFilter, kw]);

  const selected = filtered.find((r) => r.id === selectedId) ?? filtered[0] ?? null;

  useEffect(() => {
    const focus = searchParams.get("focus");
    if (focus && reports.some((r) => r.id === focus)) {
      setSelectedId(focus);
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, reports, setSearchParams]);

  useEffect(() => {
    if (reports.length === 0) {
      setSelectedId(null);
      return;
    }
    if (selectedId && reports.some((r) => r.id === selectedId)) return;
    setSelectedId(reports[0]?.id ?? null);
  }, [reports, selectedId]);

  useEffect(() => {
    setSectionModal(null);
  }, [selected?.id]);

  const selectTimePreset = (id: ReportTimeFilter) => {
    setTimeFilter(id);
    setDateFrom("");
    setDateTo("");
    setSelectedId(null);
  };

  const handleDateFromChange = (value: string) => {
    setDateFrom(value);
    setSelectedId(null);
  };

  const handleDateToChange = (value: string) => {
    setDateTo(value);
    setSelectedId(null);
  };

  const clearCustomRange = () => {
    setDateFrom("");
    setDateTo("");
    setSelectedId(null);
  };

  const selectedFullText = selected ? reportFullText(selected) : "";

  const copyFullText = async () => {
    if (!selectedFullText) return;
    try {
      await navigator.clipboard.writeText(selectedFullText);
      setHint("报告全文已复制到剪贴板");
    } catch {
      setHint("复制失败，请手动选择全文复制");
    }
  };

  const downloadPdf = async () => {
    if (!selected || !selectedFullText || exportingPdf) return;
    setExportingPdf(true);
    try {
      await exportReportPdf(selected.title, selectedFullText);
      setHint(`已导出「${selected.title}.pdf」`);
    } catch {
      setHint("PDF 导出失败，请稍后重试");
    } finally {
      setExportingPdf(false);
    }
  };

  return (
    <div className="pf-usr-page">
      <header className="pf-usr-top-bar">
        <div className="pf-usr-top-left">
          <div className="pf-usr-title-block">
            <span className="pf-usr-title-mark" aria-hidden>⊞</span>
            <h1>巡检报告</h1>
          </div>
          <div className="pf-usr-metrics" aria-label="报告统计">
            <span className="pf-usr-metric pf-usr-metric-blue">
              <strong>{reportStats.total}</strong>
              <em>报告</em>
            </span>
          </div>
          <span className="pf-usr-demo-tag">演示</span>
        </div>
      </header>

      {error ? <div className="pf-usr-status pf-usr-status-error">{error}</div> : null}
      {loading ? <div className="pf-usr-status">正在加载报告数据…</div> : null}
      {hint ? <div className="pf-usr-status">{hint}</div> : null}

      <div className="pf-usr-layout pf-usr-layout-reports">
        <aside className="pf-panel pf-usr-sidebar">
          <h2 className="pf-usr-section-title">报告类型</h2>
          <ul className="pf-usr-cat-list">
            {freqCategories.map((cat) => (
              <li key={cat.id}>
                <button
                  type="button"
                  className={`pf-usr-cat-item${freqFilter === cat.id ? " is-active" : ""}`}
                  onClick={() => {
                    setFreqFilter(cat.id);
                    setSelectedId(null);
                  }}
                >
                  <span>{cat.label}</span>
                  <span className="pf-usr-cat-count">{cat.count}</span>
                </button>
              </li>
            ))}
          </ul>

          <h3 className="pf-usr-section-title pf-usr-section-title-sm">时间范围</h3>
          <ul className="pf-usr-cat-list pf-usr-report-time-list">
            {REPORT_TIME_FILTERS.map((id) => (
              <li key={id}>
                <button
                  type="button"
                  className={`pf-usr-region-item${!useCustomRange && timeFilter === id ? " is-active" : ""}`}
                  onClick={() => selectTimePreset(id)}
                >
                  <span>{reportTimeFilterLabel(id)}</span>
                  <span>{timeFilterCounts[id]}</span>
                </button>
              </li>
            ))}
          </ul>

          <div className={`pf-usr-report-date-range${useCustomRange ? " is-active" : ""}`}>
            <div className="pf-usr-report-date-range-head">
              <span>自定义时间</span>
              {useCustomRange ? (
                <button type="button" className="pf-usr-report-date-clear" onClick={clearCustomRange}>
                  清除
                </button>
              ) : null}
            </div>
            <label className="pf-usr-report-date-field">
              <span>开始日期</span>
              <input
                type="date"
                className="pf-cell-input pf-usr-report-date-input"
                value={dateFrom}
                onChange={(e) => handleDateFromChange(e.target.value)}
              />
            </label>
            <label className="pf-usr-report-date-field">
              <span>结束日期</span>
              <input
                type="date"
                className="pf-cell-input pf-usr-report-date-input"
                value={dateTo}
                min={dateFrom || undefined}
                onChange={(e) => handleDateToChange(e.target.value)}
              />
            </label>
            {useCustomRange ? (
              <p className="pf-usr-report-date-hint">
                {dateFrom} 至 {dateTo} · 共 {timeFilteredReports.length} 份
              </p>
            ) : (
              <p className="pf-usr-report-date-hint">选择起止日期后按更新时间筛选</p>
            )}
          </div>
        </aside>

        <section className="pf-panel pf-usr-list-panel">
          <div className="pf-usr-panel-head">
            <h2 className="pf-usr-section-title">报告列表 ({filtered.length})</h2>
            <input
              type="search"
              className="pf-cell-input pf-usr-search"
              placeholder="搜索报告…"
              value={kw}
              onChange={(e) => setKw(e.target.value)}
            />
          </div>
          <div className="pf-usr-list">
            {!loading && hasSubscription === false ? (
              <p className="pf-usr-list-empty pf-usr-list-empty-subscribe">
                您还没有订阅任何业务，请前往「管理控制台 → 巡检业务」页面进行订阅
              </p>
            ) : filtered.length === 0 ? (
              <p className="pf-usr-list-empty">当前筛选下暂无报告</p>
            ) : (
              filtered.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  className={`pf-usr-list-item${selected?.id === r.id ? " is-active" : ""}`}
                  onClick={() => setSelectedId(r.id)}
                >
                  <div className="pf-usr-list-item-top">
                    <div className="pf-usr-list-item-badges">
                      <Badge tone="info">{frequencyLabel(r.frequency)}</Badge>
                    </div>
                  </div>
                  <strong>{r.title}</strong>
                  <p>{r.period}</p>
                  <div className="pf-usr-list-item-meta">
                    <span>{r.planName ? `来源：${r.planName}` : "系统推送"}</span>
                    <span>更新 {r.updatedAt.slice(5, 16)}</span>
                  </div>
                </button>
              ))
            )}
          </div>
        </section>

        <section className="pf-panel pf-usr-detail-panel">
          {selected ? (
            <div className="pf-usr-detail-body pf-usr-report-detail">
              <div className="pf-usr-detail-head">
                <div>
                  <div className="pf-usr-detail-badges">
                    <Badge tone="info">{frequencyLabel(selected.frequency)}</Badge>
                  </div>
                  <h2>{selected.title}</h2>
                  <p className="pf-usr-detail-sub">
                    {selected.period} · 更新 {selected.updatedAt}
                    {selected.planName ? ` · 来源：${selected.planName}` : " · 系统推送"}
                  </p>
                </div>
                <div className="pf-usr-detail-actions">
                  <button type="button" className="pf-btn pf-btn-sm" onClick={copyFullText}>
                    复制全文
                  </button>
                  <button type="button" className="pf-btn pf-btn-sm" onClick={downloadPdf} disabled={exportingPdf}>
                    {exportingPdf ? "导出中…" : "导出 PDF"}
                  </button>
                </div>
              </div>

              <div className="pf-usr-summary-box">
                <h3>摘要</h3>
                <p>{selected.summary}</p>
              </div>

              <div className="pf-usr-report-fulltext">
                <div className="pf-usr-report-fulltext-head">
                  <h3>报告全文</h3>
                </div>
                <textarea
                  className="pf-cell-input pf-usr-report-fulltext-area"
                  readOnly
                  value={selectedFullText}
                  aria-label="报告全文"
                />
              </div>

              <div className="pf-usr-sections pf-usr-sections-compact">
                <span className="pf-usr-sections-compact-title">章节概览</span>
                <div className="pf-usr-section-chip-row">
                  {selected.sections.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      className="pf-usr-section-chip"
                      onClick={() => setSectionModal(s)}
                    >
                      {s.title}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <p className="pf-usr-detail-empty">请选择报告查看详情</p>
          )}
        </section>
      </div>

      <Modal open={sectionModal != null} title={sectionModal?.title ?? ""} onClose={() => setSectionModal(null)} wide>
        {sectionModal ? <ReportSectionDetail section={sectionModal} /> : null}
      </Modal>
    </div>
  );
}
