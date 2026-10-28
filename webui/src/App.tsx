import { useCallback, useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { chatMarkdownSource, isAbortError, prettifyModelOutput } from "./chatFormat";
import { MarkdownBody } from "./MarkdownBody";
import { StreamCardPanel } from "./StreamCard";
import { DocumentLibraryPage } from "./DocumentLibraryPage";
import { SpecWorkflowDemoPage } from "./SpecWorkflowDemoPage";
import { RegionDetailPage } from "./platform/admin/RegionDetailPage";
import { RegionConfigPage } from "./platform/admin/RegionConfigPage";
import { KnowledgePage } from "./platform/admin/KnowledgePage";
import { PermissionConfigPage } from "./platform/admin/PermissionConfigPage";
import { LogManagementPage } from "./platform/admin/LogManagementPage";
import { AlgorithmPage } from "./platform/admin/AlgorithmPage";
import { ReportManagementPage } from "./platform/admin/ReportManagementPage";
import { InspectionWorkStudioPage } from "./platform/admin/InspectionWorkStudioPage";
import { HermesAgentPage } from "./platform/admin/HermesAgentPage";
import { DataCenterDashboardPage } from "./platform/dataCenter/DataCenterDashboardPage";
import { DataCenterWorksPage } from "./platform/dataCenter/DataCenterWorksPage";
import { DataCenterReportsPage } from "./platform/dataCenter/DataCenterReportsPage";
import { DataCenterEventsPage } from "./platform/dataCenter/DataCenterEventsPage";
import { SmartAssistantPage } from "./platform/dataCenter/SmartAssistantPage";
import { PortalEntryPage } from "./platform/PortalEntryPage";
import { LoginPage } from "./platform/LoginPage";
import { RequireAuth } from "./platform/RequireAuth";
import { RequirePermission } from "./platform/RequirePermission";
import { PermissionDeniedPage } from "./platform/PermissionDeniedPage";
import { useAuth } from "./platform/AuthContext";
import { UserLayout } from "./platform/UserLayout";
import { AdminLayout } from "./platform/AdminLayout";
import { apiBase, apiFetch } from "./api";

type ChatBubble =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string }
  | { kind: "meta"; text: string }
  | {
      kind: "think";
      text: string;
      step: number;
      agent?: Record<string, unknown>;
    }
  | {
      kind: "tool";
      id: string;
      label: string;
      done: boolean;
      ok?: boolean;
      card?: Record<string, unknown>;
      agent?: Record<string, unknown>;
    };

const SESSION_KEY = "SIA_session";

function withPerm(perm: string, element: JSX.Element) {
  return <RequirePermission perm={perm}>{element}</RequirePermission>;
}

/** 智能助手：与看板同权，避免旧账号缺 p-trigger-task 无法访问 */
function SmartAssistantRoute() {
  const { hasPermission, loading, isAuthenticated } = useAuth();
  if (loading) return <div className="pf-usr-status">正在验证权限…</div>;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  if (!hasPermission("p-trigger-task") && !hasPermission("p-dash")) {
    return <PermissionDeniedPage />;
  }
  return <SmartAssistantPage />;
}

async function parseSseStream(
  body: ReadableStream<Uint8Array> | null,
  onEvent: (obj: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (!body) return;
  const reader = body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (signal?.aborted) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() || "";
    for (const block of parts) {
      const line = block.trim();
      if (!line.startsWith("data:")) continue;
      const json = line.slice(5).trim();
      try {
        onEvent(JSON.parse(json) as Record<string, unknown>);
      } catch {
        /* ignore */
      }
    }
  }
}

function BubbleView({ b }: { b: ChatBubble }) {
  if (b.kind === "tool") {
    const icon = b.done ? (b.ok ? "✓" : "✗") : "⋯";
    const cls = b.done ? (b.ok ? "tool-ok" : "tool-fail") : "tool-run";
    const ag = b.agent;
    const agLabel = ag && typeof ag.label === "string" ? ag.label : "";
    const agHint = ag && typeof ag.hint === "string" ? ag.hint : "";
    return (
      <div className={`bubble tool ${cls}`}>
        <div className="tool-row">
          <span className="tool-icon">{icon}</span>
          <span className="tool-label">{b.label}</span>
          {!b.done && <span className="tool-hint">执行中</span>}
        </div>
        {agLabel ? (
          <div className="tool-agent-lane">
            <span className="tool-agent-badge">{agLabel}</span>
            {agHint ? <span className="tool-agent-hint">{agHint}</span> : null}
          </div>
        ) : null}
        {b.done && b.card != null && (
          <div className="tool-card-slot">
            <StreamCardPanel card={b.card} />
          </div>
        )}
      </div>
    );
  }
  if (b.kind === "think") {
    const ma = b.agent;
    const mainLabel = ma && typeof ma.label === "string" ? ma.label : "";
    const mainRole = ma && typeof ma.role === "string" ? ma.role : "";
    return (
      <details className="bubble think think-details">
        <summary className="think-summary">
          {mainLabel ? <span className="think-main-tag">{mainLabel}</span> : null}
          推理 · 第 {b.step + 1} 步
          {mainRole ? <span className="think-role"> · {mainRole}</span> : null}
          <span className="think-summary-hint">（点击展开原文）</span>
        </summary>
        <div className="think-body">
          <MarkdownBody source={chatMarkdownSource(b.text || "")} />
        </div>
      </details>
    );
  }
  if (b.kind === "assistant") {
    return (
      <div className="bubble assistant">
        <MarkdownBody source={chatMarkdownSource(b.text)} />
      </div>
    );
  }
  if (b.kind === "user") {
    return (
      <div className="bubble user">
        <MarkdownBody source={chatMarkdownSource(b.text)} />
      </div>
    );
  }
  return <div className={`bubble ${b.kind}`}>{b.text}</div>;
}

