import { useCallback, useEffect, useMemo, useState } from "react";
import { Modal } from "../components/Modal";
import type { InspectionWorkEntity } from "../types";
import {
  loadReportPushSubscriptions,
  saveReportPushSubscriptions,
  type ReportPushSubscriptionRow,
} from "./reportPushApi";
import { WorkMultiSelect, type WorkMultiSelectOption } from "./WorkMultiSelect";

type Props = {
  open: boolean;
  onClose: () => void;
  works: InspectionWorkEntity[];
  onSaved?: (message: string) => void;
};

export function ReportPushModal({ open, onClose, works, onSaved }: Props) {
  const [rows, setRows] = useState<ReportPushSubscriptionRow[]>([]);
  const [draft, setDraft] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const workOptions: WorkMultiSelectOption[] = useMemo(
    () =>
      works.map((w) => ({
        id: w.work_id,
        label: w.name || w.work_id,
      })),
    [works],
  );

  const reload = useCallback(async () => {
    if (!open) return;
    setLoading(true);
    setError("");
    try {
      const items = await loadReportPushSubscriptions();
      setRows(items);
      const map: Record<string, string[]> = {};
      for (const row of items) {
        map[row.user_id] = [...row.work_ids];
      }
      setDraft(map);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [open]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const dirty = useMemo(() => {
    return rows.some((row) => {
      const a = [...(draft[row.user_id] ?? [])].sort().join(",");
      const b = [...row.work_ids].sort().join(",");
      return a !== b;
    });
  }, [draft, rows]);

  const setWorkIdsForUser = (userId: string, workIds: string[]) => {
    setDraft((prev) => ({ ...prev, [userId]: workIds }));
  };

  const save = async () => {
    if (saving) return;
    setSaving(true);
    setError("");
    try {
      const items = rows.map((row) => ({
        user_id: row.user_id,
        work_ids: draft[row.user_id] ?? [],
      }));
      await saveReportPushSubscriptions(items);
      await reload();
      onSaved?.("报告推送订阅已保存");
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleClose = () => {
    if (saving) return;
    onClose();
  };

  return (
    <Modal
      open={open}
      title="报告推送"
      onClose={handleClose}
      wide
      closeOnBackdrop={false}
      modalClassName="pf-modal-report-push"
      footer={
        <>
          <button type="button" className="pf-btn pf-btn-sm" onClick={handleClose} disabled={saving}>
            取消
          </button>
          <button
            type="button"
            className="pf-btn pf-btn-sm pf-btn-primary"
            disabled={loading || saving || !dirty}
            onClick={() => void save()}
          >
            {saving ? "保存中…" : "确定"}
          </button>
        </>
      }
    >
      <div className="pf-report-push-body">
        <p className="pf-report-push-lead">
          为每位用户配置可查看的巡检业务。保存后，该用户登录「用户看板 → 巡检报告」时，仅展示与订阅业务相关的报告。
        </p>
        {error ? <p className="pf-studio-ai-error">{error}</p> : null}
        {loading ? (
          <p className="pf-report-push-status">正在加载用户与订阅…</p>
        ) : (
          <div className="pf-report-push-table-wrap">
            <table className="pf-report-push-table">
              <thead>
                <tr>
                  <th>用户选择</th>
                  <th>订阅业务</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.user_id}>
                    <td className="pf-report-push-user-cell">
                      <strong>{row.name || row.account}</strong>
                      {row.status !== "active" ? (
                        <span className="pf-report-push-user-muted">（已停用）</span>
                      ) : null}
                    </td>
                    <td>
                      <WorkMultiSelect
                        options={workOptions}
                        value={draft[row.user_id] ?? []}
                        onChange={(ids) => setWorkIdsForUser(row.user_id, ids)}
                        disabled={saving || row.status !== "active"}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Modal>
  );
}
