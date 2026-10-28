import { useMemo } from "react";
import type { InspectionWorkEntity } from "../types";
import { summarizeEquipmentAlgoConfig } from "./equipmentAlgoConfig";

type EquipmentSelectRowProps = {
  work: InspectionWorkEntity;
  deviceId: string;
  name: string;
  subtitle: string;
  icon: string;
  accent: "blue" | "green";
  selected: boolean;
  onToggle: () => void;
  onConfigure: () => void;
};

export function EquipmentSelectRow({
  work,
  deviceId,
  name,
  subtitle,
  icon,
  accent,
  selected,
  onToggle,
  onConfigure,
}: EquipmentSelectRowProps) {
  const algoSummaries = useMemo(() => {
    if (!selected) return [];
    return summarizeEquipmentAlgoConfig(work, deviceId);
  }, [work, deviceId, selected]);

  return (
    <div className={`pf-studio-equip-row pf-studio-accent-${accent}${selected ? " is-selected" : ""}`}>
      <button
        type="button"
        className="pf-studio-equip-row-main"
        onClick={onToggle}
        aria-pressed={selected}
      >
        <span className="pf-studio-equip-row-icon">{icon}</span>
        <span className="pf-studio-equip-row-meta">
          <strong>{name}</strong>
          <small>{subtitle}</small>
        </span>
        <span className="pf-studio-equip-row-check" aria-hidden>
          {selected ? "✓" : ""}
        </span>
      </button>

      <div className="pf-studio-equip-row-side">
        {selected ? (
          <>
            {algoSummaries.length === 0 ? (
              <span className="pf-studio-equip-row-hint">请先在「算法」步骤选择算法</span>
            ) : (
              <div className="pf-studio-equip-row-algo-scroll" title={`${algoSummaries.length} 个算法`}>
                <ul className="pf-studio-equip-row-algos">
                  {algoSummaries.map((algo) => (
                    <li key={algo.algorithmId} className="pf-studio-equip-row-algo">
                      <div className="pf-studio-equip-row-algo-head">
                        <span
                          className={`pf-studio-equip-algo-status${algo.enabled ? " is-on" : " is-off"}`}
                        >
                          {algo.enabled ? "启用" : "停用"}
                        </span>
                        <span className="pf-studio-equip-algo-name">{algo.algorithmName}</span>
                      </div>
                      <span className="pf-studio-equip-algo-params">
                        {algo.configured ? algo.preview : "默认参数"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {algoSummaries.length > 0 ? (
              <span className="pf-studio-equip-algo-count">
                {algoSummaries.filter((a) => a.enabled).length}/{algoSummaries.length}
              </span>
            ) : null}
            <button
              type="button"
              className="pf-btn pf-btn-sm pf-studio-equip-row-config"
              onClick={onConfigure}
            >
              配置
            </button>
          </>
        ) : (
          <span className="pf-studio-equip-row-placeholder">选中后可配置算法与查看画面</span>
        )}
      </div>
    </div>
  );
}
