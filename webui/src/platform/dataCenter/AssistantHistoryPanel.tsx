import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { timeAgo } from "@hermes/lib/utils";
import {
  deleteHermesSession,
  listHermesSessions,
  type SessionInfo,
} from "./assistantHermesApi";

type Props = {
  activeDbSessionId: string | null;
  onSelectDbSession: (sessionId: string) => void;
  onNewChat: () => void;
  refreshKey?: number;
};

export function AssistantHistoryPanel({
  activeDbSessionId,
  onSelectDbSession,
  onNewChat,
  refreshKey = 0,
}: Props) {
  const [, setSearchParams] = useSearchParams();
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await listHermesSessions(50, 0);
      setSessions(res.sessions ?? []);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const handleSelect = (id: string) => {
    onSelectDbSession(id);
    setSearchParams({ resume: id }, { replace: true });
  };

  const handleNew = () => {
    onNewChat();
    setSearchParams({}, { replace: true });
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteHermesSession(id);
      if (activeDbSessionId === id) handleNew();
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="sa-history-inner">
      <div className="sa-history-head">
        <h2>对话</h2>
        <button type="button" className="sa-btn sa-btn-ghost sa-btn-sm" onClick={() => void load()}>
          刷新
        </button>
      </div>
      <button type="button" className="sa-btn sa-btn-primary sa-new-chat" onClick={handleNew}>
        新对话
      </button>
      {loading ? <p className="sa-muted">加载中…</p> : null}
      {err ? <p className="sa-error">{err}</p> : null}
      <ul className="sa-session-list">
        {sessions.map((s) => {
          const active = activeDbSessionId === s.id;
          const label = s.title?.trim() || s.preview?.trim() || s.id.slice(0, 12);
          return (
            <li key={s.id} className="sa-session-row">
              <button
                type="button"
                className={`sa-session-item${active ? " is-active" : ""}`}
                onClick={() => handleSelect(s.id)}
              >
                <span className="sa-session-title">{label}</span>
                <span className="sa-session-meta">
                  {s.source ? `${s.source} · ` : ""}
                  {timeAgo(s.last_active || s.started_at)}
                </span>
              </button>
              <button
                type="button"
                className="sa-session-del"
                title="删除"
                onClick={() => void handleDelete(s.id)}
              >
                ×
              </button>
            </li>
          );
        })}
      </ul>
      {!loading && !err && sessions.length === 0 ? (
        <p className="sa-muted">暂无历史，点击「新对话」开始。</p>
      ) : null}
    </div>
  );
}
