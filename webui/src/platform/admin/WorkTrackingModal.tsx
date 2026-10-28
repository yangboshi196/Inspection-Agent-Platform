import { useCallback, useEffect, useState } from "react";
import { Modal } from "../components/Modal";
import { formatTrackingTimeDisplay, TRACKING_STATUS_LABEL } from "./workTrackingFormat";
import {
  getWorkTrackingSummary,
  listWorkTracking,
  type WorkTrackingItem,
  type WorkTrackingQueueStatus,
} from "./workTrackingApi";

type TabId = WorkTrackingQueueStatus;

const TABS: TabId[] = ["running", "completed", "waiting"];

type Props = {
  open: boolean;
  onClose: () => void;
};

function TimeCell({ label, value }: { label: string; value: string }) {
  return (
    <span className="pf-work-track-time-cell">
      <span className="pf-work-track-time-label">{label}</span>
      <span className="pf-work-track-time-value">{value}</span>
    </span>
  );
}

function TrackingRow({ item }: { item: WorkTrackingItem }) {
  const status = item.queue_status;
  const prefix = `(${TRACKING_STATUS_LABEL[status] ?? status})`;

  return (
    <li className="pf-work-track-row">
      <span className="pf-work-track-status-prefix">{prefix}</span>
      <span className="pf-work-track-name" title={item.work_name}>
        {item.work_name}
      </span>
      {status === "waiting" ? (
        <>
          <TimeCell label="预计开始时间:" value={formatTrackingTimeDisplay(item, "start")} />
          <TimeCell label="预计结束时间:" value={formatTrackingTimeDisplay(item, "end")} />
        </>
      ) : status === "running" ? (
        <>
          <TimeCell label="开始时间:" value={formatTrackingTimeDisplay(item, "start")} />
          <TimeCell label="预计结束时间：" value={formatTrackingTimeDisplay(item, "end")} />
        </>
      ) : (
        <>
          <TimeCell label="开始时间:" value={formatTrackingTimeDisplay(item, "start")} />
          <TimeCell label="结束时间：" value={formatTrackingTimeDisplay(item, "end")} />
        </>
      )}
    </li>
  );
}

export function WorkTrackingModal({ open, onClose }: Props) {
  const [tab, setTab] = useState<TabId>("running");
  const [items, setItems] = useState<WorkTrackingItem[]>([]);
  const [counts, setCounts] = useState({ waiting: 0, running: 0, completed: 0 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const reload = useCallback(async (activeTab: TabId) => {
    setLoading(true);
    setError("");
    try {
      const [summary, list] = await Promise.all([
        getWorkTrackingSummary(),
        listWorkTracking(activeTab),
      ]);
      setCounts({
        waiting: summary.waiting ?? 0,
        running: summary.running ?? 0,
        completed: summary.completed ?? 0,
      });
      setItems(list);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void reload(tab);
    const timer = window.setInterval(() => {
      void reload(tab);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [open, tab, reload]);

  const countFor = (id: TabId) => counts[id] ?? 0;

  return (
    <Modal
      open={open}
      title="业务追踪"
      onClose={onClose}
      wide
      closeOnBackdrop={false}
      modalClassName="pf-modal-work-tracking"
      footer={
        <button type="button" className="pf-btn pf-btn-sm" onClick={onClose}>
          退出
        </button>
      }
    >
      {error ? <p className="pf-studio-ai-error pf-report-bind-error">{error}</p> : null}

      <div className="pf-work-track-tabs" role="tablist" aria-label="业务追踪状态">
        {TABS.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={`pf-studio-filter-chip pf-work-track-tab${tab === id ? " is-active" : ""}`}
            onClick={() => setTab(id)}
          >
            {TRACKING_STATUS_LABEL[id]}（{countFor(id)}条）
          </button>
        ))}
      </div>

      <div className="pf-work-track-list-wrap">
        {loading ? <div className="pf-report-bind-loading">加载追踪数据…</div> : null}
        <ul className="pf-work-track-list">
          {items.length === 0 && !loading ? (
            <li className="pf-work-track-empty">当前分类暂无已发布的业务</li>
          ) : (
            items.map((item) => <TrackingRow key={item.work_id} item={item} />)
          )}
        </ul>
      </div>
    </Modal>
  );
}
