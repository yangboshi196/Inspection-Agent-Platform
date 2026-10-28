import { useEffect, useMemo, useRef, useState } from "react";

export type WorkMultiSelectOption = {
  id: string;
  label: string;
};

type Props = {
  options: WorkMultiSelectOption[];
  value: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
  placeholder?: string;
};

const MAX_VISIBLE_CHIPS = 2;

export function WorkMultiSelect({
  options,
  value,
  onChange,
  disabled = false,
  placeholder = "选择订阅业务",
}: Props) {
  const [open, setOpen] = useState(false);
  const [keyword, setKeyword] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  const selectedSet = useMemo(() => new Set(value), [value]);
  const labelById = useMemo(
    () => Object.fromEntries(options.map((o) => [o.id, o.label])),
    [options],
  );

  const filtered = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => o.label.toLowerCase().includes(q) || o.id.toLowerCase().includes(q));
  }, [keyword, options]);

  const selectedLabels = value.map((id) => labelById[id] || id);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const toggle = (id: string) => {
    if (selectedSet.has(id)) {
      onChange(value.filter((x) => x !== id));
    } else {
      onChange([...value, id]);
    }
  };

  const visibleChips = selectedLabels.slice(0, MAX_VISIBLE_CHIPS);
  const hiddenCount = Math.max(0, selectedLabels.length - MAX_VISIBLE_CHIPS);

  return (
    <div
      className={`pf-report-push-select${open ? " is-open" : ""}${disabled ? " is-disabled" : ""}`}
      ref={rootRef}
    >
      <button
        type="button"
        className="pf-report-push-select-trigger"
        disabled={disabled}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="pf-report-push-select-value">
          {selectedLabels.length === 0 ? (
            <span className="pf-report-push-select-placeholder">{placeholder}</span>
          ) : (
            <span className="pf-report-push-chip-row">
              {visibleChips.map((label, idx) => (
                <span key={`${value[idx]}-${label}`} className="pf-report-push-chip" title={label}>
                  {label}
                </span>
              ))}
              {hiddenCount > 0 ? <span className="pf-report-push-chip-more">+{hiddenCount}</span> : null}
            </span>
          )}
        </span>
        <span className="pf-report-push-select-caret" aria-hidden>
          ▾
        </span>
      </button>

      {open ? (
        <div className="pf-report-push-select-panel" role="listbox" aria-multiselectable>
          <input
            type="search"
            className="pf-cell-input pf-report-push-select-search"
            placeholder="搜索业务…"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            autoFocus
          />
          <ul className="pf-report-push-select-list">
            {filtered.length === 0 ? (
              <li className="pf-report-push-select-empty">无匹配业务</li>
            ) : (
              filtered.map((opt) => {
                const checked = selectedSet.has(opt.id);
                return (
                  <li key={opt.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={checked}
                      className={`pf-report-push-select-item${checked ? " is-selected" : ""}`}
                      onClick={() => toggle(opt.id)}
                    >
                      <span className="pf-report-push-select-item-label" title={opt.label}>
                        {opt.label}
                      </span>
                      {checked ? <span className="pf-report-push-select-check" aria-hidden>✓</span> : null}
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
