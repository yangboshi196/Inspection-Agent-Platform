export const ROUTE_PERMISSIONS: Record<string, string> = {
  "/user/dashboard": "p-dash",
  "/user/assistant": "p-trigger-task",
  "/user/trigger-tasks": "p-trigger-task",
  "/user/reports": "p-reports",
  "/user/events": "p-events",
  "/user/works": "p-inspection-view",
  "/admin/inspection-works": "p-inspection",
  "/admin/devices": "p-device",
  "/admin/knowledge": "p-knowledge",
  "/admin/reports": "p-reports",
  "/admin/algorithms": "p-algo",
  "/admin/permissions": "p-perm",
  "/admin/logs": "p-logs",
  "/admin/hermes-agent": "p-perm",
  "/admin/regions": "p-device",
  "/chat": "p-workflow",
  "/docs": "p-docs",
  "/workflow": "p-workflow",
};

export function permissionForPath(pathname: string): string | null {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (ROUTE_PERMISSIONS[path]) return ROUTE_PERMISSIONS[path];
  if (path.startsWith("/admin/regions")) return "p-device";
  if (path.startsWith("/admin/hermes-agent")) return "p-perm";
  if (path.startsWith("/admin/logs")) return "p-logs";
  return null;
}
