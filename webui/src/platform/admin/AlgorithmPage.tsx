import { useCallback, useEffect, useMemo, useState } from "react";
import {
  algoStats,
  fuzzyMatchAlgorithm,
  inputTypeLabel,
  type AlgorithmDemoItem,
} from "./algorithmMock";
import {
  apiRowToDemoItem,
  fetchVaioCoreHealth,
  loadAlgorithmDemoItems,
  loadVaioMcpTools,
  registerVaioHermesMcp,
  removeAlgorithm,
  syncAlgorithmsFromVaio,
  updateAlgorithmDesc,
} from "../algorithmApi";
import type { VaioCoreHealth, VaioMcpTool } from "../../api";

export function AlgorithmPage() {
  const [items, setItems] = useState<AlgorithmDemoItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [kw, setKw] = useState("");
  const [hint, setHint] = useState("");
  const [vaioHealth, setVaioHealth] = useState<VaioCoreHealth | null>(null);
  const [mcpTools, setMcpTools] = useState<VaioMcpTool[]>([]);
  const [syncing, setSyncing] = useState(false);

  const reload = useCallback(async () => {
    const list = await loadAlgorithmDemoItems();
    setItems(list);
    setSelectedId((prev) => (prev && list.some((a) => a.id === prev) ? prev : list[0]?.id ?? null));
    return list;
  }, []);

  const refreshVaioStatus = useCallback(async () => {
    try {
      const [health, tools] = await Promise.all([fetchVaioCoreHealth(), loadVaioMcpTools()]);
      setVaioHealth(health);
      setMcpTools(tools);
    } catch (e) {
      setVaioHealth({ ok: false, error: String(e) });
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await Promise.all([reload(), refreshVaioStatus()]);
      } catch (e) {
        if (!cancelled) setHint(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reload, refreshVaioStatus]);

  const stats = algoStats(items);

  const filtered = useMemo(() => {
    const q = kw.trim();
    if (!q) return items;
    return items.filter((a) => fuzzyMatchAlgorithm(a, q));
  }, [items, kw]);

  const selected = items.find((a) => a.id === selectedId) ?? filtered[0] ?? null;

  useEffect(() => {
    if (!selectedId && filtered[0]?.id) setSelectedId(filtered[0].id);
  }, [selectedId, filtered]);

  const onSyncVaio = async () => {
    setSyncing(true);
    setHint("正在从 vaio-analysis-core 同步算法…");
    try {
      const result = await syncAlgorithmsFromVaio();
      await reload();
      await refreshVaioStatus();
      setHint(`已同步 ${result.synced} 个 vaio 算法（核心：${result.core_health}）`);
    } catch (e) {
      setHint(String(e));
    } finally {
      setSyncing(false);
    }
  };

  const onRegisterMcp = async () => {
    setHint("正在写入 Hermes MCP 配置…");
    try {
      const result = await registerVaioHermesMcp();
      setHint(`已注册 vaio_analysis → ${result.config_path}，请重启 Hermes 会话或执行 /reload-mcp`);
    } catch (e) {
      setHint(String(e));
    }
  };

  const updateItem = async (id: string, patch: Partial<AlgorithmDemoItem>) => {
    if (patch.description !== undefined) {
      try {
        const row = await updateAlgorithmDesc(id, patch.description);
        const demo = apiRowToDemoItem(row);
        setItems((list) => list.map((a) => (a.id === id ? { ...a, ...demo } : a)));
        setHint("");
      } catch (e) {
        setHint(String(e));
      }
      return;
    }
    setItems((list) => list.map((a) => (a.id === id ? { ...a, ...patch } : a)));
  };

  const deleteItem = async (item: AlgorithmDemoItem) => {
    if (!window.confirm(`确定删除算法「${item.name}」？`)) return;
    try {
      await removeAlgorithm(item.id);
      setItems((list) => list.filter((a) => a.id !== item.id));
      setSelectedId(null);
      setHint("");
    } catch (e) {
      setHint(String(e));
    }
  };

  const coreBadge = vaioHealth?.ok
    ? `vaio 核心在线 (${vaioHealth.core?.service ?? "ok"})`
    : `vaio 核心离线${vaioHealth?.error ? `：${vaioHealth.error}` : ""}`;

  const statusMsg = loading ? "加载算法目录…" : hint;

  return (
    <div className="pf-scroll pf-algo-page">
      <header className="pf-algo-top-bar">
        <div className="pf-algo-top-left">
          <div className="pf-algo-title-block">
            <span className="pf-algo-title-mark" aria-hidden>⊠</span>
            <h1>算法管理</h1>
          </div>
          <div className="pf-algo-metrics" aria-label="算法统计">
            <span className="pf-algo-metric pf-algo-metric-blue"><strong>{stats.total}</strong><em>算法</em></span>
            <span className="pf-algo-metric pf-algo-metric-purple"><strong>{stats.linkedWorks}</strong><em>关联巡检业务</em></span>
            <span className={`pf-algo-metric ${vaioHealth?.ok ? "pf-algo-metric-blue" : "pf-algo-metric-purple"}`}>
              <strong>{mcpTools.length}</strong><em>MCP 工具</em>
            </span>
          </div>
        </div>
        <div className="pf-algo-header-actions">
          <button type="button" className="pf-btn pf-btn-sm" disabled={syncing} onClick={() => void onSyncVaio()}>
            {syncing ? "同步中…" : "从 vaio 同步"}
          </button>
          <button type="button" className="pf-btn pf-btn-sm" onClick={() => void onRegisterMcp()}>
            注册 Hermes MCP
          </button>
        </div>
      </header>

      <div className="pf-algo-vaio-bar">
        <span className={vaioHealth?.ok ? "pf-algo-vaio-ok" : "pf-algo-vaio-off"}>{coreBadge}</span>
        {vaioHealth?.base_url ? <span className="pf-algo-vaio-url">{vaioHealth.base_url}</span> : null}
      </div>

      {statusMsg ? <div className="pf-algo-status">{statusMsg}</div> : null}

      <div className="pf-algo-layout">
        <section className="pf-panel pf-algo-list-panel">
          <div className="pf-algo-panel-head pf-algo-panel-head-stacked">
            <h2 className="pf-algo-section-title">算法列表 ({filtered.length})</h2>
            <input
              type="search"
              className="pf-cell-input pf-algo-search pf-algo-search-full"
              placeholder="模糊搜索名称、描述、版本、输入类型…"
              value={kw}
              onChange={(e) => setKw(e.target.value)}
            />
          </div>
          <div className="pf-algo-list">
            {filtered.length === 0 ? (
              <p className="pf-algo-list-empty">
                {loading ? "加载中…" : "未找到匹配的算法。请先「从 vaio 同步」"}
              </p>
            ) : (
              filtered.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  className={`pf-algo-list-item${selected?.id === a.id ? " is-active" : ""}`}
                  onClick={() => setSelectedId(a.id)}
                >
                  <div className="pf-algo-list-item-top">
                    <strong>{a.name}</strong>
                    <span className="pf-algo-list-version">{a.version}</span>
                  </div>
                  <p>{a.description.slice(0, 120)}</p>
                  <div className="pf-algo-list-item-meta">
                    <span>{inputTypeLabel(a.inputType)}</span>
                    <span>{a.author}</span>
                    <span>{a.id}</span>
                  </div>
                </button>
              ))
            )}
          </div>
        </section>

        <section className="pf-panel pf-algo-detail-panel">
          {selected ? (
            <div className="pf-algo-detail-body">
              <div className="pf-algo-detail-head">
                <div>
                  <h2>{selected.name}</h2>
                  <p className="pf-algo-detail-id">{selected.id}</p>
                </div>
                <div className="pf-algo-detail-actions">
                  <button
                    type="button"
                    className="pf-btn pf-btn-sm pf-btn-danger"
                    onClick={() => void deleteItem(selected)}
                  >
                    删除
                  </button>
                </div>
              </div>

              <div className="pf-algo-detail-metrics">
                <div className="pf-algo-detail-metric">
                  <span>健康状态</span>
                  <strong>{selected.health}</strong>
                </div>
                <div className="pf-algo-detail-metric">
                  <span>输入类型</span>
                  <strong>{inputTypeLabel(selected.inputType)}</strong>
                </div>
              </div>

              <label className="pf-algo-field">
                <span>算法描述</span>
                <textarea
                  className="pf-cell-textarea pf-algo-textarea"
                  rows={3}
                  defaultValue={selected.description}
                  key={`desc-${selected.id}`}
                  onBlur={(e) => void updateItem(selected.id, { description: e.target.value })}
                />
              </label>

              <dl className="pf-algo-dl">
                <div><dt>版本</dt><dd>{selected.version}</dd></div>
                <div><dt>输入类型</dt><dd>{inputTypeLabel(selected.inputType)}</dd></div>
                <div><dt>来源</dt><dd>{selected.author}</dd></div>
                {selected.id.startsWith("vaio-") ? (
                  <div><dt>vaio 配方 ID</dt><dd>{selected.id.replace(/^vaio-/, "")}</dd></div>
                ) : null}
              </dl>

              <section className="pf-algo-mcp-section">
                <h3 className="pf-algo-section-title">Hermes MCP 工具（vaio_analysis）</h3>
                <p className="pf-algo-mcp-hint">
                  在 Hermes Chat 中启用 toolset <code>mcp-vaio_analysis</code> 后，Agent 可调用下列工具连接 C++ 核心。
                </p>
                <ul className="pf-algo-mcp-list">
                  {mcpTools.map((t) => (
                    <li key={t.name}>
                      <code>{t.hermes_name}</code>
                      <span>{t.description}</span>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          ) : (
            <p className="pf-algo-detail-empty">请选择算法查看详情</p>
          )}
        </section>
      </div>
    </div>
  );
}
