import { useCallback, useEffect, useRef, useState } from "react";
import { GatewayClient, type GatewayEvent } from "@hermes/lib/gatewayClient";

export type ChatLine = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
};

export type AssistantToolCard = {
  id: string;
  name: string;
  label: string;
  status: "running" | "done" | "error";
  context?: string;
  summary?: string;
};

export type WorkflowStep = {
  id: string;
  label: string;
  status: "running" | "done" | "error";
};

const TOOL_LABELS: Record<string, string> = {
  skill_view: "加载 Skill 流程",
  clarify: "澄清需求",
  terminal: "终端执行",
  SIA_list_documents: "浏览文档库",
  SIA_ingest_knowledge: "知识库向量化",
  SIA_query_knowledge: "检索知识库",
  SIA_generate_inspection_work: "生成巡检草案",
  SIA_list_inspection_works: "查询巡检业务",
  SIA_create_inspection_work: "创建巡检业务",
  SIA_patch_inspection_work: "更新巡检业务",
  SIA_list_inspection_events: "查询巡检事件",
  SIA_patch_inspection_event: "更新事件",
};

function toolLabel(name: string, context?: string): string {
  if (TOOL_LABELS[name]) return TOOL_LABELS[name];
  if (name === "skill_view" && context) return `Skill：${context.slice(0, 48)}`;
  return name;
}

type ResumeResponse = {
  session_id: string;
  resumed?: string;
  messages?: Array<{ role?: string; content?: string; text?: string }>;
};

function mapHistoryMessages(
  messages: ResumeResponse["messages"],
): ChatLine[] {
  if (!messages?.length) return [];
  return messages.map((m, i) => ({
    id: `hist-${i}`,
    role: (m.role === "user" ? "user" : "assistant") as ChatLine["role"],
    text: String(m.content ?? m.text ?? ""),
  }));
}

