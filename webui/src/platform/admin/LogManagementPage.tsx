import { useCallback, useEffect, useMemo, useState } from "react";
import {
  loadLogCategories,
  loadLogEntries,
  loadLogSources,
  loadLogStats,
  type LogEntry,
  type LogSource,
} from "../logsApi";

const LEVELS = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;
const LINE_LIMITS = [100, 200, 500] as const;

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function formatTime(ts: string | null) {
  if (!ts) return "—";
  return ts.replace("T", " ").slice(0, 19);
}

function levelClass(level: string) {
  switch (level) {
    case "ERROR":
    case "CRITICAL":
      return "is-error";
    case "WARNING":
      return "is-warning";
    case "DEBUG":
      return "is-debug";
    default:
      return "is-info";
  }
}

function categoryLabel(id: string) {
  const map: Record<string, string> = {
    platform: "平台",
    business: "业务",
    algorithm: "算法",
    auth: "鉴权",
    other: "其他",
  };
  return map[id] ?? id;
}

function shortLogger(name: string) {
  if (!name) return "—";
  const parts = name.split(".");
  return parts.length > 2 ? parts.slice(-2).join(".") : name;
}

function LogDetailPanel({ entry, sourceLabel }: { entry: LogEntry | null; sourceLabel: (id: string) => string }) {
  const [showStack, setShowStack] = useState(false);

  useEffect(() => {
    setShowStack(false);
  }, [entry?.id]);

  if (!entry) {
    return (
      <div className="pf-log-detail-panel pf-log-detail-empty">
        <p>选择一条日志查看详情与堆栈</p>
      </div>
    );
  }

  const stackLines = entry.detail_lines ?? [];

  return (
    <div className="pf-log-detail-panel">
      <div className="pf-log-detail-head">
        <div className="pf-log-detail-title">
          <span className={`pf-log-level-tag ${levelClass(entry.level)}`}>{entry.level}</span>
          {(entry.count ?? 1) > 1 ? <span className="pf-log-recent-count">聚合 ×{entry.count}</span> : null}
          <span className="pf-log-detail-time">{formatTime(entry.timestamp)}</span>
          <span className="pf-log-detail-source">{sourceLabel(entry.source)}</span>
        </div>
        <span className="pf-log-detail-logger" title={entry.logger}>
          {entry.logger || "—"}
        </span>
      </div>

      <p className="pf-log-detail-message">{entry.message}</p>

      {entry.root_cause ? (
        <div className="pf-log-detail-cause">
          <strong>根因</strong>
          <span>{entry.root_cause}</span>
        </div>
      ) : null}

      {stackLines.length > 0 ? (
        <div className="pf-log-detail-stack">
          <button type="button" className="pf-log-stack-toggle" onClick={() => setShowStack((v) => !v)}>
            {showStack ? "收起堆栈" : `展开堆栈（${stackLines.length} 行）`}
          </button>
          {showStack ? <pre className="pf-log-raw">{stackLines.join("\n")}</pre> : null}
        </div>
      ) : (
        <pre className="pf-log-raw pf-log-raw-compact">{entry.raw}</pre>
      )}
    </div>
  );
}

