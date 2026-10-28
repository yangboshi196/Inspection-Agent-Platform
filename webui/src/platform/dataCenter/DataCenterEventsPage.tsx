import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Badge } from "../components/Badge";
import { buildEventResolution, type DataCenterEvent } from "./dataCenterMock";
import { eventBadgeTone, eventStatusLabel } from "./dataCenterPageHelpers";
import { EventDetailMedia } from "./EventDetailMedia";
import {
  fetchInspectionEvent,
  loadInspectionEventsPage,
  patchInspectionEventStatus,
  syncInspectionDetectionBoxes,
} from "./inspectionEventApi";

type TypeFilter = "all" | "video" | "sensor";
type StatusFilter = "all" | "pending" | "processing" | "resolved";

type EventItem = DataCenterEvent;

type FilterCounts = {
  all: number;
  video: number;
  sensor: number;
  pending: number;
  processing: number;
  resolved: number;
};

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;

export function DataCenterEventsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(10);
  const [filterCounts, setFilterCounts] = useState<FilterCounts>({
    all: 0,
    video: 0,
    sensor: 0,
    pending: 0,
    processing: 0,
    resolved: 0,
  });
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [kwInput, setKwInput] = useState("");
  const [kw, setKw] = useState("");
  const [hint, setHint] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => setKw(kwInput.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [kwInput]);

  useEffect(() => {
    setPage(1);
  }, [typeFilter, statusFilter, kw, pageSize]);

  const refreshFilterCounts = async () => {
    const [all, video, sensor, pending, processing, resolved] = await Promise.all([
      loadInspectionEventsPage({ limit: 1 }),
      loadInspectionEventsPage({ kind: "video", limit: 1 }),
      loadInspectionEventsPage({ kind: "sensor", limit: 1 }),
      loadInspectionEventsPage({ status: "pending", limit: 1 }),
      loadInspectionEventsPage({ status: "processing", limit: 1 }),
      loadInspectionEventsPage({ status: "resolved", limit: 1 }),
    ]);
    setFilterCounts({
      all: all.total,
      video: video.total,
      sensor: sensor.total,
      pending: pending.total,
      processing: processing.total,
      resolved: resolved.total,
    });
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await refreshFilterCounts();
        void syncInspectionDetectionBoxes({ limit: 60 }).catch(() => {});
        if (cancelled || !selectedId) return;
        const fresh = await fetchInspectionEvent(selectedId);
        if (!cancelled) {
          setEvents((list) => list.map((e) => (e.id === fresh.id ? fresh : e)));
        }
      } catch (e) {
        if (!cancelled) setHint(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const kind = typeFilter === "all" ? undefined : typeFilter;
        const status = statusFilter === "all" ? undefined : statusFilter;
        const result = await loadInspectionEventsPage({
          kind,
          status,
          q: kw || undefined,
          limit: pageSize,
          offset: (page - 1) * pageSize,
        });
        if (cancelled) return;
        setEvents(result.items);
        setTotal(result.total);
        const stillVisible = result.items.some((e) => e.id === selectedId);
        if (!stillVisible) {
          setSelectedId(result.items[0]?.id ?? null);
        }
      } catch (e) {
        if (!cancelled) setHint(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [page, pageSize, typeFilter, statusFilter, kw]);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    (async () => {
      try {
        const fresh = await fetchInspectionEvent(selectedId);
        if (cancelled) return;
        setEvents((list) => list.map((e) => (e.id === fresh.id ? fresh : e)));
      } catch {
        /* 列表数据仍可展示 */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const selected = events.find((e) => e.id === selectedId) ?? events[0] ?? null;

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  useEffect(() => {
    const work = searchParams.get("work");
    if (!work) return;
    setKwInput(work);
    setSelectedId(null);
    setSearchParams({}, { replace: true });
  }, [searchParams, setSearchParams]);

  const advanceStatus = async () => {
    if (!selected) return;
    const next =
      selected.status === "pending"
        ? "processing"
        : selected.status === "processing"
          ? "resolved"
          : "resolved";
    const resolution = buildEventResolution(next, selected.type, selected.title, selected.time);
    try {
      const updated = await patchInspectionEventStatus(selected.id, next, {
        handler: resolution.handler,
        handled_at: resolution.handledAt,
        resolution_outcome: resolution.outcome,
        resolution_detail: resolution.detail,
      });
      setEvents((list) => list.map((e) => (e.id === updated.id ? updated : e)));
      await refreshFilterCounts();
      setHint(`事件已更新为「${eventStatusLabel(next)}」`);
    } catch (e) {
      setHint(String(e));
    }
  };

  const stats = useMemo(
    () => ({
      total: filterCounts.all,
      pending: filterCounts.pending,
      processing: filterCounts.processing,
      resolved: filterCounts.resolved,
      video: filterCounts.video,
      sensor: filterCounts.sensor,
    }),
    [filterCounts],
  );

  return (
    <div className="pf-usr-page">
      <header className="pf-usr-top-bar">
        <div className="pf-usr-top-left">
          <div className="pf-usr-title-block">
            <span className="pf-usr-title-mark" aria-hidden>◫</span>
            <h1>巡检事件</h1>
          </div>
          <div className="pf-usr-metrics" aria-label="事件统计">
            <span className="pf-usr-metric pf-usr-metric-blue"><strong>{stats.total}</strong><em>事件</em></span>
            <span className="pf-usr-metric pf-usr-metric-orange"><strong>{stats.pending}</strong><em>待处理</em></span>
            <span className="pf-usr-metric pf-usr-metric-purple"><strong>{stats.processing}</strong><em>处理中</em></span>
            <span className="pf-usr-metric pf-usr-metric-green"><strong>{stats.resolved}</strong><em>已关闭</em></span>
          </div>
          <span className="pf-usr-demo-tag">{loading ? "加载中" : "已接后端"}</span>
        </div>
      </header>

      {loading && events.length === 0 ? <div className="pf-usr-status">加载事件中…</div> : null}
      {hint ? <div className="pf-usr-status">{hint}</div> : null}

      <div className="pf-usr-layout">
        <aside className="pf-panel pf-usr-sidebar">
          <h2 className="pf-usr-section-title">事件类型</h2>
          <ul className="pf-usr-cat-list">
            {([
              { id: "all" as const, label: "全部", count: stats.total },
              { id: "video" as const, label: "视频分析", count: stats.video },
              { id: "sensor" as const, label: "传感异常", count: stats.sensor },
            ]).map((cat) => (
              <li key={cat.id}>
                <button
                  type="button"
                  className={`pf-usr-cat-item${typeFilter === cat.id ? " is-active" : ""}`}
                  onClick={() => {
                    setTypeFilter(cat.id);
                    setSelectedId(null);
                  }}
                >
                  <span>{cat.label}</span>
                  <span className="pf-usr-cat-count">{cat.count}</span>
                </button>
              </li>
            ))}
          </ul>

          <h3 className="pf-usr-section-title pf-usr-section-title-sm">处置状态</h3>
          <div className="pf-usr-board-grid">
            {([
              { id: "all" as const, label: "全部", count: stats.total },
              { id: "pending" as const, label: "待处理", count: stats.pending, tone: "orange" },
              { id: "processing" as const, label: "处理中", count: stats.processing, tone: "purple" },
              { id: "resolved" as const, label: "已关闭", count: stats.resolved, tone: "green" },
            ]).map((item) => (
              <button
                key={item.id}
                type="button"
                className={`pf-usr-board-card pf-usr-board-${item.tone ?? "gray"}${statusFilter === item.id ? " is-active" : ""}`}
                onClick={() => {
                  setStatusFilter(item.id);
                  setSelectedId(null);
                }}
              >
                <strong>{item.count}</strong>
                <span>{item.label}</span>
              </button>
            ))}
          </div>
        </aside>

        <section className="pf-panel pf-usr-list-panel">
          <div className="pf-usr-panel-head">
            <h2 className="pf-usr-section-title">事件列表 ({total})</h2>
            <input
              type="search"
              className="pf-cell-input pf-usr-search"
              placeholder="搜索事件、来源、巡检业务…"
              value={kwInput}
              onChange={(e) => setKwInput(e.target.value)}
            />
          </div>
          <div className="pf-usr-list">
            {events.length === 0 && !loading ? (
              <p className="pf-usr-list-empty">当前筛选下暂无事件</p>
            ) : (
              events.map((e) => (
                <button
                  key={e.id}
                  type="button"
                  className={`pf-usr-list-item${selected?.id === e.id ? " is-active" : ""}`}
                  onClick={() => setSelectedId(e.id)}
                >
                  <div className="pf-usr-list-item-top">
                    <div className="pf-usr-list-item-title">
                      <span className={`pf-dc-event-type pf-dc-event-type-${e.type}`}>
                        {e.type === "video" ? "视频" : "传感"}
                      </span>
                      <strong>{e.title}</strong>
                    </div>
                    <Badge tone={eventBadgeTone(e.status)}>{eventStatusLabel(e.status)}</Badge>
                  </div>
                  <p>{e.source} · {e.work}</p>
                  <div className="pf-usr-list-item-meta">
                    <span>{e.time.slice(5, 16)}</span>
                  </div>
                </button>
              ))
            )}
          </div>
          <footer className="pf-usr-list-footer">
            <div className="pf-usr-pagination" aria-label="事件列表分页">
              <label className="pf-usr-pagination-size">
                <span>每页</span>
                <select
                  className="pf-cell-input pf-usr-pagination-select"
                  value={pageSize}
                  onChange={(e) => setPageSize(Number(e.target.value))}
                >
                  {PAGE_SIZE_OPTIONS.map((size) => (
                    <option key={size} value={size}>{size}</option>
                  ))}
                </select>
                <span>条</span>
              </label>
              <button
                type="button"
                className="pf-usr-pagination-btn"
                disabled={page <= 1 || loading}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                aria-label="上一页"
              >
                ‹
              </button>
              <span className="pf-usr-pagination-info">
                {page} / {totalPages}
              </span>
              <button
                type="button"
                className="pf-usr-pagination-btn"
                disabled={page >= totalPages || loading}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                aria-label="下一页"
              >
                ›
              </button>
              <span className="pf-usr-pagination-total">共 {total} 条</span>
            </div>
          </footer>
        </section>

        <section className="pf-panel pf-usr-detail-panel">
          {selected ? (
            <div className="pf-usr-detail-body">
              <div className="pf-usr-detail-head">
                <div>
                  <div className="pf-usr-detail-badges">
                    <span className={`pf-dc-event-type pf-dc-event-type-${selected.type}`}>
                      {selected.type === "video" ? "视频分析" : "传感异常"}
                    </span>
                    <Badge tone={eventBadgeTone(selected.status)}>{eventStatusLabel(selected.status)}</Badge>
                  </div>
                  <h2>{selected.title}</h2>
                </div>
                {selected.status !== "resolved" ? (
                  <button type="button" className="pf-btn pf-btn-sm pf-btn-primary" onClick={() => void advanceStatus()}>
                    {selected.status === "pending" ? "开始处理" : "标记关闭"}
                  </button>
                ) : null}
              </div>

              <dl className="pf-usr-dl">
                <div><dt>上报时间</dt><dd>{selected.reportedAt}</dd></div>
                <div><dt>来源设备</dt><dd>{selected.source}</dd></div>
                <div><dt>关联巡检业务</dt><dd>{selected.work}</dd></div>
                <div><dt>事件类型</dt><dd>{selected.type === "video" ? "视频分析" : "传感异常"}</dd></div>
                {selected.type === "video" && selected.algorithmName ? (
                  <div><dt>分析算法</dt><dd>{selected.algorithmName}</dd></div>
                ) : null}
                {selected.type === "sensor" && selected.value != null ? (
                  <div><dt>异常读数</dt><dd>{selected.value}（阈值 {selected.threshold}）</dd></div>
                ) : null}
                <div><dt>处置状态</dt><dd>{eventStatusLabel(selected.status)}</dd></div>
              </dl>

              <EventDetailMedia key={selected.id} event={selected} />

              <section
                className={`pf-usr-event-resolution pf-usr-event-resolution-${selected.status}`}
                aria-label="处理结果"
              >
                <div className="pf-usr-event-resolution-head">
                  <h3 className="pf-usr-section-title">处理结果</h3>
                  <Badge tone={eventBadgeTone(selected.status)}>{selected.resolution.outcome}</Badge>
                </div>
                <div className="pf-usr-event-resolution-box">
                  {(selected.resolution.handler || selected.resolution.handledAt) ? (
                    <dl className="pf-usr-event-resolution-meta">
                      {selected.resolution.handler ? (
                        <div><dt>处理人</dt><dd>{selected.resolution.handler}</dd></div>
                      ) : null}
                      {selected.resolution.handledAt ? (
                        <div><dt>处理时间</dt><dd>{selected.resolution.handledAt}</dd></div>
                      ) : null}
                    </dl>
                  ) : null}
                  <p>{selected.resolution.detail}</p>
                </div>
              </section>

              <p className="pf-dc-page-foot">
                管理员可在 <Link to="/admin/inspection-works">巡检业务</Link> 调整关联巡检业务与运行状态。
              </p>
            </div>
          ) : (
            <p className="pf-usr-detail-empty">请选择事件查看详情</p>
          )}
        </section>
      </div>
    </div>
  );
}
