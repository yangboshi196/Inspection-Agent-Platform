import type { ReactNode } from "react";

type Props = {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  modalClassName?: string;
  footer?: ReactNode;
  /** 点击遮罩是否关闭；默认 true。AI 编排等长表单建议 false。 */
  closeOnBackdrop?: boolean;
};

export function Modal({
  open,
  title,
  onClose,
  children,
  wide,
  modalClassName,
  footer,
  closeOnBackdrop = true,
}: Props) {
  if (!open) return null;
  return (
    <div
      className="pf-modal-backdrop"
      onClick={closeOnBackdrop ? onClose : undefined}
      role="presentation"
    >
      <div
        className={`pf-modal${wide ? " pf-modal-wide" : ""}${modalClassName ? ` ${modalClassName}` : ""}`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="pf-modal-title"
      >
        <header className="pf-modal-header">
          <h2 id="pf-modal-title">{title}</h2>
          <button type="button" className="pf-modal-close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>
        <div className="pf-modal-body">{children}</div>
        {footer ? <footer className="pf-modal-footer">{footer}</footer> : null}
      </div>
    </div>
  );
}
