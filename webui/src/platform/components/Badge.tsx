type Tone = "default" | "success" | "warning" | "error" | "info" | "draft";

const TONE_CLASS: Record<Tone, string> = {
  default: "pf-badge-default",
  success: "pf-badge-success",
  warning: "pf-badge-warning",
  error: "pf-badge-error",
  info: "pf-badge-info",
  draft: "pf-badge-draft",
};

export function Badge({ children, tone = "default" }: { children: string; tone?: Tone }) {
  return <span className={`pf-badge ${TONE_CLASS[tone]}`}>{children}</span>;
}

export function handleStatusTone(status: string): Tone {
  switch (status) {
    case "resolved":
      return "success";
    case "processing":
      return "info";
    case "ignored":
      return "default";
    default:
      return "warning";
  }
}