function ChatPage() {
  const [sessionId, setSessionId] = useState("");
  const [input, setInput] = useState("");
  const [bubbles, setBubbles] = useState<ChatBubble[]>([]);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let sid = localStorage.getItem(SESSION_KEY);
    if (!sid) {
      sid =
        typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : `s-${Date.now()}`;
      localStorage.setItem(SESSION_KEY, sid);
    }
    setSessionId(sid);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [bubbles, loading]);

  const finalizeThinkStep = useCallback((step: number) => {
    setBubbles((b) => {
      const next = [...b];
      for (let i = next.length - 1; i >= 0; i--) {
        const x = next[i];
        if (x.kind === "think" && x.step === step) {
          next[i] = { ...x, text: prettifyModelOutput(x.text) };
          return next;
        }
      }
      return next;
    });
  }, []);

  const stopGeneration = () => {
    abortRef.current?.abort();
  };

  const send = async () => {
    const text = input.trim();
    if (!text || !sessionId || loading) return;
    setInput("");
    setBubbles((b) => [...b, { kind: "user", text }]);
    setLoading(true);
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    const signal = abortRef.current.signal;

    try {
      const res = await apiFetch(`${apiBase()}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message: text,
        }),
        signal,
      });
      if (!res.ok) {
        setBubbles((b) => [...b, { kind: "meta", text: `请求失败：HTTP ${res.status}` }]);
        return;
      }
      await parseSseStream(
        res.body,
        (ev) => {
          const t = ev.type;

          if (t === "reasoning_start" && typeof ev.step === "number") {
            const step = ev.step as number;
            const agent = ev.agent as Record<string, unknown> | undefined;
            setBubbles((b) => [...b, { kind: "think", text: "", step, agent }]);
          }

          if (t === "thinking_delta" && typeof ev.text === "string" && typeof ev.step === "number") {
            const step = ev.step as number;
            const chunk = ev.text as string;
            setBubbles((b) => {
              const next = [...b];
              for (let i = next.length - 1; i >= 0; i--) {
                const x = next[i];
                if (x.kind === "think" && x.step === step) {
                  next[i] = { ...x, text: x.text + chunk };
                  return next;
                }
              }
              return next;
            });
          }

          if (t === "reasoning_end" && typeof ev.step === "number") {
            finalizeThinkStep(ev.step as number);
          }

          if (t === "delta" && typeof ev.text === "string") {
            setBubbles((b) => [...b, { kind: "assistant", text: ev.text as string }]);
          }

          if (t === "tool_start") {
            const tool = ev.tool as
              | {
                  name?: string;
                  label?: string;
                  tool_call_id?: string;
                  agent?: Record<string, unknown>;
                }
              | undefined;
            const id = tool?.tool_call_id || `t-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
            const label = tool?.label || tool?.name || "工具";
            const agent = tool?.agent;
            setBubbles((b) => [...b, { kind: "tool", id, label, done: false, agent }]);
          }

          if (t === "tool_end") {
            const tool = ev.tool as {
              tool_call_id?: string;
              label?: string;
              name?: string;
              ok?: boolean;
              agent?: Record<string, unknown>;
            } | undefined;
            const id = tool?.tool_call_id;
            const ok = tool?.ok;
            const endAgent = tool?.agent;
            setBubbles((b) => {
              const next = [...b];
              const card = ev.card as Record<string, unknown> | undefined;
              for (let i = next.length - 1; i >= 0; i--) {
                const x = next[i];
                if (x.kind === "tool" && (!id || x.id === id)) {
                  if (!x.done) {
                    next[i] = {
                      ...x,
                      done: true,
                      ok,
                      card,
                      agent: x.agent ?? endAgent,
                    };
                    break;
                  }
                }
              }
              return next;
            });
          }

          if (t === "error") {
            setBubbles((b) => [
              ...b,
              { kind: "meta", text: `错误：${String(ev.error || ev.message || "")}` },
            ]);
          }
        },
        signal,
      );
    } catch (e: unknown) {
      if (isAbortError(e)) {
        setBubbles((b) => [...b, { kind: "meta", text: "已停止生成" }]);
        return;
      }
      setBubbles((b) => [...b, { kind: "meta", text: `网络异常：${String(e)}` }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="main main-chat-only">
      <div className="toolbar">
        <span className="toolbar-meta">会话 {sessionId ? sessionId.slice(0, 8) : "…"}…</span>
      </div>

      <div className="workspace-chat workspace-chat-full">
        <div className="chat">
          <div className="chat-inner">
            {bubbles.length === 0 && (
              <div className="bubble meta">与助手对话；当前为通用 ReAct 骨架（未注册平台工具时可纯对话）。</div>
            )}
            {bubbles.map((b, i) => (
              <BubbleView key={i} b={b} />
            ))}
            {loading && (
              <div className="bubble meta chat-loading-hint">生成中… 可随时点「停止」中断。</div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="input-row">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入消息…"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <button type="button" disabled={loading} onClick={() => void send()}>
            发送
          </button>
          <button type="button" className="btn-stop" disabled={!loading} onClick={stopGeneration}>
            停止
          </button>
        </div>
      </div>
    </div>
  );
}

function AdminRegionRedirect() {
  const { regionId } = useParams();
  const q = regionId ? `?region=${encodeURIComponent(regionId)}` : "";
  return <Navigate to={`/admin/regions${q}`} replace />;
}

function HermesLegacyRedirect() {
  const { tab } = useParams<{ tab?: string }>();
  const safeTab = tab || "sessions";
  return <Navigate to={`/admin/hermes-agent/${encodeURIComponent(safeTab)}`} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/portal"
        element={
          <RequireAuth>
            <PortalEntryPage />
          </RequireAuth>
        }
      />
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="/hermes-agent" element={<Navigate to="/admin/hermes-agent/sessions" replace />} />
      <Route path="/hermes-agent/:tab" element={<HermesLegacyRedirect />} />

      <Route path="/user" element={<RequireAuth><UserLayout /></RequireAuth>}>
        <Route index element={<Navigate to="dashboard" replace />} />
        <Route path="dashboard" element={withPerm("p-dash", <DataCenterDashboardPage />)} />
        <Route path="assistant" element={<SmartAssistantRoute />} />
        <Route path="trigger-tasks" element={<Navigate to="/user/assistant" replace />} />
        <Route path="reports" element={withPerm("p-reports", <DataCenterReportsPage />)} />
        <Route path="report-plans" element={<Navigate to="/user/reports" replace />} />
        <Route path="events" element={withPerm("p-events", <DataCenterEventsPage />)} />
        <Route path="works" element={withPerm("p-inspection-view", <DataCenterWorksPage />)} />
        <Route path="status" element={<Navigate to="/user/works" replace />} />
      </Route>

      <Route element={<RequireAuth><AdminLayout /></RequireAuth>}>
        <Route path="/admin/inspection-works" element={withPerm("p-inspection", <InspectionWorkStudioPage />)} />
        <Route path="/admin/regions/new" element={withPerm("p-device", <RegionDetailPage />)} />
        <Route path="/admin/regions/:regionId/edit" element={withPerm("p-device", <RegionDetailPage />)} />
        <Route path="/admin/regions" element={withPerm("p-device", <RegionConfigPage />)} />
        <Route path="/admin/devices" element={<Navigate to="/admin/regions" replace />} />
        <Route path="/admin/regions/:regionId/*" element={<AdminRegionRedirect />} />
        <Route path="/admin/knowledge" element={withPerm("p-knowledge", <KnowledgePage />)} />
        <Route path="/admin/algorithms" element={withPerm("p-algo", <AlgorithmPage />)} />
        <Route path="/admin/reports" element={withPerm("p-reports", <ReportManagementPage />)} />
        <Route path="/admin/permissions" element={withPerm("p-perm", <PermissionConfigPage />)} />
        <Route path="/admin/logs" element={withPerm("p-logs", <LogManagementPage />)} />
        <Route path="/admin/hermes-agent" element={<Navigate to="/admin/hermes-agent/sessions" replace />} />
        <Route path="/admin/hermes-agent/:tab" element={withPerm("p-perm", <HermesAgentPage />)} />
        <Route path="/chat" element={withPerm("p-workflow", <ChatPage />)} />
        <Route path="/docs" element={withPerm("p-docs", <DocumentLibraryPage />)} />
        <Route path="/workflow" element={withPerm("p-workflow", <SpecWorkflowDemoPage />)} />
      </Route>

      <Route path="/data-center/*" element={<Navigate to="/user/dashboard" replace />} />
    </Routes>
  );
}
