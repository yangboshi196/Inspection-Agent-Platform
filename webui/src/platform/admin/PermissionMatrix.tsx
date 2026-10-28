import type { ReactNode } from "react";
import { PERM_PRESETS, PERMISSIONS, knownPermissionIds, permissionsByModule } from "./permissionMock";

const MODULE_GROUPS = permissionsByModule(PERMISSIONS);

type Props = {
  permissionIds: string[];
  saving?: boolean;
  readOnly?: boolean;
  activePresetId: string | null;
  onToggle: (permId: string) => void;
  onApplyPreset: (presetId: string) => void;
  footnote: string;
};

function samePermSet(a: string[], b: string[]) {
  if (a.length !== b.length) return false;
  const sa = [...a].sort();
  const sb = [...b].sort();
  return sa.every((id, i) => id === sb[i]);
}

export function permCoverage(permissionIds: string[]) {
  const matched = knownPermissionIds(permissionIds);
  const total = PERMISSIONS.length;
  const count = matched.length;
  return { count, total, pct: total ? Math.min(100, Math.round((count / total) * 100)) : 0 };
}

export function portalCounts(permissionIds: string[]) {
  let userPortal = 0;
  let adminPortal = 0;
  for (const id of knownPermissionIds(permissionIds)) {
    const p = PERMISSIONS.find((x) => x.id === id);
    if (p?.module === "user") userPortal += 1;
    if (p?.module === "admin") adminPortal += 1;
  }
  return { userPortal, adminPortal };
}

export function resolveActivePresetId(permissionIds: string[]) {
  const known = knownPermissionIds(permissionIds);
  for (const preset of PERM_PRESETS) {
    if (samePermSet(known, [...preset.ids])) return preset.id;
  }
  return null;
}

export function PermissionHeroStats({
  title,
  subtitle,
  avatarText,
  permissionIds,
}: {
  title: string;
  subtitle: ReactNode;
  avatarText: string;
  permissionIds: string[];
}) {
  const coverage = permCoverage(permissionIds);
  const counts = portalCounts(permissionIds);
  return (
    <div className="pf-perm-user-hero">
      <div className="pf-perm-user-hero-main">
        <span className="pf-perm-user-avatar pf-perm-user-avatar-lg" aria-hidden>
          {avatarText.slice(0, 1)}
        </span>
        <div className="pf-perm-user-hero-text">
          <h2>{title}</h2>
          <p>{subtitle}</p>
        </div>
      </div>
      <div className="pf-perm-user-hero-stats">
        <div className="pf-perm-hero-stat pf-perm-hero-stat-blue">
          <strong>{counts.userPortal}</strong>
          <span>用户端</span>
        </div>
        <div className="pf-perm-hero-stat pf-perm-hero-stat-purple">
          <strong>{counts.adminPortal}</strong>
          <span>管理端</span>
        </div>
        <div className="pf-perm-hero-stat pf-perm-hero-stat-green">
          <strong>{coverage.pct}%</strong>
          <span>覆盖率</span>
        </div>
      </div>
      <div className="pf-perm-coverage-wrap">
        <div className="pf-perm-coverage-head">
          <span>页面权限覆盖</span>
          <span>
            {coverage.count}/{coverage.total}
          </span>
        </div>
        <div className="pf-perm-coverage-bar">
          <span className="pf-perm-coverage-fill" style={{ width: `${coverage.pct}%` }} />
        </div>
      </div>
    </div>
  );
}

export function PermissionMatrix({
  permissionIds,
  saving = false,
  readOnly = false,
  activePresetId,
  onToggle,
  onApplyPreset,
  footnote,
}: Props) {
  const selectedPermSet = new Set(knownPermissionIds(permissionIds));
  const disabled = saving || readOnly;
  return (
    <>
      <div className="pf-perm-toolbar">
        <div className="pf-perm-preset-row">
          <span className="pf-perm-preset-label">快捷模板</span>
          {PERM_PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              className={`pf-perm-preset-chip${activePresetId === preset.id ? " is-active" : ""}`}
              disabled={disabled}
              title={preset.desc}
              onClick={() => onApplyPreset(preset.id)}
            >
              {preset.name}
            </button>
          ))}
        </div>
      </div>
      <div className={`pf-perm-matrix${readOnly ? " is-readonly" : ""}`}>
        {MODULE_GROUPS.map((group) => {
          const ids = group.items.map((p) => p.id);
          const checkedCount = ids.filter((id) => selectedPermSet.has(id)).length;
          return (
            <div key={group.module} className={`pf-perm-module pf-perm-module-${group.side}`}>
              <div className="pf-perm-module-head">
                <span className="pf-perm-module-icon" aria-hidden>
                  {group.icon}
                </span>
                <span className="pf-perm-module-title">
                  <strong>{group.label}</strong>
                  <em>{group.side === "user" ? "用户端门户" : "管理端后台"}</em>
                </span>
                <span className="pf-perm-module-count">
                  {checkedCount}/{ids.length}
                </span>
              </div>
              <ul className="pf-perm-perm-list">
                {group.items.map((p) => {
                  const checked = selectedPermSet.has(p.id);
                  return (
                    <li key={p.id}>
                      <button
                        type="button"
                        className={`pf-perm-perm-item${checked ? " is-checked" : ""}`}
                              disabled={disabled}
                              onClick={() => onToggle(p.id)}
                      >
                        <span className="pf-perm-perm-text">
                          <strong>{p.name}</strong>
                          <em>{p.desc}</em>
                        </span>
                        <span className={`pf-perm-perm-tag pf-perm-perm-tag-${p.module}`}>
                          {checked ? "已授权" : "点击授权"}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>
      <p className="pf-perm-matrix-foot">{footnote}</p>
    </>
  );
}
