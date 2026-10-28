import { NavLink, Outlet, Link } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { HERMES_TABS } from "./hermesAgent";

const NAV = [
  { to: "/admin/regions", label: "区域配置", icon: "◎", perm: "p-device" },
  { to: "/admin/inspection-works", label: "巡检业务", icon: "◉", perm: "p-inspection" },
  { to: "/admin/knowledge", label: "知识库", icon: "⊟", perm: "p-knowledge" },
  { to: "/admin/reports", label: "报告管理", icon: "▤", perm: "p-reports" },
  { to: "/admin/algorithms", label: "算法管理", icon: "⊠", perm: "p-algo" },
  { to: "/admin/permissions", label: "用户权限", icon: "⛨", perm: "p-perm" },
  { to: "/admin/logs", label: "日志管理", icon: "≣", perm: "p-logs" },
] as const;

const SECONDARY_NAV: Array<{ to: string; label: string; icon: string; perm: "p-perm" }> = HERMES_TABS.map((tab) => ({
  to: `/admin/hermes-agent/${tab.slug}`,
  label: tab.label,
  icon: tab.icon,
  perm: "p-perm",
}));

export function AdminLayout() {
  const { hasPermission } = useAuth();
  const visibleNav = NAV.filter((item) => hasPermission(item.perm));
  const visibleSecondary = SECONDARY_NAV.filter((item) => hasPermission(item.perm));

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="sidebar-logo">管</span>
          <div className="sidebar-brand-text">
            <strong>管理控制台</strong>
            <small>配置与维护</small>
          </div>
        </div>
        <nav className="nav">
          {visibleNav.map((item) => (
            <NavLink key={item.to} to={item.to}>
              <span className="nav-icon" aria-hidden>
                {item.icon}
              </span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        {visibleSecondary.length > 0 ? (
          <nav className="nav nav-secondary" aria-label="Hermes Dashboard">
            {visibleSecondary.map((item) => (
              <NavLink key={item.to} to={item.to} end={false}>
                <span className="nav-icon" aria-hidden>
                  {item.icon}
                </span>
                {item.label}
              </NavLink>
            ))}
          </nav>
        ) : null}
        <div className="sidebar-foot">
          <Link to="/portal" className="pf-nav-portal-link">
            返回入口
          </Link>
        </div>
      </aside>
      <div className="pf-admin-main">
        <Outlet />
      </div>
    </div>
  );
}
