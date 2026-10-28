import { apiBase, apiFetch, readApiError } from "../../api";

export type ReportPushSubscriptionRow = {
  user_id: string;
  account: string;
  name: string;
  status: string;
  work_ids: string[];
};

export type ReportPushWorkOption = {
  work_id: string;
  name: string;
};

export async function loadReportPushSubscriptions(): Promise<ReportPushSubscriptionRow[]> {
  const res = await apiFetch(`${apiBase()}/api/report-push/subscriptions`);
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { items: ReportPushSubscriptionRow[] };
  return data.items;
}

export async function saveReportPushSubscriptions(
  items: Array<{ user_id: string; work_ids: string[] }>,
): Promise<void> {
  const res = await apiFetch(`${apiBase()}/api/report-push/subscriptions`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  if (!res.ok) throw new Error(await readApiError(res));
}

export async function loadMyReportPushSubscription(): Promise<{
  work_ids: string[];
  has_subscription: boolean;
}> {
  const res = await apiFetch(`${apiBase()}/api/report-push/me`);
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { work_ids: string[]; has_subscription: boolean };
  return {
    work_ids: data.work_ids ?? [],
    has_subscription: Boolean(data.has_subscription),
  };
}
