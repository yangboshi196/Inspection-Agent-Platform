import { useEffect, useMemo, useState } from "react";
import { Modal } from "../components/Modal";
import type { CameraDevice, InspectionWorkEntity, SensorDevice } from "../types";
import {
  defaultDetectionRoi,
  readDetectionRoiFromParams,
  type DetectionRoiBundle,
} from "./detectionRoi";
import {
  algoParamFields,
  applyDetectionRoiToParams,
  applyVaioAlgorithmConfig,
  getEquipmentAlgoParams,
  isAlgoEnabled,
  isVideoAlgo,
  mergeEquipmentAlgoParams,
  type AlgoParamField,
  type EquipmentAlgoParams,
} from "./equipmentAlgoConfig";
import { VideoRoiEditor } from "./VideoRoiEditor";

type Props = {
  open: boolean;
  work: InspectionWorkEntity;
  equipmentId: string;
  equipmentName: string;
  equipmentRole?: string;
  cameras: CameraDevice[];
  sensors: SensorDevice[];
  onClose: () => void;
  onSave: (params: InspectionWorkEntity["equipment_algo_params"]) => void;
};

type ParamTab = "basic" | "advanced";

function ParamField({
  field,
  value,
  onChange,
}: {
  field: AlgoParamField;
  value: string | number | boolean;
  onChange: (next: string | number | boolean) => void;
}) {
  if (field.type === "boolean") {
    return (
      <label className="pf-studio-equip-param pf-studio-equip-param-check">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span>
          {field.label}
          {field.hint ? <em>{field.hint}</em> : null}
        </span>
      </label>
    );
  }

  if (field.type === "select") {
    return (
      <label className="pf-studio-equip-param">
        <span>{field.label}</span>
        <select
          className="pf-select"
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
        >
          {(field.options ?? []).map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {field.hint ? <em className="pf-studio-equip-param-hint">{field.hint}</em> : null}
      </label>
    );
  }

  return (
    <label className="pf-studio-equip-param">
      <span>
        {field.label}
        {field.unit ? <i>{field.unit}</i> : null}
      </span>
      <input
        className="pf-cell-input"
        type={field.type === "number" ? "number" : "text"}
        value={String(value)}
        min={field.min}
        max={field.max}
        step={field.step}
        onChange={(e) =>
          onChange(field.type === "number" ? Number(e.target.value) : e.target.value)
        }
      />
      {field.hint ? <em className="pf-studio-equip-param-hint">{field.hint}</em> : null}
    </label>
  );
}

function formatLiveClock(date: Date) {
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

function SensorLivePreview({
  equipmentId,
  equipmentName,
  sensors,
}: {
  equipmentId: string;
  equipmentName: string;
  sensors: SensorDevice[];
}) {
  const sensor = sensors.find((s) => s.id === equipmentId) ?? sensors[0];
  if (!sensor) {
    return (
      <div className="pf-studio-equip-live pf-studio-equip-live-sensor">
        <p className="pf-studio-equip-live-caption">未找到传感器设备</p>
      </div>
    );
  }
  const [clock, setClock] = useState(() => formatLiveClock(new Date()));
  const [sensorValue, setSensorValue] = useState(() => 24.6);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setClock(formatLiveClock(new Date()));
      setSensorValue((v) => {
        const delta = (Math.random() - 0.5) * 0.8;
        if (sensor.dataType.includes("噪声")) return Math.max(58, Math.min(78, v + delta * 3));
        if (sensor.dataType.includes("烟雾")) return Math.max(0.02, Math.min(0.18, v + delta * 0.02));
        return Math.max(18, Math.min(32, v + delta));
      });
    }, 1200);
    return () => window.clearInterval(timer);
  }, [sensor]);

  const display =
    sensor.dataType.includes("噪声")
      ? `${sensorValue.toFixed(1)} ${sensor.unit}`
      : sensor.dataType.includes("烟雾") || sensor.dataType.includes("粉尘")
        ? `${sensorValue.toFixed(3)} ${sensor.unit}`
        : `${sensorValue.toFixed(1)} ${sensor.unit}`;

  return (
    <div className="pf-studio-equip-live pf-studio-equip-live-sensor">
      <div className="pf-studio-equip-live-sensor-panel">
        <span className="pf-studio-equip-live-badge pf-studio-equip-live-badge-sensor">实时</span>
        <strong>{display}</strong>
        <em>{sensor.dataType}</em>
        <span className="pf-studio-equip-live-time">{clock}</span>
      </div>
      <p className="pf-studio-equip-live-caption">
        {equipmentName} · {sensor.online ? "在线" : "离线"} · 传感数据流（演示）
      </p>
    </div>
  );
}

