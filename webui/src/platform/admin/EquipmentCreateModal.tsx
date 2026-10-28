import { useEffect, useState } from "react";
import { Modal } from "../components/Modal";
import { createEquipment } from "../equipmentApi";

type Props = {
  open: boolean;
  regionId: string;
  regionName: string;
  onClose: () => void;
  onCreated: (equipmentId: string) => void;
};

/** 单设备导入：在选中区域下手动创建设备 */
export function EquipmentCreateModal({ open, regionId, regionName, onClose, onCreated }: Props) {
  const [equipmentId, setEquipmentId] = useState("");
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"camera" | "sensor">("camera");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setEquipmentId("");
    setName("");
    setKind("camera");
    setDescription("");
    setError("");
  }, [open, regionId]);

  const handleClose = () => {
    if (saving) return;
    onClose();
  };

  const handleSubmit = async () => {
    if (!name.trim()) {
      setError("请填写设备名称");
      return;
    }
    if (!regionId) {
      setError("请先选择所属区域");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const row = await createEquipment({
        id: equipmentId.trim() || undefined,
        name: name.trim(),
        kind,
        description: description.trim(),
        region_id: regionId,
      });
      onCreated(row.id);
      onClose();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      title="添加设备"
      onClose={handleClose}
      footer={
        <>
          <button type="button" className="pf-btn pf-btn-sm" disabled={saving} onClick={handleClose}>
            取消
          </button>
          <button
            type="button"
            className="pf-btn pf-btn-sm pf-btn-primary"
            disabled={saving}
            onClick={() => void handleSubmit()}
          >
            {saving ? "保存中…" : "创建设备"}
          </button>
        </>
      }
    >
      <div className="pf-equip-create-form">
        <p className="pf-equip-create-intro">
          在区域 <strong>{regionName || regionId}</strong> 下新增设备。设备 ID 可留空由系统自动生成。
        </p>
        <label className="pf-dev-field">
          <span>设备 ID（选填）</span>
          <input
            className="pf-cell-input"
            value={equipmentId}
            onChange={(e) => setEquipmentId(e.target.value)}
            placeholder="如 cam-gate-01，留空自动生成"
          />
        </label>
        <label className="pf-dev-field">
          <span>设备名称（必填）</span>
          <input
            className="pf-cell-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="如 东门岗摄像头"
            required
          />
        </label>
        <label className="pf-dev-field">
          <span>类型</span>
          <select className="pf-cell-input" value={kind} onChange={(e) => setKind(e.target.value as "camera" | "sensor")}>
            <option value="camera">摄像头</option>
            <option value="sensor">传感器</option>
          </select>
        </label>
        <label className="pf-dev-field">
          <span>描述</span>
          <textarea
            className="pf-cell-textarea pf-dev-textarea"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="地点、画面、业务说明等"
          />
        </label>
        <label className="pf-dev-field">
          <span>所属区域 ID</span>
          <input className="pf-cell-input" value={regionId} readOnly />
        </label>
        {error ? <p className="pf-equip-import-error">{error}</p> : null}
      </div>
    </Modal>
  );
}
