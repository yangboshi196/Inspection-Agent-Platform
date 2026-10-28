import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

type Props = {
  /** Markdown 源码 */
  source: string;
  className?: string;
};

/** 聊天区 Markdown 渲染（GFM + 单换行转硬换行，链接新窗口打开） */
export function MarkdownBody({ source, className = "markdown-body" }: Props) {
  const text = source.trim() || "…";
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks]}
        components={{
          a: (props) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
