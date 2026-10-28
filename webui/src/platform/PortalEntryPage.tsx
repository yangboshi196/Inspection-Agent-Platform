import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { canAccessAdminPortal, canAccessUserPortal } from "./auth";

const USER_FEATURES = [
  "数据看板与运行 KPI",
  "巡检报告与周期归档",
  "巡检事件与告警跟踪",
  "巡检业务全景与现状浏览",
];

const ADMIN_FEATURES = [
  "巡检业务编排与调度",
  "区域配置与设备接入",
  "规范安全知识库维护",
  "算法包导入与健康监测",
];

export function PortalEntryPage() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const showUser = canAccessUserPortal(user);
  const showAdmin = canAccessAdminPortal(user);

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="pf-portal">
      <header className="pf-portal-topbar">
        <div className="pf-portal-topbar-user">
          <span className="pf-portal-topbar-label">当前账号</span>
          <strong>
            {user?.name ?? user?.account ?? "访客"}
            {user?.permissions?.length ? ` · ${user.permissions.length} 项权限` : ""}
          </strong>
        </div>
        <button type="button" className="pf-portal-logout" onClick={() => void handleLogout()}>
          退出登录
        </button>
      </header>

      <main className="pf-portal-stage">
        <section className="pf-portal-brand" aria-label="平台标识">
          <div className="pf-portal-brand-mark">巡</div>
          <h1>安全生产智能巡检系统</h1>
          <p className="pf-portal-brand-en">Safety Production Intelligent Inspection System</p>
          <span className="pf-portal-brand-hint">请选择访问入口</span>
        </section>

        <div className="pf-portal-gates">
          {showUser ? (
            <Link to="/user/dashboard" className="pf-portal-gate pf-portal-gate-user">
              <div className="pf-portal-gate-head">
                <span className="pf-portal-gate-icon" aria-hidden>
                  ◈
                </span>
                <span className="pf-portal-gate-tag">User Portal</span>
              </div>
              <div className="pf-portal-gate-body">
                <h2>用户看板</h2>
                <p>面向运营与监管人员，查看巡检报告、工单流转、事件处置与合规态势。</p>
                <ul className="pf-portal-gate-list">
                  {USER_FEATURES.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              </div>
              <span className="pf-portal-gate-cta">
                进入看板
                <span aria-hidden>→</span>
              </span>
            </Link>
          ) : null}

          {showAdmin ? (
            <Link to="/admin/inspection-works" className="pf-portal-gate pf-portal-gate-admin">
              <div className="pf-portal-gate-head">
                <span className="pf-portal-gate-icon" aria-hidden>
                  ⚙
                </span>
                <span className="pf-portal-gate-tag">Admin Console</span>
              </div>
              <div className="pf-portal-gate-body">
                <h2>管理控制台</h2>
                <p>面向巡检配置与运维人员，维护巡检业务规则、用户权限、系统资源与算法能力。</p>
                <ul className="pf-portal-gate-list">
                  {ADMIN_FEATURES.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              </div>
              <span className="pf-portal-gate-cta">
                进入管理
                <span aria-hidden>→</span>
              </span>
            </Link>
          ) : null}

          {!showUser && !showAdmin ? (
            <div className="pf-portal-gate pf-portal-gate-static">
              <p>当前账号未分配任何页面权限，请联系管理员。</p>
            </div>
          ) : null}
        </div>
      </main>
    </div>
  );
}
