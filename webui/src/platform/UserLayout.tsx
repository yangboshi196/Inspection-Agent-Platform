import { NavLink, Outlet, Link } from "react-router-dom";

import { useAuth } from "./AuthContext";

import { ReportDataProvider } from "./dataCenter/ReportDataContext";



type NavItem = {
  to: string;
  label: string;
  icon: string;
  perm: string;
  end?: boolean;
};

const NAV: NavItem[] = [
  { to: "/user/dashboard", end: true, label: "数据看板", icon: "◈", perm: "p-dash" },
  { to: "/user/assistant", label: "智能巡检助手", icon: "✦", perm: "p-trigger-task" },
  { to: "/user/reports", label: "巡检报告", icon: "⊞", perm: "p-reports" },
  { to: "/user/events", label: "巡检事件", icon: "◫", perm: "p-events" },
  { to: "/user/works", label: "巡检业务", icon: "◉", perm: "p-inspection-view" },
];



export function UserLayout() {

  const { hasPermission, user } = useAuth();

  const visibleNav = NAV.filter((item) => {
    if (item.to === "/user/assistant") {
      return hasPermission("p-trigger-task") || hasPermission("p-dash");
    }
    return hasPermission(item.perm);
  });



  return (

    <div className="layout">

      <aside className="sidebar">

        <div className="sidebar-brand">

          <span className="sidebar-logo">看</span>

          <div className="sidebar-brand-text">

            <strong>
              用户看板{user?.name || user?.account ? `（${user.name || user.account}）` : ""}
            </strong>

          </div>

        </div>

        <nav className="nav">

          {visibleNav.map((item) => (

            <NavLink key={item.to} to={item.to} end={item.end === true}>

              <span className="nav-icon" aria-hidden>

                {item.icon}

              </span>

              {item.label}

            </NavLink>

          ))}

        </nav>

        <div className="sidebar-foot">

          <Link to="/portal" className="pf-nav-portal-link">

            返回入口

          </Link>

        </div>

      </aside>

      <div className="pf-user-main">

        <ReportDataProvider>

          <Outlet />

        </ReportDataProvider>

      </div>

    </div>

  );

}

