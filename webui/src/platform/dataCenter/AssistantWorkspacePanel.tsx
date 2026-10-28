import type { AssistantToolCard } from "./useHermesGateway";

export function AssistantWorkspacePanel({ tools }: { tools: AssistantToolCard[] }) {
  return (
    <aside className="sa-workspace" aria-label="智能体工作区">
      <div className="sa-workspace-head">
        <h2>智能体工作区</h2>
        <p className="sa-workspace-sub">Skill 与 MCP 工具的结构化输出</p>
      </div>
      <div className="sa-workspace-cards">
        {tools.length === 0 ? (
          <p className="sa-muted sa-workspace-empty">
            工具调用结果将显示为卡片：知识库入库、巡检草案、事件列表等。
          </p>
        ) : (
          tools.map((tool) => (
            <article
              key={tool.id}
              className={`sa-tool-card sa-tool-card--${tool.status}`}
            >
              <header className="sa-tool-card-head">
                <span className="sa-tool-card-icon">
                  {tool.status === "running" ? "◌" : tool.status === "error" ? "✕" : "✓"}
                </span>
                <h3>{tool.label}</h3>
              </header>
              {tool.context ? (
                <p className="sa-tool-card-ctx">{tool.context}</p>
              ) : null}
              {tool.summary ? (
                <pre className="sa-tool-card-body">{tool.summary}</pre>
              ) : tool.status === "running" ? (
                <p className="sa-tool-card-run">执行中…</p>
              ) : null}
            </article>
          ))
        )}
      </div>
    </aside>
  );
}