export function LogManagementPage() {
  const [sources, setSources] = useState<LogSource[]>([]);
  const [categories, setCategories] = useState<Array<{ id: string; label: string }>>([]);
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [totalMatched, setTotalMatched] = useState(0);
  const [stats, setStats] = useState<Awaited<ReturnType<typeof loadLogStats>> | null>(null);
  const [source, setSource] = useState("runtime");
  const [level, setLevel] = useState<(typeof LEVELS)[number]>("ALL");
  const [category, setCategory] = useState("all");
  const [keyword, setKeyword] = useState("");
  const [appliedKeyword, setAppliedKeyword] = useState("");
  const [lineLimit, setLineLimit] = useState<(typeof LINE_LIMITS)[number]>(200);
  const [groupSimilar, setGroupSimilar] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [loading, setLoading] = useState(true);
  const [hint, setHint] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setHint("");
    try {
      const useGroup = groupSimilar && (level === "ERROR" || level === "CRITICAL" || level === "ALL");
      const [srcList, catList, statData, entryData] = await Promise.all([
        loadLogSources(),
        loadLogCategories(),
        loadLogStats(24),
        loadLogEntries({
          source,
          level,
          category,
          q: appliedKeyword || undefined,
          limit: lineLimit,
          group: useGroup,
        }),
      ]);
      setSources(srcList);
      setCategories(catList);
      setStats(statData);
      setEntries(entryData.items);
      setTotalMatched(entryData.total_matched ?? entryData.items.length);
      if (!entryData.available) {
        setHint("当前日志源暂无文件，请确认服务已运行或切换其他日志源");
      }
      setSelectedId((prev) => {
        if (prev && entryData.items.some((e) => e.id === prev)) return prev;
        return entryData.items[0]?.id ?? null;
      });
    } catch (e) {
      setHint(String(e));
    } finally {
      setLoading(false);
    }
  }, [source, level, category, appliedKeyword, lineLimit, groupSimilar]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => void refresh(), 8000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, refresh]);

  const sourceLabel = useMemo(() => {
    const map = Object.fromEntries(sources.map((s) => [s.id, s.label]));
    return (id: string) => map[id] ?? id;
  }, [sources]);

  const jumpToError = useCallback((entry: LogEntry) => {
    setSource("runtime");
    setLevel("ERROR");
    setCategory("all");
    setGroupSimilar(true);
    const q = entry.message.split(" work_id=")[0]?.trim() || entry.message;
    setKeyword(q);
    setAppliedKeyword(q);
    setSelectedId(entry.id);
  }, []);

  const activeSource = sources.find((s) => s.id === source);
  const selectedEntry = entries.find((e) => e.id === selectedId) ?? null;

  const kpi = useMemo(() => {
    const lv = stats?.by_level ?? {};
    return {
      total: Object.values(lv).reduce((a, b) => a + b, 0),
      error: (lv.ERROR ?? 0) + (lv.CRITICAL ?? 0),
      warning: lv.WARNING ?? 0,
      info: lv.INFO ?? 0,
    };
  }, [stats]);

  const groupingActive = groupSimilar && (level === "ERROR" || level === "CRITICAL" || level === "ALL");

  return (
    <div className="pf-scroll pf-log-page">
      <header className="pf-log-top-bar">
        <div className="pf-log-top-left">
          <div className="pf-log-title-block">
            <span className="pf-log-title-mark" aria-hidden>
              ≣
            </span>
            <div>
              <h1>日志管理</h1>
              <p>平台运行、业务执行与 Hermes 日志统一检索</p>
            </div>
          </div>
          <div className="pf-log-metrics">
            <span className="pf-log-metric">
              <em>{kpi.total}</em>
              <i>24h 条目</i>
            </span>
            <span className="pf-log-metric pf-log-metric-error">
              <em>{kpi.error}</em>
              <i>错误</i>
            </span>
            <span className="pf-log-metric pf-log-metric-warn">
              <em>{kpi.warning}</em>
              <i>警告</i>
            </span>
            <span className="pf-log-metric">
              <em>{kpi.info}</em>
              <i>信息</i>
            </span>
          </div>
        </div>
        <div className="pf-log-header-actions">
          <label className="pf-log-auto-refresh">
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
            自动刷新
          </label>
          <button type="button" className="pf-btn pf-btn-sm pf-btn-primary" disabled={loading} onClick={() => void refresh()}>
            {loading ? "刷新中…" : "刷新"}
          </button>
        </div>
      </header>

      {hint ? <div className="pf-log-status">{hint}</div> : null}

      <div className="pf-log-layout">
        <aside className="pf-panel pf-log-sidebar">
          <h3 className="pf-log-sidebar-title">日志源</h3>
          <ul className="pf-log-source-list">
            {sources.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  className={`pf-log-source-item${source === s.id ? " is-active" : ""}${s.available ? "" : " is-unavailable"}`}
                  onClick={() => setSource(s.id)}
                >
                  <span className="pf-log-source-name">{s.label}</span>
                  <span className="pf-log-source-meta">{s.available ? formatBytes(s.size_bytes) : "不可用"}</span>
                </button>
              </li>
            ))}
          </ul>

          {stats?.recent_errors && stats.recent_errors.length > 0 ? (
            <section className="pf-log-recent-errors">
              <h4>近期错误</h4>
              <ul>
                {stats.recent_errors.map((e) => (
                  <li key={e.id}>
                    <button type="button" className="pf-log-recent-item" onClick={() => jumpToError(e)} title="点击筛选该错误">
                      <span className="pf-log-recent-head">
                        <span className={`pf-log-level-tag ${levelClass(e.level)}`}>{e.level}</span>
                        {(e.count ?? 1) > 1 ? <span className="pf-log-recent-count">×{e.count}</span> : null}
                      </span>
                      <span className="pf-log-recent-meta">
                        {formatTime(e.timestamp)} · {sourceLabel(e.source)}
                      </span>
                      <span className="pf-log-recent-msg">{e.root_cause || e.message}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </aside>

        <section className="pf-panel pf-log-main">
          <div className="pf-log-filter-bar">
            <label className="pf-log-filter">
              <span>级别</span>
              <select className="pf-select" value={level} onChange={(e) => setLevel(e.target.value as (typeof LEVELS)[number])}>
                {LEVELS.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="pf-log-filter">
              <span>分类</span>
              <select className="pf-select" value={category} onChange={(e) => setCategory(e.target.value)}>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="pf-log-filter">
              <span>条数</span>
              <select
                className="pf-select"
                value={lineLimit}
                onChange={(e) => setLineLimit(Number(e.target.value) as (typeof LINE_LIMITS)[number])}
              >
                {LINE_LIMITS.map((n) => (
                  <option key={n} value={n}>
                    最近 {n} 条
                  </option>
                ))}
              </select>
            </label>
            <label className="pf-log-filter pf-log-filter-check">
              <input
                type="checkbox"
                checked={groupSimilar}
                onChange={(e) => setGroupSimilar(e.target.checked)}
              />
              <span>聚合相似</span>
            </label>
            <label className="pf-log-filter pf-log-filter-search">
              <span>搜索</span>
              <input
                className="pf-cell-input"
                placeholder="关键词 / logger / 消息"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") setAppliedKeyword(keyword.trim());
                }}
              />
            </label>
            <button type="button" className="pf-btn pf-btn-sm" onClick={() => setAppliedKeyword(keyword.trim())}>
              查询
            </button>
          </div>

          <div className="pf-log-table-meta">
            <span>
              当前：<strong>{activeSource?.label ?? source}</strong>
              {activeSource?.updated_at
                ? ` · 更新 ${activeSource.updated_at.slice(0, 19).replace("T", " ")}`
                : ""}
              {groupingActive ? " · 已聚合相似错误" : ""}
            </span>
            <span>
              {groupingActive ? `原始 ${totalMatched} 条 · 展示 ${entries.length} 组` : `匹配 ${entries.length} 条`}
            </span>
          </div>

          <div className="pf-log-main-body">
            <div className="pf-log-table-wrap">
              <table className="pf-log-table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>级别</th>
                    <th>分类</th>
                    <th>模块</th>
                    <th>消息 / 根因</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="pf-log-empty">
                        {loading ? "加载中…" : "暂无匹配日志"}
                      </td>
                    </tr>
                  ) : (
                    entries.map((row) => (
                      <tr
                        key={row.id}
                        className={`pf-log-row ${levelClass(row.level)}${selectedId === row.id ? " is-selected" : ""}`}
                        onClick={() => setSelectedId(row.id)}
                      >
                        <td className="pf-log-col-time">{formatTime(row.timestamp)}</td>
                        <td>
                          <span className={`pf-log-level-tag ${levelClass(row.level)}`}>{row.level}</span>
                          {(row.count ?? 1) > 1 ? <span className="pf-log-row-count">×{row.count}</span> : null}
                        </td>
                        <td>{categoryLabel(row.category)}</td>
                        <td className="pf-log-col-logger" title={row.logger}>
                          {shortLogger(row.logger)}
                        </td>
                        <td className="pf-log-col-message">
                          <span className="pf-log-msg-primary">{row.message}</span>
                          {row.root_cause ? <span className="pf-log-msg-cause">{row.root_cause}</span> : null}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <LogDetailPanel entry={selectedEntry} sourceLabel={sourceLabel} />
          </div>
        </section>
      </div>
    </div>
  );
}
