export type PermissionDef = {
  id: string;
  name: string;
  module: string;
  moduleLabel: string;
  desc: string;
};

/** 权限元数据，与 auth/builtin_seed.json 中 permissions 字段对齐 */
export const PERMISSIONS: PermissionDef[] = [
  { id: "p-dash", name: "查看数据看板", module: "user", moduleLabel: "用户端 · 数据看板", desc: "访问巡检概览与统计" },
  { id: "p-trigger-task", name: "触发巡检任务", module: "user", moduleLabel: "用户端 · 数据看板", desc: "Agent 编排并触发综合业务巡检" },
  { id: "p-reports", name: "查看巡检报告", module: "user", moduleLabel: "用户端 · 数据看板", desc: "阅读运行报告" },
  { id: "p-events", name: "查看巡检事件", module: "user", moduleLabel: "用户端 · 数据看板", desc: "查看告警与事件列表" },
  { id: "p-inspection-view", name: "查看巡检业务展示", module: "user", moduleLabel: "用户端 · 巡检", desc: "浏览巡检业务展示结果" },
  { id: "p-inspection", name: "巡检业务管理", module: "admin", moduleLabel: "管理端 · 巡检", desc: "创建、编辑巡检业务" },
  { id: "p-device", name: "区域配置", module: "admin", moduleLabel: "管理端 · 资源", desc: "维护区域与接入设备" },
  { id: "p-knowledge", name: "知识库管理", module: "admin", moduleLabel: "管理端 · 资源", desc: "规范文档与条目维护" },
  { id: "p-algo", name: "算法管理", module: "admin", moduleLabel: "管理端 · 资源", desc: "导入与维护算法包" },
  { id: "p-perm", name: "权限配置", module: "admin", moduleLabel: "管理端 · 系统", desc: "用户页面访问授权（含 Hermes）" },
  { id: "p-logs", name: "日志管理", module: "admin", moduleLabel: "管理端 · 系统", desc: "查看平台与业务运行日志" },
  { id: "p-docs", name: "文档库", module: "admin", moduleLabel: "管理端 · 开发", desc: "文档上传与向量化" },
  { id: "p-workflow", name: "规范流程", module: "admin", moduleLabel: "管理端 · 开发", desc: "规范抽取演示流程" },
];

export type CreateUserDraft = {
  name: string;
  account: string;
  password: string;
  roleId: string;
};

export type CreateRoleDraft = {
  name: string;
  description: string;
};

export function emptyCreateUserDraft(): CreateUserDraft {
  return { name: "", account: "", password: "", roleId: "" };
}

export function emptyCreateRoleDraft(): CreateRoleDraft {
  return { name: "", description: "" };
}

export function normalizeAccount(account: string) {
  return account.trim().toLowerCase();
}

export function validatePassword(password: string): string | null {
  const value = password.trim();
  if (!value) return "请输入密码";
  if (value.length < 4) return "密码至少 4 位";
  if (value.length > 64) return "密码不超过 64 位";
  return null;
}

export function validatePasswordConfirm(password: string, confirm: string): string | null {
  const err = validatePassword(password);
  if (err) return err;
  if (password !== confirm) return "两次输入的密码不一致";
  return null;
}

/** 姓名：简体中文汉字、英文字母、数字 */
const USER_NAME_RE = /^[\u4e00-\u9fa5A-Za-z0-9]+$/;

export function validateUserName(name: string): string | null {
  const value = name.trim();
  if (!value) return "请填写用户姓名";
  if (!USER_NAME_RE.test(value)) return "姓名栏不允许非法字符";
  return null;
}

/** 登录账号：可打印 ASCII（不含空格），须字母或数字开头，且至少含一个字母或数字 */
const ACCOUNT_PRINTABLE_RE = /^[\x21-\x7E]+$/;
const ACCOUNT_START_RE = /^[A-Za-z0-9]/;
const ACCOUNT_HAS_ALNUM_RE = /[A-Za-z0-9]/;

