import type { ReactNode } from "react";

export type ConfirmDialogProps = {
  open: boolean;
  title: string;
  description: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  loading?: boolean;
  showDismiss?: boolean;
  dismissLabel?: string;
  dismissChecked?: boolean;
  onDismissChange?: (checked: boolean) => void;
  onConfirm: () => void;
  onCancel: () => void;
};

/** 操作确认弹窗（与平台统一风格：标题 + 说明 + 底栏按钮） */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "确定",
  cancelLabel = "取消",
  danger = false,
  loading = false,
  showDismiss = false,
  dismissLabel = "不再提示",
  dismissChecked = false,
  onDismissChange,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null;

  return (
    <div className="pf-modal-backdrop" onClick={onCancel} role="presentation">
      <div
        className="pf-modal pf-confirm-dialog"
        onClick={(e) => e.stopPropagation()}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="pf-confirm-title"
        aria-describedby="pf-confirm-desc"
      >
        <div className="pf-confirm-dialog-body">
          <h2 id="pf-confirm-title" className="pf-confirm-dialog-title">
            {title}
          </h2>
          <div id="pf-confirm-desc" className="pf-confirm-dialog-desc">
            {description}
          </div>
        </div>
        <footer className="pf-confirm-dialog-footer">
          {showDismiss ? (
            <label className="pf-confirm-dialog-dismiss">
              <input
                type="checkbox"
                checked={dismissChecked}
                onChange={(e) => onDismissChange?.(e.target.checked)}
              />
              <span>{dismissLabel}</span>
            </label>
          ) : (
            <span />
          )}
          <div className="pf-confirm-dialog-actions">
            <button type="button" className="pf-confirm-btn pf-confirm-btn-cancel" onClick={onCancel} disabled={loading}>
              {cancelLabel}
            </button>
            <button
              type="button"
              className={`pf-confirm-btn pf-confirm-btn-primary${danger ? " pf-confirm-btn-danger" : ""}`}
              onClick={onConfirm}
              disabled={loading}
            >
              {loading ? "处理中…" : confirmLabel}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
