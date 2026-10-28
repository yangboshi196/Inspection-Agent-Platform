import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "../components/Badge";
import {
  buildDispatchRows,
  buildProcessRows,
  DEMO_OWNERS,
  DEMO_PROPERTIES,
  DEMO_REGIONS,
  DEMO_WORKS,
  defaultConfig,
  generateFlowFromDescription,
  PROMPT_CHIPS,
  type DispatchRow,
  type GeneratedFlow,
  type ProcessRow,
  type TriggerTaskConfig,
} from "./triggerTaskMock";

type Phase = "describe" | "configure" | "running" | "done";

const PHASE_STEPS: { id: Phase | "done"; label: string }[] = [
  { id: "describe", label: "描述" },
  { id: "configure", label: "配置" },
  { id: "running", label: "执行" },
  { id: "done", label: "完成" },
];

function phaseIndex(phase: Phase): number {
  if (phase === "describe") return 0;
  if (phase === "configure") return 1;
  return 2;
}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

function ownerInitial(name: string) {
  return name.slice(0, 1);
}

export function TriggerTaskPage() {
  const [phase, setPhase] = useState<Phase>("describe");
  const [description, setDescription] = useState("");
  const [agentLoading, setAgentLoading] = useState(false);
  const [flow, setFlow] = useState<GeneratedFlow | null>(null);
  const [config, setConfig] = useState<TriggerTaskConfig>(defaultConfig());
  const [progress, setProgress] = useState(0);
  const [dispatch, setDispatch] = useState<DispatchRow[]>([]);
  const [process, setProcess] = useState<ProcessRow[]>([]);
  const [reportReady, setReportReady] = useState(false);

  const activePhaseIdx = phase === "done" ? 3 : phaseIndex(phase);

  const propertyName = useMemo(
    () => DEMO_PROPERTIES.find((p) => p.id === config.propertyId)?.name ?? "—",
    [config.propertyId],
  );

  const handleGenerate = useCallback(async () => {
    setAgentLoading(true);
    await sleep(1400);
    const generated = generateFlowFromDescription(description);
    setFlow(generated);
    setConfig(generated.config);
    setAgentLoading(false);
    setPhase("configure");
  }, [description]);

  const toggleId = (list: string[], id: string) =>
    list.includes(id) ? list.filter((x) => x !== id) : [...list, id];

  const updateConfig = (patch: Partial<TriggerTaskConfig>) => {
    setConfig((c) => ({ ...c, ...patch }));
  };

  const resetFlow = () => {
    setPhase("describe");
    setFlow(null);
    setProgress(0);
    setReportReady(false);
  };

  const handleLaunch = useCallback(async () => {
    setPhase("running");
    setProgress(0);
    setReportReady(false);
    const rows = buildDispatchRows(config);
    const prows = buildProcessRows(config);
    setDispatch(rows);
    setProcess(prows);

    for (let p = 0; p <= 100; p += 5) {
      await sleep(280);
      setProgress(p);
      setDispatch((prev) =>
        prev.map((r, i) => ({
          ...r,
          progress: Math.min(100, Math.max(0, p - i * 12)),
          status: p - i * 12 >= 100 ? "done" : p - i * 12 > 0 ? "running" : "pending",
        })),
      );
      setProcess((prev) =>
        prev.map((r, i) => ({
          ...r,
          status:
            p > 70 && i < 2 ? "resolved" : p > 35 && i === 0 ? "processing" : "queued",
          updatedAt:
            p > 20
              ? `${String(9 + Math.floor(p / 15)).padStart(2, "0")}:${String(10 + i * 7).padStart(2, "0")}`
              : "—",
        })),
      );
    }
    setReportReady(true);
    setPhase("done");
  }, [config]);

  return (
    <div className="pf-usr-page pf-tt-page">
      <header className="pf-tt-page-head">
        <h1>触发任务</h1>
        {phase !== "describe" ? (
          <button type="button" className="pf-btn pf-btn-sm pf-tt-btn-ghost" onClick={resetFlow}>
            重来
          </button>
        ) : null}
      </header>

      <nav className="pf-tt-phase-nav" aria-label="任务阶段">
        {PHASE_STEPS.map((step, index) => {
          const done = index < activePhaseIdx;
          const current = index === activePhaseIdx;
          return (
            <div
              key={step.id}
              className={`pf-tt-phase-item${done ? " is-done" : ""}${current ? " is-current" : ""}`}
            >
              <span className="pf-tt-phase-dot">{done ? "✓" : index + 1}</span>
              <span className="pf-tt-phase-label">{step.label}</span>
            </div>
          );
        })}
      </nav>

      {phase === "describe" ? (
        <section className="pf-dc-panel pf-tt-composer">
          <div className="pf-tt-composer-title">
            <span className="pf-tt-agent-mark">AI</span>
            <h2>描述任务</h2>
          </div>
          <textarea
            className="pf-tt-textarea"
            rows={5}
            placeholder="时间、物业、业务、区域、负责人…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <div className="pf-tt-example-chips">
            {PROMPT_CHIPS.map((chip) => (
              <button
                key={chip.label}
                type="button"
                className="pf-tt-example-chip"
                title={chip.text}
                onClick={() => setDescription(chip.text)}
              >
                {chip.label}
              </button>
            ))}
          </div>
          <div className="pf-tt-composer-foot">
            <button
              type="button"
              className="pf-btn pf-tt-btn-primary"
              disabled={agentLoading}
              onClick={() => void handleGenerate()}
            >
              {agentLoading ? (
                <>
                  <span className="pf-tt-spinner" aria-hidden />
                  编排中…
                </>
              ) : (
                "生成草案"
              )}
            </button>
          </div>
        </section>
      ) : null}

      {flow && phase !== "describe" ? (
        <>
          <section className="pf-dc-panel pf-tt-flow-panel">
            <div className="pf-tt-flow-head">
              <h2>{flow.title}</h2>
              <span className="pf-tt-flow-meta">{flow.summary}</span>
            </div>
            <ol className="pf-tt-pipeline">
              {flow.steps.map((step, index) => (
                <li
                  key={step.id}
                  className={`pf-tt-pipeline-step${
                    phase === "configure" && index === 0 ? " is-current" : ""
                  }${phase === "running" || phase === "done" ? " is-done" : ""}`}
                  title={step.desc || undefined}
                >
                  <span className="pf-tt-pipeline-index">{index + 1}</span>
                  <strong className="pf-tt-pipeline-label">{step.title}</strong>
                </li>
              ))}
            </ol>
          </section>

          {phase === "configure" ? (
            <div className="pf-tt-config-layout">
              <section className="pf-dc-panel pf-tt-config-card">
                <header className="pf-tt-config-card-head">
                  <span className="pf-tt-config-icon">◷</span>
                  <h2>时间</h2>
                </header>
                <div className="pf-tt-field-grid pf-tt-field-grid-time">
                  <label className="pf-tt-field pf-tt-field-wide">
                    <span>物业项目</span>
                    <select
                      value={config.propertyId}
                      onChange={(e) => updateConfig({ propertyId: e.target.value })}
                    >
                      {DEMO_PROPERTIES.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="pf-tt-field">
                    <span>执行日期</span>
                    <input
                      type="date"
                      value={config.scheduleDate}
                      onChange={(e) => updateConfig({ scheduleDate: e.target.value })}
                    />
                  </label>
                  <label className="pf-tt-field">
                    <span>开始</span>
                    <input
                      type="time"
                      value={config.scheduleStart}
                      onChange={(e) => updateConfig({ scheduleStart: e.target.value })}
                    />
                  </label>
                  <label className="pf-tt-field">
                    <span>结束</span>
                    <input
                      type="time"
                      value={config.scheduleEnd}
                      onChange={(e) => updateConfig({ scheduleEnd: e.target.value })}
                    />
                  </label>
                </div>
              </section>

              <section className="pf-dc-panel pf-tt-config-card">
                <header className="pf-tt-config-card-head">
                  <span className="pf-tt-config-icon">◉</span>
                  <h2>业务</h2>
                </header>
                <div className="pf-tt-tile-grid">
                  {DEMO_WORKS.map((w) => (
                    <label
                      key={w.id}
                      className={`pf-tt-tile${config.workIds.includes(w.id) ? " is-on" : ""}`}
                    >
                      <input
                        type="checkbox"
                        checked={config.workIds.includes(w.id)}
                        onChange={() => updateConfig({ workIds: toggleId(config.workIds, w.id) })}
                      />
                      <span className="pf-tt-tile-check" aria-hidden />
                      <span className="pf-tt-tile-text">{w.name}</span>
                    </label>
                  ))}
                </div>
              </section>

              <section className="pf-dc-panel pf-tt-config-card">
                <header className="pf-tt-config-card-head">
                  <span className="pf-tt-config-icon">⌖</span>
                  <h2>区域</h2>
                </header>
                <div className="pf-tt-tile-grid pf-tt-tile-grid-compact">
                  {DEMO_REGIONS.map((r) => (
                    <label
                      key={r.id}
                      className={`pf-tt-tile pf-tt-tile-sm${config.regionIds.includes(r.id) ? " is-on" : ""}`}
                    >
                      <input
                        type="checkbox"
                        checked={config.regionIds.includes(r.id)}
                        onChange={() => updateConfig({ regionIds: toggleId(config.regionIds, r.id) })}
                      />
                      <span className="pf-tt-tile-check" aria-hidden />
                      <span className="pf-tt-tile-text">{r.name}</span>
                    </label>
                  ))}
                </div>
              </section>

              <section className="pf-dc-panel pf-tt-config-card">
                <header className="pf-tt-config-card-head">
                  <span className="pf-tt-config-icon">人</span>
                  <h2>负责人</h2>
                </header>
                <div className="pf-tt-owner-grid">
                  {DEMO_OWNERS.map((o) => (
                    <label
                      key={o.id}
                      className={`pf-tt-owner-tile${config.ownerIds.includes(o.id) ? " is-on" : ""}`}
                    >
                      <input
                        type="checkbox"
                        checked={config.ownerIds.includes(o.id)}
                        onChange={() => updateConfig({ ownerIds: toggleId(config.ownerIds, o.id) })}
                      />
                      <span className="pf-tt-owner-avatar" aria-hidden>
                        {ownerInitial(o.name)}
                      </span>
                      <span className="pf-tt-owner-info">
                        <strong>{o.name}</strong>
                      </span>
                    </label>
                  ))}
                </div>
              </section>

              <section className="pf-dc-panel pf-tt-launch-bar">
                <span className="pf-tt-flow-meta">{flow.summary}</span>
                <button type="button" className="pf-btn pf-tt-btn-primary" onClick={() => void handleLaunch()}>
                  触发任务
                </button>
              </section>
            </div>
          ) : null}

          {(phase === "running" || phase === "done") && (
            <div className="pf-tt-run-layout">
              <section className="pf-dc-panel pf-tt-progress-hero">
                <div className="pf-tt-progress-hero-top">
                  <div>
                    <h2>任务进度</h2>
                    <p>
                      {propertyName} · {config.scheduleDate} · {config.scheduleStart}–{config.scheduleEnd}
                    </p>
                  </div>
                  <Badge tone={phase === "done" ? "success" : "info"}>
                    {phase === "done" ? "已完成" : "执行中"}
                  </Badge>
                </div>
                <div
                  className="pf-tt-progress-track"
                  role="progressbar"
                  aria-valuenow={progress}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div className="pf-tt-progress-fill" style={{ width: `${progress}%` }} />
                </div>
                <div className="pf-tt-progress-foot">
                  <strong>{progress}%</strong>
                  <span>
                    {dispatch.filter((d) => d.status === "done").length}/{dispatch.length} 完成
                  </span>
                </div>
              </section>

              <section className="pf-dc-panel pf-tt-run-card">
                <h2>工作分发</h2>
                <ul className="pf-tt-dispatch-list">
                  {dispatch.map((row) => (
                    <li key={row.id} className={`pf-tt-dispatch-row is-${row.status}`}>
                      <div className="pf-tt-dispatch-meta">
                        <strong>{row.workName}</strong>
                        <span>
                          {row.regionName} · {row.ownerName}
                        </span>
                      </div>
                      <div className="pf-tt-dispatch-progress">
                        <div className="pf-tt-dispatch-track">
                          <span style={{ width: `${row.progress}%` }} />
                        </div>
                        <em>{row.progress}%</em>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>

              <section className="pf-dc-panel pf-tt-run-card">
                <h2>工作处理</h2>
                <ul className="pf-tt-process-list">
                  {process.map((row) => (
                    <li key={row.id} className="pf-tt-process-row">
                      <div>
                        <strong>{row.title}</strong>
                        <span>
                          {row.ownerName} · {row.updatedAt}
                        </span>
                      </div>
                      <Badge
                        tone={
                          row.status === "resolved"
                            ? "success"
                            : row.status === "processing"
                              ? "warning"
                              : "default"
                        }
                      >
                        {row.status === "resolved"
                          ? "已处置"
                          : row.status === "processing"
                            ? "处理中"
                            : "排队"}
                      </Badge>
                    </li>
                  ))}
                </ul>
              </section>

              <section className={`pf-dc-panel pf-tt-report-card${reportReady ? " is-ready" : ""}`}>
                <div className="pf-tt-report-icon" aria-hidden>
                  ⊞
                </div>
                <div className="pf-tt-report-body">
                  <h2>报告</h2>
                  {reportReady ? (
                    <div className="pf-tt-report-actions">
                      <Link to="/user/reports" className="pf-btn pf-tt-btn-primary">
                        查看报告
                      </Link>
                      <button type="button" className="pf-btn pf-btn-sm pf-tt-btn-ghost" onClick={() => setPhase("configure")}>
                        改配置
                      </button>
                    </div>
                  ) : (
                    <p className="pf-tt-report-wait">完成后生成</p>
                  )}
                </div>
              </section>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
