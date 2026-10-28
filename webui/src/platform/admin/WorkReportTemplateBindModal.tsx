import { useCallback, useEffect, useMemo, useState } from "react";
import { Modal } from "../components/Modal";
import { loadReportTemplates } from "../dataCenter/reportApi";
import type { ReportTemplate } from "../dataCenter/reportPlanMock";
import {
  getWorkReportTemplateBinding,
  saveWorkReportTemplateBinding,
  type WorkReportTemplateBinding,
} from "./workReportTemplateApi";

const NO_TEMPLATE = "";

type Props = {
  open: boolean;
  onClose: () => void;
  workId: string;
  workName: string;
  workSaved: boolean;
  onBindingChange?: (binding: WorkReportTemplateBinding | null) => void;
  onSaved?: (binding: WorkReportTemplateBinding | null, message: string) => void;
};

function activeTemplateId(binding: WorkReportTemplateBinding | null): string {
  if (!binding?.enabled || !binding.template_id) return NO_TEMPLATE;
  return binding.template_id;
}

export function WorkReportTemplateBindModal({
  open,
  onClose,
  workId,
  workName,
  workSaved,
  onBindingChange,
  onSaved,
}: Props) {
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [binding, setBinding] = useState<WorkReportTemplateBinding | null>(null);
  const [pickTemplateId, setPickTemplateId] = useState(NO_TEMPLATE);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const pickedTemplate = templates.find((t) => t.id === pickTemplateId) ?? null;
  const savedTemplateId = activeTemplateId(binding);
  const dirty = pickTemplateId !== savedTemplateId;
  const busy = loading || saving;

  const syncBinding = useCallback(
    (row: WorkReportTemplateBinding | null) => {
      setBinding(row);
      onBindingChange?.(row);
    },
    [onBindingChange],
  );

  const reload = useCallback(async () => {
    if (!open || !workSaved) {
      setBinding(null);
      setPickTemplateId(NO_TEMPLATE);
      setTemplates([]);
      setError("");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const [tpls, row] = await Promise.all([
        loadReportTemplates(),
        getWorkReportTemplateBinding(workId),
      ]);
      setTemplates(tpls);
      syncBinding(row);
      setPickTemplateId(activeTemplateId(row));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [open, workId, workSaved, syncBinding]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const statusText = useMemo(() => {
    if (loading) return "正在加载…";
    if (savedTemplateId && binding?.template_name) {
      return `已配置「${binding.template_name}」，业务执行完成后将自动生成报告。`;
    }
    return "尚未配置报告模版，执行完成后不会自动生成报告。";
  }, [binding?.template_name, loading, savedTemplateId]);

  const save = async () => {
    if (!dirty || saving) return;
    setSaving(true);
    setError("");
    try {
      await saveWorkReportTemplateBinding(workId, pickTemplateId || null);
      const verified = await getWorkReportTemplateBinding(workId);
      syncBinding(verified);
      setPickTemplateId(activeTemplateId(verified));
      const message =
        verified?.enabled && verified.template_name
          ? `已绑定报告模版「${verified.template_name}」`
          : "已取消自动生成报告";
      onSaved?.(verified, message);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败，请重试");
    } finally {
      setSaving(false);
    }
  };

  const handleClose = () => {
    if (busy) return;
    onClose();
  };

  return (
    <Modal
      open={open}
      title="报告模版"
      onClose={handleClose}
      wide
      closeOnBackdrop={false}
      modalClassName="pf-modal-work-report-bind"
      footer={
        <>
          <button type="button" className="pf-btn pf-btn-sm" onClick={handleClose} disabled={busy}>
            取消
          </button>
          <button
            type="button"
            className="pf-btn pf-btn-sm pf-btn-primary"
            disabled={busy || !dirty}
            onClick={() => void save()}
          >
            {saving ? "保存中…" : "确定"}
          </button>
        </>
      }
    >
      {!workSaved ? (
        <p className="pf-work-report-bind-hint">请先保存巡检业务，再配置报告模版。</p>
      ) : (
        <div className="pf-work-report-bind-body">
          {error ? <p className="pf-studio-ai-error pf-work-report-bind-error">{error}</p> : null}

          <p className="pf-work-report-bind-lead">
            为<strong>{workName}</strong>选择报告模版。模版在
            <strong>报告管理 → 报告模版</strong>
            中维护，多个业务可共用同一模版。
          </p>

          <div
            className={`pf-work-report-bind-status${savedTemplateId ? " is-on" : ""}`}
            aria-live="polite"
          >
            {statusText}
          </div>

          <label className="pf-work-report-bind-field">
            <span>选择模版</span>
            <select
              className="pf-cell-input pf-select"
              value={pickTemplateId}
              disabled={busy}
              onChange={(e) => setPickTemplateId(e.target.value)}
            >
              <option value={NO_TEMPLATE}>不自动生成报告</option>
              {templates.length === 0 ? (
                <option value="__empty__" disabled>
                  模版库为空，请先在报告管理中添加
                </option>
              ) : (
                templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))
              )}
            </select>
          </label>

          {pickedTemplate?.description ? (
            <p className="pf-work-report-bind-desc">{pickedTemplate.description}</p>
          ) : pickTemplateId ? (
            <p className="pf-work-report-bind-desc pf-work-report-bind-desc-muted">
              业务执行完成后，Agent 将结合运行结果与此模版内容生成报告。
            </p>
          ) : null}
        </div>
      )}
    </Modal>
  );
}
