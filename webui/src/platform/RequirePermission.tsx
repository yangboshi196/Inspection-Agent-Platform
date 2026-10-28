import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { PermissionDeniedPage } from "./PermissionDeniedPage";
import { permissionForPath } from "./permissionRoutes";

type RequirePermissionProps = {
  children: React.ReactNode;
  perm?: string;
  /** 为 true 时无权限跳转 fallback；默认展示无权限提示页 */
  redirect?: boolean;
  fallback?: string;
};

export function RequirePermission({
  children,
  perm,
  redirect = false,
  fallback = "/portal",
}: RequirePermissionProps) {
  const { hasPermission, loading, isAuthenticated } = useAuth();
  const location = useLocation();

  if (loading) {
    return <div className="pf-usr-status">正在验证权限…</div>;
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  const required = perm ?? permissionForPath(location.pathname);
  if (required && !hasPermission(required)) {
    return redirect ? <Navigate to={fallback} replace /> : <PermissionDeniedPage />;
  }
  return children;
}