export function validateLoginAccount(account: string, existingAccounts: string[] = []): string | null {
  const raw = account.trim();
  if (!raw) return "请填写登录账号";
  if (!ACCOUNT_START_RE.test(raw)) return "账号必须以字母或数字开头";
  if (!ACCOUNT_PRINTABLE_RE.test(raw)) return "登录账号含有非法字符";
  if (!ACCOUNT_HAS_ALNUM_RE.test(raw)) return "至少要有数字或者字母";
  const normalized = normalizeAccount(raw);
  if (existingAccounts.some((a) => normalizeAccount(a) === normalized)) {
    return "当前账号已存在，不允许重复";
  }
  return null;
}

export const DEFAULT_NEW_USER_PERMS: string[] = [];

const PERMISSION_ID_SET = new Set(PERMISSIONS.map((p) => p.id));

/** 仅统计权限矩阵中已定义的 id（忽略历史遗留如 p-hermes） */
export function knownPermissionIds(permissionIds: string[]): string[] {
  return permissionIds.filter((id) => PERMISSION_ID_SET.has(id));
}

export function isFullAdminUser(user: { status: string; permissions?: string[] }): boolean {
  if (user.status !== "active") return false;
  const set = new Set(knownPermissionIds(user.permissions ?? []));
  return PERMISSIONS.every((p) => set.has(p.id));
}

export function countFullAdminUsers(
  users: { user_id: string; status: string; permissions?: string[] }[],
  excludeUserId?: string,
): number {
  return users.filter(
    (u) => u.user_id !== excludeUserId && u.status === "active" && isFullAdminUser(u),
  ).length;
}

export function isLastFullAdminUser(
  user: { user_id: string; status: string; permissions?: string[] },
  users: { user_id: string; status: string; permissions?: string[] }[],
): boolean {
  return isFullAdminUser(user) && countFullAdminUsers(users, user.user_id) === 0;
}

export function permissionsByModule(perms: PermissionDef[]) {
  const map = new Map<string, { label: string; side: "user" | "admin"; items: PermissionDef[] }>();
  for (const p of perms) {
    let g = map.get(p.moduleLabel);
    if (!g) {
      g = { label: p.moduleLabel, side: p.module === "user" ? "user" : "admin", items: [] };
      map.set(p.moduleLabel, g);
    }
    g.items.push(p);
  }
  const order = ["用户端 · 数据看板", "用户端 · 巡检", "管理端 · 巡检", "管理端 · 资源", "管理端 · 系统", "管理端 · 开发"];
  return [...map.entries()]
    .sort(([a], [b]) => {
      const ia = order.indexOf(a);
      const ib = order.indexOf(b);
      if (ia === -1 && ib === -1) return a.localeCompare(b);
      if (ia === -1) return 1;
      if (ib === -1) return -1;
      return ia - ib;
    })
    .map(([module, data]) => ({
      module,
      label: data.label,
      side: data.side,
      icon: moduleIcon(module),
      items: data.items,
    }));
}

export function moduleIcon(moduleLabel: string) {
  if (moduleLabel.includes("数据看板")) return "◈";
  if (moduleLabel.includes("业务") && moduleLabel.startsWith("用户")) return "◉";
  if (moduleLabel.includes("业务")) return "⚙";
  if (moduleLabel.includes("资源")) return "⊡";
  if (moduleLabel.includes("系统")) return "⛨";
  if (moduleLabel.includes("开发")) return "⌘";
  return "◫";
}

export const PERM_PRESETS = [
  { id: "readonly", name: "只看板", desc: "用户端只读", ids: ["p-dash", "p-trigger-task", "p-reports", "p-events", "p-inspection-view"] },
  { id: "ops", name: "运维配置", desc: "巡检业务与资源维护", ids: ["p-dash", "p-trigger-task", "p-reports", "p-events", "p-inspection-view", "p-inspection", "p-device", "p-knowledge", "p-algo", "p-logs"] },
  { id: "full", name: "全部权限", desc: "管理端 + 用户端", ids: PERMISSIONS.map((p) => p.id) },
] as const;
