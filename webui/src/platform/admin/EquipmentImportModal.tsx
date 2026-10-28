import { useMemo, useState } from "react";
import { Modal } from "../components/Modal";
import { importBuiltinEquipment } from "../equipmentApi";
import {
  EQUIPMENT_IMPORT_MANIFEST,
  groupImportPreviewByRegion,
} from "./equipmentImportManifest";

type ImportMode = "merge" | "replace";

type Props = {
  open: boolean;
  onClose: () => void;
  onImported: (result: { inserted: number; mode: ImportMode }) => void;
  currentDeviceCount: number;
};

export function EquipmentImportModal({ open, onClose, onImported, currentDeviceCount }: Props) {
  const [mode, setMode] = useState<ImportMode>("merge");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState<{ inserted: number } | null>(null);

  const regionGroups = useMemo(
    () => groupImportPreviewByRegion(EQUIPMENT_IMPORT_MANIFEST.rows),
    [],
  );

  const handleClose = () => {
    if (loading) return;
    setError("");
    setSuccess(null);
    setMode("merge");
    onClose();
  };

  const runImport = async () => {
    if (mode === "replace" && currentDeviceCount > 0) {
      const ok = window.confirm(
        "全量替换将删除现有全部设备记录后重新导入演示包，关联巡检业务中的设备引用可能失效。确定继续？",
      );
      if (!ok) return;
    }
    setLoading(true);
    setError("");
    try {
      const inserted = await importBuiltinEquipment(mode === "replace");
      setSuccess({ inserted });
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const finish = () => {
    if (success) onImported({ inserted: success.inserted, mode });
    handleClose();
  };

  const m = EQUIPMENT_IMPORT_MANIFEST;

  return (
    <Modal
      open={open}
      title="导入设备"
      onClose={handleClose}
      wide
      modalClassName="pf-modal-equipment-import"
      footer={
        success ? (
          <>
            <button type="button" className="pf-btn pf-btn-sm pf-btn-primary" onClick={finish}>
              完成
            </button>
          </>
        ) : (
          <>
            <button type="button" className="pf-btn pf-btn-sm" disabled={loading} onClick={handleClose}>
              取消
            </button>
            <button
              type="button"
              className={`pf-btn pf-btn-sm pf-btn-primary${loading ? " is-loading" : ""}`}
              disabled={loading}
              onClick={() => void runImport()}
            >
              {loading ? "导入中…" : "开始导入"}
            </button>
          </>
        )
      }
    >
      {success ? (
        <div className="pf-equip-import-result">
          <div className="pf-equip-import-result-icon" aria-hidden>✓</div>
          <h3>导入完成</h3>
          <p>
            {success.inserted > 0
              ? `本次写入 ${success.inserted} 条设备记录。左侧选择区域即可查看归属设备。`
              : "演示包中的设备均已存在，未新增记录。可在区域列表中查看已有设备。"}
          </p>
        </div>
      ) : (
        <div className="pf-equip-import">
          <div className="pf-equip-import-hero">
            <div className="pf-equip-import-hero-main">
              <span className="pf-equip-import-hero-icon" aria-hidden>⬇</span>
              <div>
                <strong>{m.packageName}</strong>
                <p>{m.description}</p>
              </div>
            </div>
            <div className="pf-equip-import-stats">
              <span>
                <strong>{m.total}</strong>
                <em>合计</em>
              </span>
              <span>
                <strong>{m.cameras}</strong>
                <em>摄像头</em>
              </span>
              <span>
                <strong>{m.sensors}</strong>
                <em>传感器</em>
              </span>
              <span>
                <strong>{regionGroups.length}</strong>
                <em>覆盖区域</em>
              </span>
            </div>
          </div>

          <section className="pf-equip-import-section">
            <h3>导入方式</h3>
            <div className="pf-equip-import-mode-grid">
              <button
                type="button"
                className={`pf-equip-import-mode-card${mode === "merge" ? " is-active" : ""}`}
                onClick={() => setMode("merge")}
              >
                <span className="pf-equip-import-mode-title">追加导入</span>
                <span className="pf-equip-import-mode-desc">仅新增种子包中尚未存在的设备 ID，不修改、不删除已有设备。</span>
                <span className="pf-equip-import-mode-tag">推荐</span>
              </button>
              <button
                type="button"
                className={`pf-equip-import-mode-card pf-equip-import-mode-card-danger${mode === "replace" ? " is-active" : ""}`}
                onClick={() => setMode("replace")}
              >
                <span className="pf-equip-import-mode-title">全量替换</span>
                <span className="pf-equip-import-mode-desc">清空设备库后重新写入演示包，用于重置演示环境。</span>
              </button>
            </div>
          </section>

          <section className="pf-equip-import-section">
            <div className="pf-equip-import-section-head">
              <h3>设备清单预览</h3>
              <span className="pf-equip-import-section-hint">导入后按 region_id 自动归属区域</span>
            </div>
            <div className="pf-equip-import-preview">
              {regionGroups.map((group) => (
                <details key={group.regionId} className="pf-equip-import-region-block" open>
                  <summary>
                    <span className="pf-equip-import-region-name">{group.regionName}</span>
                    <span className="pf-equip-import-region-meta">
                      {group.cameras > 0 ? `${group.cameras} 摄像头` : null}
                      {group.cameras > 0 && group.sensors > 0 ? " · " : null}
                      {group.sensors > 0 ? `${group.sensors} 传感器` : null}
                    </span>
                  </summary>
                  <ul className="pf-equip-import-device-list">
                    {group.items.map((item) => (
                      <li key={item.id}>
                        <span className={`pf-equip-import-kind pf-equip-import-kind-${item.kind}`}>
                          {item.kind === "camera" ? "摄像" : "传感"}
                        </span>
                        <span className="pf-equip-import-device-name">{item.name}</span>
                        <code>{item.id}</code>
                        <span className={`pf-equip-import-online${item.online ? " is-on" : ""}`}>
                          {item.online ? "在线" : "离线"}
                        </span>
                      </li>
                    ))}
                  </ul>
                </details>
              ))}
            </div>
          </section>

          <section className="pf-equip-import-section pf-equip-import-coming">
            <h3>更多接入方式</h3>
            <div className="pf-equip-import-soon-grid">
              <div className="pf-equip-import-soon-card is-disabled">
                <strong>视频平台同步</strong>
                <p>从海康 / 大华等平台拉取通道列表（规划中）</p>
              </div>
              <div className="pf-equip-import-soon-card is-disabled">
                <strong>物联网网关</strong>
                <p>批量注册 MQTT / Modbus 传感器点位（规划中）</p>
              </div>
            </div>
          </section>

          {error ? <p className="pf-equip-import-error">{error}</p> : null}
        </div>
      )}
    </Modal>
  );
}