export function useHermesGateway(ready: boolean) {
  const gwRef = useRef<GatewayClient | null>(null);
  const [connected, setConnected] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [gwSessionId, setGwSessionId] = useState<string | null>(null);
  const [dbSessionId, setDbSessionId] = useState<string | null>(null);
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [tools, setTools] = useState<AssistantToolCard[]>([]);
  const [workflowSteps, setWorkflowSteps] = useState<WorkflowStep[]>([]);
  const [statusLine, setStatusLine] = useState("等待对话开始…");
  const [busy, setBusy] = useState(false);
  const assistantDraftRef = useRef<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    const gw = new GatewayClient();
    gwRef.current = gw;

    const onDelta = (ev: GatewayEvent<{ text?: string }>) => {
      const chunk = ev.payload?.text ?? "";
      if (!chunk) return;
      setLines((prev) => {
        const draftId = assistantDraftRef.current;
        if (!draftId) return prev;
        return prev.map((l) =>
          l.id === draftId ? { ...l, text: l.text + chunk } : l,
        );
      });
    };

    const onMessageStart = () => {
      const id = `a-${Date.now()}`;
      assistantDraftRef.current = id;
      setLines((prev) => [...prev, { id, role: "assistant", text: "" }]);
    };

    const onMessageComplete = () => {
      assistantDraftRef.current = null;
      setBusy(false);
      setStatusLine("等待输入…");
    };

    const onToolStart = (ev: GatewayEvent<{ tool_id?: string; name?: string; context?: string }>) => {
      const id = ev.payload?.tool_id ?? `tool-${Date.now()}`;
      const name = ev.payload?.name ?? "tool";
      const context = ev.payload?.context;
      const label = toolLabel(name, context);
      setStatusLine(`${label}…`);
      setTools((prev) => [
        ...prev,
        { id, name, label, status: "running", context },
      ]);
      setWorkflowSteps((prev) => [
        ...prev,
        { id, label, status: "running" },
      ]);
    };

    const onToolComplete = (ev: GatewayEvent<{ tool_id?: string; name?: string; summary?: string }>) => {
      const id = ev.payload?.tool_id;
      const name = ev.payload?.name ?? "tool";
      const summary = ev.payload?.summary;
      const label = toolLabel(name);
      setTools((prev) =>
        prev.map((t) =>
          t.id === id || (!id && t.status === "running")
            ? { ...t, status: "done", summary: summary ?? t.summary }
            : t,
        ),
      );
      setWorkflowSteps((prev) =>
        prev.map((s) =>
          s.id === id || (!id && s.status === "running")
            ? { ...s, status: "done" }
            : s,
        ),
      );
      setStatusLine(`已完成：${label}`);
    };

    const onStatus = (ev: GatewayEvent<{ text?: string; kind?: string }>) => {
      const text = ev.payload?.text?.trim();
      if (text) setStatusLine(text);
    };

    const onError = (ev: GatewayEvent<{ message?: string }>) => {
      const msg = ev.payload?.message;
      if (msg) {
        setStatusLine(msg);
        setBusy(false);
      }
    };

    gw.on("message.delta", onDelta);
    gw.on("message.start", onMessageStart);
    gw.on("message.complete", onMessageComplete);
    gw.on("tool.start", onToolStart);
    gw.on("tool.complete", onToolComplete);
    gw.on("status.update", onStatus);
    gw.on("error", onError);

    gw.onState(setConnected);
    gw
      .connect()
      .then(() => setConnectError(null))
      .catch((e: Error) => {
        setConnectError(e.message);
        setConnected(false);
      });

    return () => {
      gw.close();
      gwRef.current = null;
    };
  }, [ready]);

  const createSession = useCallback(async () => {
    const gw = gwRef.current;
    if (!gw || !connected) throw new Error("助手服务未连接");
    const r = await gw.request<{ session_id: string }>("session.create", { cols: 100 });
    setGwSessionId(r.session_id);
    setDbSessionId(null);
    setLines([]);
    setTools([]);
    setWorkflowSteps([]);
    setStatusLine("新对话已就绪，请输入需求。");
    return r.session_id;
  }, [connected]);

  const resumeSession = useCallback(
    async (targetDbId: string) => {
      const gw = gwRef.current;
      if (!gw || !connected) throw new Error("助手服务未连接");
      const r = await gw.request<ResumeResponse>("session.resume", {
        session_id: targetDbId,
        cols: 100,
      });
      setGwSessionId(r.session_id);
      setDbSessionId(r.resumed ?? targetDbId);
      setLines(mapHistoryMessages(r.messages));
      setTools([]);
      setWorkflowSteps([]);
      setStatusLine("已恢复历史会话，可继续对话。");
      return r;
    },
    [connected],
  );

  const submit = useCallback(
    async (text: string) => {
      const gw = gwRef.current;
      let sid = gwSessionId;
      if (!gw) throw new Error("助手服务未连接");
      if (!sid) {
        const created = await gw.request<{ session_id: string }>("session.create", { cols: 100 });
        sid = created.session_id;
        setGwSessionId(sid);
      }
      const trimmed = text.trim();
      if (!trimmed) return;
      setLines((prev) => [
        ...prev,
        { id: `u-${Date.now()}`, role: "user", text: trimmed },
      ]);
      setBusy(true);
      setStatusLine("助手思考中…");
      await gw.request("prompt.submit", { session_id: sid, text: trimmed });
    },
    [gwSessionId],
  );

  const interrupt = useCallback(async () => {
    const gw = gwRef.current;
    const sid = gwSessionId;
    if (!gw || !sid) return;
    try {
      await gw.request("session.interrupt", { session_id: sid });
    } finally {
      setBusy(false);
      setStatusLine("已停止生成");
    }
  }, [gwSessionId]);

  return {
    connected,
    connectError,
    gwSessionId,
    dbSessionId,
    lines,
    tools,
    workflowSteps,
    statusLine,
    busy,
    createSession,
    resumeSession,
    submit,
    interrupt,
  };
}
