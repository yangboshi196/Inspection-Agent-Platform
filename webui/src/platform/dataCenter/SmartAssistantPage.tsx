import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { readApiError, uploadDocument } from "../../api";
import { AssistantChatPanel } from "./AssistantChatPanel";
import { AssistantHistoryPanel } from "./AssistantHistoryPanel";
import { AssistantWorkspacePanel } from "./AssistantWorkspacePanel";
import { bootstrapHermesGlobals, useHermesBootstrap } from "./HermesAssistantShell";
import { useHermesGateway } from "./useHermesGateway";

function SmartAssistantApp() {
  const [searchParams] = useSearchParams();
  const resumeId = searchParams.get("resume");
  const gateway = useHermesGateway(true);
  const [historyRefresh, setHistoryRefresh] = useState(0);
  const [toast, setToast] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const resumeAttemptedRef = useRef<string | null>(null);
  const wasBusyRef = useRef(false);

  useEffect(() => {
    if (!gateway.connected || !resumeId) return;
    if (resumeAttemptedRef.current === resumeId) return;
    resumeAttemptedRef.current = resumeId;
    gateway
      .resumeSession(resumeId)
      .catch((e: unknown) => setToast(e instanceof Error ? e.message : String(e)));
  }, [gateway.connected, resumeId, gateway.resumeSession]);

  useEffect(() => {
    if (wasBusyRef.current && !gateway.busy) {
      setHistoryRefresh((k) => k + 1);
    }
    wasBusyRef.current = gateway.busy;
  }, [gateway.busy]);

  const handleNewChat = () => {
    void gateway.createSession().catch((e: unknown) =>
      setToast(e instanceof Error ? e.message : String(e)),
    );
  };

  const handleSelectSession = (id: string) => {
    void gateway.resumeSession(id).catch((e: unknown) =>
      setToast(e instanceof Error ? e.message : String(e)),
    );
  };

  const handleUpload = async (file: File) => {
    setUploading(true);
    setToast(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await uploadDocument(fd);
      if (!res.ok) throw new Error(await readApiError(res));
      const data = (await res.json()) as { id?: string };
      setToast(
        data.id
          ? `上传成功 document_id=${data.id}，可发送「将向量化入库 document_id ${data.id}」`
          : "上传成功",
      );
    } catch (e) {
      setToast(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div className="sa-app">
      <aside className="sa-rail" aria-label="导航与历史">
        <div className="sa-rail-brand">
          <span className="sa-rail-logo" aria-hidden>智</span>
          <div>
            <strong>智能巡检助手</strong>
            <span className="sa-rail-sub">南京物盟信息技术有限公司</span>
          </div>
        </div>
        <nav className="sa-rail-nav" aria-label="功能">
          <span className="sa-rail-nav-item is-active">
            <span className="sa-rail-nav-icon" aria-hidden>💬</span>
            对话中
          </span>
          <Link className="sa-rail-nav-item" to="/docs">
            <span className="sa-rail-nav-icon" aria-hidden>📚</span>
            知识库
          </Link>
        </nav>
        <div className="sa-rail-history">
          <AssistantHistoryPanel
            activeDbSessionId={gateway.dbSessionId}
            onSelectDbSession={handleSelectSession}
            onNewChat={handleNewChat}
            refreshKey={historyRefresh}
          />
        </div>
      </aside>

      <AssistantChatPanel
        lines={gateway.lines}
        statusLine={gateway.statusLine}
        workflowSteps={gateway.workflowSteps}
        connected={gateway.connected}
        busy={gateway.busy}
        onSend={gateway.submit}
        onStop={() => void gateway.interrupt()}
        onUploadClick={() => fileRef.current?.click()}
        uploading={uploading}
      />

      <AssistantWorkspacePanel tools={gateway.tools} />

      <input
        ref={fileRef}
        type="file"
        className="sa-upload-input"
        accept=".pdf,.doc,.docx,.txt,.md,.xlsx,.xls,.ppt,.pptx"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void handleUpload(f);
        }}
      />

      {gateway.connectError ? (
        <p className="sa-global-error">助手服务连接失败：{gateway.connectError}</p>
      ) : null}
      {toast ? <p className="sa-toast sa-toast-float">{toast}</p> : null}
    </div>
  );
}

export function SmartAssistantPage() {
  const { ready, err } = useHermesBootstrap();

  if (err) {
    return <div className="sa-status sa-error">助手初始化失败：{err}</div>;
  }
  if (!ready) {
    return <div className="sa-status">正在连接智能巡检助手…</div>;
  }

  return <SmartAssistantApp />;
}

/** 启动前同步注入 Hermes 前缀（供 REST / WS 使用）。 */
export async function ensureHermesAssistantReady() {
  await bootstrapHermesGlobals();
}
