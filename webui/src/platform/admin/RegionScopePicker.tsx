import { useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent } from "react";
import {
  buildRegionTree,
  flattenRegionTreeWithCollapse,
  type RegionTreeNode,
} from "../regionTree";

type RegionScopePickerProps = {
  regionRows: Array<{ id: string; name: string; parent_id?: string; sort_order?: number }>;
  deviceCountFor: (id: string) => number;
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
  placeholder?: string;
};

function displayRoots(roots: RegionTreeNode[]): RegionTreeNode[] {
  if (roots.length === 1 && roots[0].id === "r0") return roots[0].children;
  return roots.filter((r) => r.id !== "r0");
}

function summarizeSelection(selectedIds: string[], nodes: RegionTreeNode[]): string {
  if (selectedIds.length === 0) return "";
  const nameById = new Map(nodes.map((n) => [n.id, n.name]));
  const first = nameById.get(selectedIds[0]) ?? selectedIds[0];
  if (selectedIds.length === 1) return first;
  return `${first} 等 ${selectedIds.length} 个区域`;
}

export function RegionScopePicker({
  regionRows,
  deviceCountFor,
  selectedIds,
  onChange,
  disabled = false,
  placeholder = "选择作用区域",
}: RegionScopePickerProps) {
  const [open, setOpen] = useState(false);
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(() => new Set());
  const [localSelectedIds, setLocalSelectedIds] = useState<string[]>(selectedIds);
  const rootRef = useRef<HTMLDivElement>(null);
  const skipPropSyncRef = useRef(false);

  useEffect(() => {
    if (skipPropSyncRef.current) {
      skipPropSyncRef.current = false;
      return;
    }
    setLocalSelectedIds(selectedIds);
  }, [selectedIds]);

  const treeRoots = useMemo(
    () => displayRoots(buildRegionTree(regionRows, deviceCountFor)),
    [regionRows, deviceCountFor],
  );

  const flatNodes = useMemo(
    () => flattenRegionTreeWithCollapse(treeRoots, collapsedIds),
    [treeRoots, collapsedIds],
  );

  const summary = useMemo(
    () => summarizeSelection(localSelectedIds, flattenRegionTreeWithCollapse(treeRoots, new Set())),
    [localSelectedIds, treeRoots],
  );

  useEffect(() => {
    if (!open) return;
    const onDocPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    // 延迟注册，避免「打开下拉」的同一次点击被误判为外部点击
    const timer = window.setTimeout(() => {
      document.addEventListener("pointerdown", onDocPointer);
    }, 0);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("pointerdown", onDocPointer);
    };
  }, [open]);

  const toggleCollapse = (id: string) => {
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleRegion = (id: string) => {
    const next = localSelectedIds.includes(id)
      ? localSelectedIds.filter((x) => x !== id)
      : [...localSelectedIds, id];
    setLocalSelectedIds(next);
    skipPropSyncRef.current = true;
    onChange(next);
  };

  const stopBubble = (e: MouseEvent) => {
    e.stopPropagation();
  };

  return (
    <div className="pf-studio-region-picker" ref={rootRef}>
      <button
        type="button"
        className={`pf-select pf-studio-region-picker-trigger${open ? " is-open" : ""}`}
        disabled={disabled || flatNodes.length === 0}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="pf-studio-region-picker-trigger-text">
          {summary || placeholder}
        </span>
        <span className="pf-studio-region-picker-chevron" aria-hidden>
          ▾
        </span>
      </button>

      {open ? (
        <div
          className="pf-studio-region-picker-panel"
          role="listbox"
          aria-multiselectable="true"
          onPointerDown={stopBubble}
          onClick={stopBubble}
        >
          {flatNodes.length === 0 ? (
            <p className="pf-studio-region-picker-empty">暂无可用区域</p>
          ) : (
            <ul className="pf-studio-region-picker-list">
              {flatNodes.map((node) => {
                const hasChildren = node.childCount > 0;
                const isCollapsed = collapsedIds.has(node.id);
                const isSelected = localSelectedIds.includes(node.id);
                return (
                  <li key={node.id}>
                    <div
                      className={`pf-studio-region-picker-row${isSelected ? " is-selected" : ""}`}
                      style={{ "--pf-region-depth": node.depth } as CSSProperties}
                    >
                      {hasChildren ? (
                        <button
                          type="button"
                          className={`pf-region-tree-toggle${isCollapsed ? "" : " is-expanded"}`}
                          aria-label={isCollapsed ? "展开子区域" : "收起子区域"}
                          aria-expanded={!isCollapsed}
                          onClick={() => toggleCollapse(node.id)}
                        >
                          <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
                            <path
                              d="M3 1.5 L7 5 L3 8.5"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.5"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                        </button>
                      ) : (
                        <span className="pf-region-tree-toggle pf-region-tree-toggle-spacer" aria-hidden />
                      )}

                      <button
                        type="button"
                        role="option"
                        aria-selected={isSelected}
                        className="pf-studio-region-picker-item"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleRegion(node.id);
                        }}
                      >
                        <span className="pf-studio-region-picker-item-main">
                          <span className="pf-region-tree-level">{`${node.depth + 1}级`}</span>
                          <span className="pf-region-tree-name">{node.name}</span>
                          <span className="pf-studio-region-picker-count">
                            {node.subtreeDeviceCount} 台
                          </span>
                        </span>
                        <span
                          className={`pf-studio-region-pick-dot${isSelected ? " is-checked" : ""}`}
                          aria-hidden
                        />
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          {localSelectedIds.length > 0 ? (
            <div className="pf-studio-region-picker-foot">
              已选 {localSelectedIds.length} 个区域
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
