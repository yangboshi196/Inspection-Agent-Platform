import { useEffect, useRef, useState } from "react";
import type { AuthRoleRow } from "../authApi";

type Props = {
  value: string;
  roles: AuthRoleRow[];
  disabled?: boolean;
  onChange: (roleId: string) => void;
};

export function RoleSelect({ value, roles, disabled = false, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLUListElement>(null);
  const selected = roles.find((r) => r.role_id === value) ?? null;

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  useEffect(() => {
    if (!open || !rootRef.current || !menuRef.current) return;
    const root = rootRef.current;
    const menu = menuRef.current;
    const scrollParent = root.closest(".pf-modal-body") as HTMLElement | null;

    const scrollIntoModal = () => {
      if (!scrollParent) {
        menu.scrollIntoView({ block: "nearest", behavior: "smooth" });
        return;
      }
      const parentRect = scrollParent.getBoundingClientRect();
      const menuRect = menu.getBoundingClientRect();
      const overflow = menuRect.bottom - parentRect.bottom + 12;
      if (overflow > 0) {
        scrollParent.scrollTo({ top: scrollParent.scrollTop + overflow, behavior: "smooth" });
      }
    };

    requestAnimationFrame(() => {
      requestAnimationFrame(scrollIntoModal);
    });
  }, [open, roles.length]);

  return (
    <div className={`pf-perm-role-select${open ? " is-open" : ""}`} ref={rootRef}>
      <button
        type="button"
        className={`pf-perm-role-select-trigger${selected ? " has-value" : ""}`}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {selected ? (
          <span className="pf-perm-role-select-value">{selected.name}</span>
        ) : (
          <span className="pf-perm-role-select-placeholder">
            角色选择
            <span className="pf-perm-role-select-caret" aria-hidden>
              ▾
            </span>
          </span>
        )}
        {selected ? (
          <span className="pf-perm-role-select-caret pf-perm-role-select-caret-muted" aria-hidden>
            ▾
          </span>
        ) : null}
      </button>
      {open ? (
        <ul className="pf-perm-role-select-menu" role="listbox" ref={menuRef}>
          {roles.length === 0 ? (
            <li className="pf-perm-role-select-empty">暂无角色，请先新建角色</li>
          ) : (
            roles.map((role) => (
              <li key={role.role_id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={role.role_id === value}
                  className={role.role_id === value ? "is-active" : ""}
                  onClick={() => {
                    onChange(role.role_id);
                    setOpen(false);
                  }}
                >
                  <strong>{role.name}</strong>
                  <span>{(role.permissions ?? []).length} 项权限</span>
                </button>
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
}