export function EquipmentAlgoConfigModal({
  open,
  work,
  equipmentId,
  equipmentName,
  equipmentRole,
  cameras,
  sensors,
  onClose,
  onSave,
}: Props) {
  const algorithms = work.algorithm_set;
  const camera = cameras.find((c) => c.id === equipmentId);
  const isCamera =
    equipmentRole === "camera" || (equipmentRole !== "sensor" && Boolean(camera));
  const previewCamera = camera ?? cameras[0];

  const [activeAlgoId, setActiveAlgoId] = useState(algorithms[0]?.algorithm_id ?? "");
  const [draft, setDraft] = useState<Record<string, EquipmentAlgoParams>>({});
  const [paramTab, setParamTab] = useState<ParamTab>("basic");
  const [clock, setClock] = useState(() => formatLiveClock(new Date()));

  useEffect(() => {
    if (!open) return;
    const initial: Record<string, EquipmentAlgoParams> = {};
    for (const algo of algorithms) {
      initial[algo.algorithm_id] = getEquipmentAlgoParams(work, equipmentId, algo.algorithm_id);
    }
    setDraft(initial);
    setActiveAlgoId(algorithms[0]?.algorithm_id ?? "");
    setParamTab("basic");
  }, [open, work, equipmentId, algorithms]);

  useEffect(() => {
    if (!open || !isCamera) return;
    const timer = window.setInterval(() => setClock(formatLiveClock(new Date())), 1000);
    return () => window.clearInterval(timer);
  }, [open, isCamera]);

  const activeAlgo = algorithms.find((a) => a.algorithm_id === activeAlgoId) ?? algorithms[0];
  const activeFields = useMemo(
    () => (activeAlgo ? algoParamFields(activeAlgo.algorithm_id) : []),
    [activeAlgo],
  );
  const basicFields = activeFields.slice(0, Math.min(3, activeFields.length));
  const advancedFields = activeFields.slice(basicFields.length);
  const visibleFields = paramTab === "basic" ? basicFields : advancedFields;

  const activeParams = activeAlgo ? draft[activeAlgo.algorithm_id] ?? {} : {};
  const activeEnabled = activeAlgo ? isAlgoEnabled(activeParams) : true;
  const activeRoi: DetectionRoiBundle = activeAlgo
    ? readDetectionRoiFromParams(activeParams, activeAlgo.algorithm_id)
    : { detection: [], inverse: [] };

  const patchAlgoParams = (algoId: string, key: string, value: string | number | boolean) => {
    setDraft((prev) => ({
      ...prev,
      [algoId]: { ...prev[algoId], [key]: value },
    }));
  };

  const patchAlgoRoi = (algoId: string, roi: DetectionRoiBundle) => {
    setDraft((prev) => ({
      ...prev,
      [algoId]: applyDetectionRoiToParams(prev[algoId] ?? {}, roi, algoId),
    }));
  };

  const resetActiveRoi = () => {
    if (!activeAlgo) return;
    patchAlgoRoi(activeAlgo.algorithm_id, defaultDetectionRoi(activeAlgo.algorithm_id));
  };

  const handleSave = () => {
    let merged = work.equipment_algo_params;
    for (const [algoId, params] of Object.entries(draft)) {
      merged = mergeEquipmentAlgoParams(
        { ...work, equipment_algo_params: merged },
        equipmentId,
        algoId,
        applyVaioAlgorithmConfig(params, algoId),
      );
    }
    onSave(merged);
    onClose();
  };

  const toggleActiveAlgo = () => {
    if (!activeAlgo) return;
    patchAlgoParams(activeAlgo.algorithm_id, "enabled", !activeEnabled);
  };

  return (
    <Modal
      open={open}
      title={`算法配置 · ${equipmentName}`}
      onClose={onClose}
      modalClassName="pf-modal-equip-algo-config"
      footer={
        <>
          <button type="button" className="pf-btn pf-btn-sm" onClick={onClose}>
            取消
          </button>
          <button type="button" className="pf-btn pf-btn-sm pf-btn-primary" onClick={handleSave}>
            保存
          </button>
        </>
      }
    >
      <div className="pf-algo-config-shell">
        <aside className="pf-algo-config-sidebar">
          <h4 className="pf-algo-config-sidebar-title">算法列表</h4>
          {algorithms.length === 0 ? (
            <p className="pf-studio-equip-config-empty">请先在「算法」步骤中选择至少一个算法</p>
          ) : (
            <ul className="pf-algo-config-algo-list">
              {algorithms.map((algo) => {
                const enabled = isAlgoEnabled(draft[algo.algorithm_id] ?? {});
                const active = activeAlgo?.algorithm_id === algo.algorithm_id;
                return (
                  <li key={algo.algorithm_id}>
                    <button
                      type="button"
                      className={`pf-algo-config-algo-item${active ? " is-active" : ""}${enabled ? "" : " is-disabled"}`}
                      onClick={() => setActiveAlgoId(algo.algorithm_id)}
                    >
                      <span className="pf-algo-config-algo-item-name">{algo.name}</span>
                      <span
                        className={`pf-algo-config-algo-item-badge${enabled ? " is-on" : ""}`}
                        aria-hidden
                      >
                        {enabled ? "✓" : "—"}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </aside>

        <div className="pf-algo-config-main">
          {activeAlgo ? (
            <>
              <header className="pf-algo-config-header">
                <p>
                  您当前正在配置：<strong>{activeAlgo.name}</strong>
                </p>
                <button
                  type="button"
                  className={`pf-btn pf-btn-sm${activeEnabled ? "" : " pf-btn-primary"}`}
                  onClick={toggleActiveAlgo}
                >
                  {activeEnabled ? "禁用" : "启用"}
                </button>
              </header>

              <div className="pf-algo-config-body">
                <div className="pf-algo-config-preview">
                  {isCamera && isVideoAlgo(activeAlgo.algorithm_id) && previewCamera ? (
                    <VideoRoiEditor
                      background={previewCamera.thumbnail}
                      equipmentId={previewCamera.id}
                      rtspAddress={previewCamera.platformAddress}
                      online={previewCamera.online}
                      liveTime={clock}
                      roi={activeRoi}
                      onChange={(next) => patchAlgoRoi(activeAlgo.algorithm_id, next)}
                      onReset={resetActiveRoi}
                    />
                  ) : (
                    <SensorLivePreview
                      equipmentId={equipmentId}
                      equipmentName={equipmentName}
                      sensors={sensors}
                    />
                  )}
                </div>

                <div className="pf-algo-config-params">
                  <div className="pf-algo-config-param-tabs" role="tablist">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={paramTab === "basic"}
                      className={`pf-studio-filter-chip${paramTab === "basic" ? " is-active" : ""}`}
                      onClick={() => setParamTab("basic")}
                    >
                      基本参数
                    </button>
                    {advancedFields.length > 0 ? (
                      <button
                        type="button"
                        role="tab"
                        aria-selected={paramTab === "advanced"}
                        className={`pf-studio-filter-chip${paramTab === "advanced" ? " is-active" : ""}`}
                        onClick={() => setParamTab("advanced")}
                      >
                        高级参数
                      </button>
                    ) : null}
                  </div>

                  <div className="pf-studio-equip-config-form pf-algo-config-form" role="tabpanel">
                    {visibleFields.length === 0 ? (
                      <p className="pf-algo-config-form-empty">该分组暂无参数</p>
                    ) : (
                      visibleFields.map((field) => (
                        <ParamField
                          key={field.key}
                          field={field}
                          value={activeParams[field.key] ?? field.defaultValue}
                          onChange={(next) =>
                            patchAlgoParams(activeAlgo.algorithm_id, field.key, next)
                          }
                        />
                      ))
                    )}
                  </div>
                </div>
              </div>
            </>
          ) : (
            <p className="pf-studio-equip-config-empty">请选择左侧算法进行配置</p>
          )}
        </div>
      </div>
    </Modal>
  );
}
