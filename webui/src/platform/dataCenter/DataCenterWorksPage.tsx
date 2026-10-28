import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "../components/Badge";
import { Modal } from "../components/Modal";
import type { InspectionScheduleMode } from "../types";
import {
  healthLabel,
  healthTone,
  scheduleModeLabel,
  scheduleTone,
  workCompleteness,
} from "./dataCenterPageHelpers";
import {
  mergedWorkStats,
  resolveAlgoNames,
  resolveRuleNames,
  runPhaseLabel,
  runPhaseTone,
  scheduleTimeDescription,
  type WorkCameraBinding,
  type WorkDisplayDetail,
  type WorkRunPhase,
} from "./worksDisplayMock";
import { loadWorkDisplayDetails } from "./worksDisplayApi";

type ScheduleFilter = InspectionScheduleMode | "all";
type HealthFilter = "all" | WorkDisplayDetail["runtime"]["health"];
type RunPhaseFilter = "all" | WorkRunPhase;

type DetailModal =
  | { kind: "algo"; camera: WorkCameraBinding }
  | { kind: "rule"; camera: WorkCameraBinding }
  | null;

export function DataCenterWorksPage() {
  const [details, setDetails] = useState<WorkDisplayDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [hint, setHint] = useState("");
  const [scheduleFilter, setScheduleFilter] = useState<ScheduleFilter>("all");
  const [healthFilter, setHealthFilter] = useState<HealthFilter>("all");
  const [runPhaseFilter, setRunPhaseFilter] = useState<RunPhaseFilter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [kw, setKw] = useState("");
  const [detailModal, setDetailModal] = useState<DetailModal>(null);
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await loadWorkDisplayDetails();
        if (cancelled) return;
        setDetails(list);
        setSelectedId(list[0]?.workId ?? null);
      } catch (e) {
        if (!cancelled) setHint(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const stats = mergedWorkStats(details);

  const filtered = useMemo(() => {
    let list = details;
    if (scheduleFilter !== "all") list = list.filter((d) => d.work.schedule_mode === scheduleFilter);
    if (healthFilter !== "all") {
      list =
        healthFilter === "warning"
          ? list.filter((d) => d.runtime.health === "warning" || d.runtime.health === "critical")
          : list.filter((d) => d.runtime.health === healthFilter);
    }
    if (runPhaseFilter !== "all") list = list.filter((d) => d.runPhase === runPhaseFilter);
    const q = kw.trim().toLowerCase();
    if (q) {
      list = list.filter((d) =>
        [d.work.name, d.work.desc, d.work.region_name, d.work.work_id, healthLabel(d.runtime.health)]
          .join(" ")
          .toLowerCase()
          .includes(q),
      );
    }
    return list;
  }, [details, scheduleFilter, healthFilter, runPhaseFilter, kw]);

  const selected = filtered.find((d) => d.workId === selectedId) ?? filtered[0] ?? null;

  useEffect(() => {
    setSelectedRegionId(null);
  }, [selected?.workId]);

  const activeRegion = useMemo(() => {
    if (!selected || selected.regions.length === 0) return null;
    return selected.regions.find((r) => r.regionId === selectedRegionId) ?? selected.regions[0];
  }, [selected, selectedRegionId]);

  return (
    <div className="pf-usr-page">
      <header className="pf-usr-top-bar">
        <div className="pf-usr-top-left">
          <div className="pf-usr-title-block">
            <span className="pf-usr-title-mark" aria-hidden>◉</span>
            <h1>巡检业务展示</h1>
          </div>
          <div className="pf-usr-metrics" aria-label="巡检业务统计">
            <span className="pf-usr-metric pf-usr-metric-blue"><strong>{stats.total}</strong><em>巡检业务</em></span>
            <span className="pf-usr-metric pf-usr-metric-green"><strong>{stats.running}</strong><em>进行中</em></span>
            <span className="pf-usr-metric pf-usr-metric-purple"><strong>{stats.avgCompliance}%</strong><em>平均合规</em></span>
            <span className="pf-usr-metric pf-usr-metric-orange"><strong>{stats.warning}</strong><em>需关注</em></span>
          </div>
          <span className="pf-usr-demo-tag">{loading ? "加载中" : "已接后端"}</span>
        </div>
        <div className="pf-usr-header-actions">
          <Link to="/admin/inspection-works" className="pf-btn pf-btn-sm">配置巡检业务</Link>
        </div>
      </header>

      {loading ? <div className="pf-usr-status">加载巡检业务…</div> : null}
      {hint ? <div className="pf-usr-status">{hint}</div> : null}

      <div className="pf-usr-layout">
        <aside className="pf-panel pf-usr-sidebar">
          <h2 className="pf-usr-section-title">运行方式</h2>
          <ul className="pf-usr-cat-list">
            {([
              { id: "all" as const, label: "全部巡检业务", count: stats.total },
              { id: "periodic" as const, label: scheduleModeLabel("periodic"), count: stats.periodic },
              { id: "scheduled" as const, label: scheduleModeLabel("scheduled"), count: stats.scheduled },
              { id: "continuous" as const, label: scheduleModeLabel("continuous"), count: stats.continuous },
              { id: "manual" as const, label: scheduleModeLabel("manual"), count: stats.manual },
            ]).map((cat) => (
              <li key={cat.id}>
                <button
                  type="button"
                  className={`pf-usr-cat-item${scheduleFilter === cat.id ? " is-active" : ""}`}
                  onClick={() => {
                    setScheduleFilter(cat.id);
                    setSelectedId(null);
                  }}
                >
                  <span>{cat.label}</span>
                  <span className="pf-usr-cat-count">{cat.count}</span>
                </button>
              </li>
            ))}
          </ul>

          <div className="pf-usr-sidebar-board">
            <h3 className="pf-usr-section-title pf-usr-section-title-sm">运行概览</h3>
            <div className="pf-usr-board-grid pf-usr-board-grid-2">
              <div className="pf-usr-board-card pf-usr-board-green">
                <strong>{stats.healthy}</strong>
                <span>运行正常</span>
              </div>
              <div className="pf-usr-board-card pf-usr-board-purple">
                <strong>{stats.avgCompliance}%</strong>
                <span>平均合规</span>
              </div>
            </div>
          </div>
        </aside>

        <section className="pf-panel pf-usr-list-panel">
          <div className="pf-usr-panel-head pf-usr-panel-head-stack">
            <h2 className="pf-usr-section-title">巡检业务列表 ({filtered.length})</h2>
            <input
              type="search"
              className="pf-cell-input pf-usr-search"
              placeholder="搜索巡检业务…"
              value={kw}
              onChange={(e) => setKw(e.target.value)}
            />
            <div className="pf-usr-filter-row">
              <span className="pf-usr-filter-label">运行状态</span>
              {([
                ["all", "全部", stats.total],
                ["running", "进行中", stats.running],
                ["healthy", "正常", stats.healthy],
                ["warning", "需关注", stats.warning],
                ["idle", "空闲", stats.idle],
              ] as const).map(([id, label, count]) => (
                <button
                  key={id}
                  type="button"
                  className={`pf-usr-filter-chip${
                    id === "all"
                      ? healthFilter === "all" && runPhaseFilter === "all"
                        ? " is-active"
                        : ""
                      : id === "running"
                        ? runPhaseFilter === "running"
                          ? " is-active"
                          : ""
                        : healthFilter === id
                          ? " is-active"
                          : ""
                  }`}
                  onClick={() => {
                    if (id === "running") {
                      setRunPhaseFilter(id);
                      setHealthFilter("all");
                    } else if (id === "all") {
                      setRunPhaseFilter("all");
                      setHealthFilter("all");
                    } else {
                      setHealthFilter(id);
                      setRunPhaseFilter("all");
                    }
                    setSelectedId(null);
                  }}
                >
                  {label} {count}
                </button>
              ))}
            </div>
          </div>
          <div className="pf-usr-list">
            {filtered.length === 0 ? (
              <p className="pf-usr-list-empty">当前筛选下暂无巡检业务</p>
            ) : (
              filtered.map((d) => {
                const c = workCompleteness(d.work);
                return (
                  <button
                    key={d.workId}
                    type="button"
                    className={`pf-usr-list-item pf-usr-list-item-status pf-usr-status-${d.runtime.health}${selected?.workId === d.workId ? " is-active" : ""}`}
                    onClick={() => setSelectedId(d.workId)}
                  >
                    <div className="pf-usr-list-item-top">
                      <div className="pf-usr-list-item-badges">
                        <Badge tone={runPhaseTone(d.runPhase)}>{runPhaseLabel(d.runPhase)}</Badge>
                        <Badge tone={healthTone(d.runtime.health)}>{healthLabel(d.runtime.health)}</Badge>
                        <Badge tone={scheduleTone(d.work.schedule_mode)}>{scheduleModeLabel(d.work.schedule_mode)}</Badge>
                      </div>
                    </div>
                    <strong>{d.work.name}</strong>
                    <p>{d.work.desc || "暂无说明"}</p>
                    <div className="pf-usr-list-item-meta">
                      <span>{d.regions.length} 个区域 · {d.regions.reduce((n, r) => n + r.cameras.length, 0)} 路摄像头</span>
                      <span>合规 {d.runtime.compliance}%</span>
                      <span>完整度 {c}%</span>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </section>

        <section className="pf-panel pf-usr-detail-panel">
          {selected ? (
            <div className="pf-usr-detail-body">
              <div className="pf-usr-detail-head">
                <div>
                  <div className="pf-usr-detail-badges">
                    <Badge tone={runPhaseTone(selected.runPhase)}>{runPhaseLabel(selected.runPhase)}</Badge>
                    <Badge tone={healthTone(selected.runtime.health)}>{healthLabel(selected.runtime.health)}</Badge>
                    <Badge tone={scheduleTone(selected.work.schedule_mode)}>{scheduleModeLabel(selected.work.schedule_mode)}</Badge>
                  </div>
                  <h2>{selected.work.name}</h2>
                  <p className="pf-usr-detail-sub">{selected.work.work_id} · {selected.regions.length} 个关联区域</p>
                </div>
              </div>

              <p className="pf-usr-detail-desc">{selected.work.desc || "暂无说明"}</p>

              <div className="pf-usr-detail-metrics">
                <div className="pf-usr-detail-metric">
                  <span>合规率</span>
                  <strong>{selected.runtime.compliance}%</strong>
                  <div className="pf-dc-progress pf-dc-progress-sm">
                    <span style={{ width: `${selected.runtime.compliance}%` }} />
                  </div>
                </div>
                <div className="pf-usr-detail-metric pf-usr-detail-metric-alerts">
                  <span>7日告警</span>
                  <strong className={selected.runtime.alerts7d > 3 ? "pf-usr-warn" : ""}>{selected.runtime.alerts7d}</strong>
                  <Link
                    to={`/user/events?work=${encodeURIComponent(selected.work.name)}`}
                    className="pf-usr-metric-action"
                  >
                    查看事件
                  </Link>
                </div>
                <div className="pf-usr-detail-metric">
                  <span>告警处置率</span>
                  <strong>{selected.runtime.alertResolutionRate}%</strong>
                  <div className="pf-dc-progress pf-dc-progress-sm">
                    <span style={{ width: `${selected.runtime.alertResolutionRate}%` }} />
                  </div>
                </div>
              </div>

              <dl className="pf-usr-dl">
                <div><dt>运行状态</dt><dd>{runPhaseLabel(selected.runPhase)} · {healthLabel(selected.runtime.health)}</dd></div>
                <div><dt>运行时间</dt><dd>{scheduleTimeDescription(selected.work)}</dd></div>
                <div><dt>运行方式</dt><dd>{scheduleModeLabel(selected.work.schedule_mode)}</dd></div>
                <div><dt>上次执行</dt><dd>{selected.runtime.lastRun}</dd></div>
                <div><dt>下次执行时间</dt><dd>{selected.runtime.nextRun}</dd></div>
              </dl>

              <section className="pf-usr-work-regions">
                <div className="pf-usr-work-regions-head">
                  <h3 className="pf-usr-section-title">区域与摄像头</h3>
                  <span className="pf-usr-work-regions-count">{selected.regions.length} 个区域</span>
                </div>
                {selected.regions.length > 0 ? (
                  <>
                    <div className="pf-usr-region-picker" role="tablist" aria-label="选择区域">
                      {selected.regions.map((region) => (
                        <button
                          key={region.regionId}
                          type="button"
                          role="tab"
                          aria-selected={activeRegion?.regionId === region.regionId}
                          className={`pf-usr-region-chip${activeRegion?.regionId === region.regionId ? " is-active" : ""}`}
                          onClick={() => setSelectedRegionId(region.regionId)}
                        >
                          <span>{region.regionName}</span>
                          <em>{region.cameras.length}</em>
                        </button>
                      ))}
                    </div>
                    {activeRegion ? (
                      <article className="pf-usr-work-region">
                        {activeRegion.cameras.length > 0 ? (
                          <ul className="pf-usr-work-camera-list">
                            {activeRegion.cameras.map((camera) => (
                              <li key={camera.cameraId} className="pf-usr-work-camera-item">
                                <span className="pf-usr-camera-name-chip">{camera.cameraName}</span>
                                <div className="pf-usr-work-camera-resources">
                                  <button
                                    type="button"
                                    className="pf-usr-resource-chip"
                                    onClick={() => setDetailModal({ kind: "algo", camera })}
                                  >
                                    算法 <em>{camera.algorithmIds.length}</em>
                                  </button>
                                  <button
                                    type="button"
                                    className="pf-usr-resource-chip"
                                    onClick={() => setDetailModal({ kind: "rule", camera })}
                                  >
                                    规范 <em>{camera.ruleIds.length}</em>
                                  </button>
                                </div>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="pf-usr-work-region-empty">该区域暂无绑定摄像头</p>
                        )}
                      </article>
                    ) : null}
                  </>
                ) : (
                  <p className="pf-usr-work-region-empty">暂无关联区域</p>
                )}
              </section>
            </div>
          ) : (
            <p className="pf-usr-detail-empty">请选择巡检业务查看详情</p>
          )}
        </section>
      </div>

      <Modal
        open={detailModal != null}
        title={detailModal?.kind === "algo" ? "关联算法" : "关联规范"}
        onClose={() => setDetailModal(null)}
      >
        {detailModal && selected ? (
          <div className="pf-usr-resource-detail">
            <p className="pf-usr-resource-detail-sub">{detailModal.camera.cameraName}</p>
            <ul>
              {(detailModal.kind === "algo"
                ? resolveAlgoNames(selected.work, detailModal.camera.algorithmIds)
                : resolveRuleNames(selected.work, detailModal.camera.ruleIds)
              ).map((item) => (
                <li key={item.id}>{item.name}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
