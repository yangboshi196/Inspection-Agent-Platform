import { useEffect, useRef, useState } from "react";
import { chatMarkdownSource } from "../../chatFormat";
import { MarkdownBody } from "../../MarkdownBody";
import type { ChatLine, WorkflowStep } from "./useHermesGateway";

type Props = {
  lines: ChatLine[];
  statusLine: string;
  workflowSteps: WorkflowStep[];
  connected: boolean;
  busy: boolean;
  onSend: (text: string) => Promise<void>;
  onStop: () => void;
  onUploadClick: () => void;
  uploading: boolean;
};

export function AssistantChatPanel({
  lines,
  statusLine,
  workflowSteps,
  connected,
  busy,
  onSend,
  onStop,
  onUploadClick,
  uploading,
}: Props) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines, busy]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    await onSend(text);
  };

  return (
    <section className="sa-center" aria-label="对话">
      <header className="sa-center-head">
        <div>
          <h1>智能巡检助手</h1>
          <p>安全生产智能巡检 · 知识库 · 巡检编排 · 事件处置</p>
        </div>
        <span className={`sa-feed-dot${connected ? " is-live" : ""}`}>
          {connected ? "已连接" : "连接中…"}
        </span>
      </header>

      <div className="sa-workflow">
        <p className="sa-workflow-status">{statusLine}</p>
        {workflowSteps.length > 0 ? (
          <ol className="sa-workflow-list">
            {workflowSteps.map((step) => (
              <li key={step.id} className={`sa-workflow-item sa-workflow-item--${step.status}`}>
                <span className={`sa-step-icon sa-step-icon--${step.status === "running" ? "run" : step.status === "done" ? "done" : step.status === "error" ? "error" : "pending"}`}>
                  {step.status === "done" ? "✓" : step.status === "error" ? "!" : ""}
                </span>
                <span className="sa-workflow-label">{step.label}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="sa-workflow-hint">
            输入巡检或知识库需求；建议首句包含 @skill sia-smart-assistant
          </p>
        )}
      </div>

      <div className="sa-chat-scroll">
        {lines.length === 0 ? (
          <div className="sa-chat-empty">
            <p>描述巡检任务、上传规范文档或查询事件。</p>
            <p className="sa-chat-empty-sub">例如：「周五消防秩序巡检」「将刚上传的文档向量化入库」</p>
          </div>
        ) : (
          lines.map((line) => (
            <div key={line.id} className={`sa-bubble sa-bubble--${line.role}`}>
              {line.role === "assistant" ? (
                <MarkdownBody source={chatMarkdownSource(line.text || (busy ? "…" : ""))} />
              ) : (
                <p>{line.text}</p>
              )}
            </div>
          ))
        )}
        {busy ? (
          <div className="sa-bubble sa-bubble--assistant sa-bubble--typing">
            <span className="sa-typing-dot" />
            <span className="sa-typing-dot" />
            <span className="sa-typing-dot" />
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>

      <div className="sa-composer">
        <textarea
          className="sa-composer-input"
          rows={2}
          placeholder="请输入客户需求、巡检描述或知识库指令…"
          value={input}
          disabled={busy || !connected}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleSend();
            }
          }}
        />
        <div className="sa-composer-actions">
          <button
            type="button"
            className="sa-btn sa-btn-ghost"
            disabled={uploading}
            onClick={onUploadClick}
          >
            {uploading ? "上传中…" : "上传文件"}
          </button>
          {busy ? (
            <button type="button" className="sa-btn sa-btn-ghost" onClick={onStop}>
              停止
            </button>
          ) : (
            <button
              type="button"
              className="sa-btn sa-btn-primary"
              disabled={!connected || !input.trim()}
              onClick={() => void handleSend()}
            >
              发送
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
