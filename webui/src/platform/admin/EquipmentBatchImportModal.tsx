import { useMemo, useState } from "react";
import { Modal } from "../components/Modal";
import { batchImportEquipment } from "../equipmentApi";
import {
  downloadEquipmentImportTemplate,
  parseEquipmentCsv,
  type EquipmentBatchRow,
} from "./equipmentBatchImport";

type Props = {
  open: boolean;
  defaultRegionId: string;
  defaultRegionName: string;
  onClose: () => void;
  onImported: (result: { inserted: number; skipped: number; errors: number }) => void;
};

/** 批量设备导入：按 CSV 模板解析后提交后端 */
export function EquipmentBatchImportModal({
  open,
  defaultRegionId,
  defaultRegionName,
  onClose,
  onImported,
}: Props) {
  const [rows, setRows] = useState<EquipmentBatchRow[]>([]);
  const [parseErrors, setParseErrors] = useState<string[]>([]);
  const [fileName, setFileName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const preview = useMemo(() => rows.slice(0, 20), [rows]);

  const reset = () => {
    setRows([]);
    setParseErrors([]);
    setFileName("");
    setError("");
  };

  const handleClose = () => {
    if (loading) return;
    reset();
    onClose();
  };

  const handleFile = async (file: File | null) => {
    if (!file) return;
    setError("");
    const text = await file.text();
    const { rows: parsed, errors } = parseEquipmentCsv(text, defaultRegionId);
    setFileName(file.name);
    setRows(parsed);
    setParseErrors(errors);
  };

  const runImport = async () => {
    if (rows.length === 0) {
      setError("请先上传符合模板的 CSV 文件");
      return;
    }
    if (parseErrors.length > 0) {
      setError("请修正 CSV 中的错误行后再导入");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const result = await batchImportEquipment(
        rows.map((r) => ({
          id: r.id,
          name: r.name,
          kind: r.kind,
          description: r.description,
          region_id: r.region_id,
        })),
      );
      onImported({
        inserted: result.inserted,
        skipped: result.skipped,
        errors: result.errors.length,
      });
      handleClose();
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      open={open}
      title="批量导入设备"
      onClose={handleClose}
      wide
      modalClassName="pf-modal-equipment-import"
      footer={
        <>
          <button type="button" className="pf-btn pf-btn-sm" disabled={loading} onClick={handleClose}>
            取消
          </button>
          <button
            type="button"
            className={`pf-btn pf-btn-sm pf-btn-primary${loading ? " is-loading" : ""}`}
            disabled={loading || rows.length === 0}
            onClick={() => void runImport()}
          >
            {loading ? "导入中…" : `导入 ${rows.length} 条`}
          </button>
        </>
      }
    >
      <div className="pf-equip-import">
        <div className="pf-equip-import-hero">
          <div className="pf-equip-import-hero-main">
            <span className="pf-equip-import-hero-icon" aria-hidden>📄</span>
            <div>
              <strong>CSV 模板导入</strong>
              <p>
                按模板填写：设备名称、类型、描述、所属区域 id；可选填设备 id。当前默认区域：
                <strong>{defaultRegionName || defaultRegionId || "未选择"}</strong>
              </p>
            </div>
          </div>
          <button
            type="button"
            className="pf-btn pf-btn-sm"
            onClick={() => downloadEquipmentImportTemplate()}
          >
            下载模板
          </button>
        </div>

        <label className="pf-equip-batch-file">
          <span>选择 CSV 文件</span>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => void handleFile(e.target.files?.[0] ?? null)}
          />
          {fileName ? <em>已选：{fileName}</em> : null}
        </label>

        {parseErrors.length > 0 ? (
          <ul className="pf-equip-batch-errors">
            {parseErrors.map((msg) => (
              <li key={msg}>{msg}</li>
            ))}
          </ul>
        ) : null}

        {preview.length > 0 ? (
          <section className="pf-equip-import-section">
            <div className="pf-equip-import-section-head">
              <h3>解析预览（前 {preview.length} 条）</h3>
              <span className="pf-equip-import-section-hint">共 {rows.length} 条</span>
            </div>
            <table className="pf-table pf-equip-batch-preview">
              <thead>
                <tr>
                  <th>设备名称</th>
                  <th>类型</th>
                  <th>描述</th>
                  <th>区域 id</th>
                </tr>
              </thead>
              <tbody>
                {preview.map((row, i) => (
                  <tr key={`${row.name}-${i}`}>
                    <td>{row.name}</td>
                    <td>{row.kind === "sensor" ? "传感器" : "摄像头"}</td>
                    <td>{row.description || "—"}</td>
                    <td><code>{row.region_id}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ) : null}

        {error ? <p className="pf-equip-import-error">{error}</p> : null}
      </div>
    </Modal>
  );
}
