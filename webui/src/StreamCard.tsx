/** tool_end 附带的结构化 card（通用兜底；后续可按 kind 扩展） */

type Card = Record<string, unknown>;

export function StreamCardPanel({ card }: { card: Card }) {
  const kind = String(card.kind || "");

  if (kind === "tool_error") {
    return (
      <div className="ui-card ui-card-error">
        <div className="ui-card-hdr">工具失败</div>
        <div className="ui-card-body">{String(card.message || "")}</div>
      </div>
    );
  }

  return (
    <div className="ui-card ui-card-generic">
      <div className="ui-card-hdr">{kind ? `卡片 · ${kind}` : "卡片"}</div>
      <pre className="ui-card-pre">{JSON.stringify(card, null, 2)}</pre>
    </div>
  );
}
