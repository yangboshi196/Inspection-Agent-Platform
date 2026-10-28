import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "../components/Badge";
import { Modal } from "../components/Modal";
import {
  createAuthRole,
  createAuthUser,
  deleteAuthRole,
  deleteAuthUser,
  loadAuthRoles,
  loadAuthUsers,
  patchAuthRole,
  patchAuthUser,
  type AuthRoleRow,
  type AuthUserRow,
} from "../authApi";
import {
  emptyCreateRoleDraft,
  emptyCreateUserDraft,
  isLastFullAdminUser,
  knownPermissionIds,
  normalizeAccount,
  PERM_PRESETS,
  PERMISSIONS,
  validatePassword,
  validatePasswordConfirm,
  validateLoginAccount,
  validateUserName,
  type CreateRoleDraft,
  type CreateUserDraft,
} from "./permissionMock";
import {
  PermissionHeroStats,
  PermissionMatrix,
  permCoverage,
  resolveActivePresetId,
} from "./PermissionMatrix";
import { RoleSelect } from "./RoleSelect";

type StatusFilter = "all" | "active" | "disabled";
type SidebarTab = "users" | "roles";

type PasswordDraft = {
  password: string;
  confirm: string;
};

function emptyPasswordDraft(): PasswordDraft {
  return { password: "", confirm: "" };
}

export function PermissionConfigPage() {
  const [users, setUsers] = useState<AuthUserRow[]>([]);
  const [roles, setRoles] = useState<AuthRoleRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>("users");
  const [selectedUserId, setSelectedUserId] = useState("");
  const [selectedRoleId, setSelectedRoleId] = useState("");
  const [userKw, setUserKw] = useState("");
  const [roleKw, setRoleKw] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [hint, setHint] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [createRoleOpen, setCreateRoleOpen] = useState(false);
  const [createUserError, setCreateUserError] = useState("");
  const [createDraft, setCreateDraft] = useState<CreateUserDraft>(emptyCreateUserDraft);
  const [createRoleDraft, setCreateRoleDraft] = useState<CreateRoleDraft>(emptyCreateRoleDraft);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [passwordDraft, setPasswordDraft] = useState<PasswordDraft>(emptyPasswordDraft);
  const [roleNameDraft, setRoleNameDraft] = useState("");
  const [roleDescDraft, setRoleDescDraft] = useState("");
  const [saving, setSaving] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    let userRows: AuthUserRow[] = [];
    let roleRows: AuthRoleRow[] = [];
    let errMsg = "";
    try {
      userRows = await loadAuthUsers();
    } catch (e) {
      errMsg = String(e);
    }
    try {
      roleRows = await loadAuthRoles();
    } catch (e) {
      const roleErr = String(e);
      if (!errMsg) {
        errMsg =
          roleErr.includes("404") || roleErr.includes("Not Found")
            ? "角色接口未就绪，请重启后端服务后再试「新建角色」"
            : roleErr;
      }
    }
    setUsers(userRows);
    setRoles(roleRows);
    setSelectedUserId((prev) => {
      if (prev && userRows.some((u) => u.user_id === prev)) return prev;
      return userRows[0]?.user_id ?? "";
    });
    setSelectedRoleId((prev) => {
      if (prev && roleRows.some((r) => r.role_id === prev)) return prev;
      return roleRows[0]?.role_id ?? "";
    });
    if (errMsg && userRows.length === 0) setHint(errMsg);
    else if (errMsg) setHint(`${errMsg}（用户列表已加载）`);
    setLoading(false);
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const stats = useMemo(() => {
    const activeUsers = users.filter((u) => u.status === "active").length;
    return {
      users: users.length,
      roles: roles.length,
      activeUsers,
      configured: users.filter((u) => (u.permissions ?? []).length > 0).length,
      permissions: PERMISSIONS.length,
    };
  }, [users, roles]);

  const selectedUser = users.find((u) => u.user_id === selectedUserId) ?? null;
  const selectedRole = roles.find((r) => r.role_id === selectedRoleId) ?? null;

  useEffect(() => {
    if (!selectedRole) {
      setRoleNameDraft("");
      setRoleDescDraft("");
      return;
    }
    setRoleNameDraft(selectedRole.name);
    setRoleDescDraft(selectedRole.description ?? "");
  }, [selectedRole?.role_id, selectedRole?.name, selectedRole?.description]);

  const filteredUsers = useMemo(() => {
    const q = userKw.trim().toLowerCase();
    return users.filter((u) => {
      if (statusFilter === "active" && u.status !== "active") return false;
      if (statusFilter === "disabled" && u.status !== "disabled") return false;
      if (!q) return true;
      return [u.name, u.account, u.role_name ?? "", String((u.permissions ?? []).length)]
        .join(" ")
        .toLowerCase()
        .includes(q);
    });
  }, [users, userKw, statusFilter]);

  const filteredRoles = useMemo(() => {
    const q = roleKw.trim().toLowerCase();
    return roles.filter((r) => {
      if (!q) return true;
      return [r.name, r.description ?? "", String((r.permissions ?? []).length)]
        .join(" ")
        .toLowerCase()
        .includes(q);
    });
  }, [roles, roleKw]);

  const openCreateModal = () => {
    setCreateDraft(emptyCreateUserDraft());
    setCreateUserError("");
    setCreateOpen(true);
    setHint("");
  };

  const closeCreateModal = () => {
    setCreateOpen(false);
    setCreateDraft(emptyCreateUserDraft());
    setCreateUserError("");
  };

  const openPasswordModal = () => {
    setPasswordDraft(emptyPasswordDraft());
    setPasswordOpen(true);
    setHint("");
  };

  const closePasswordModal = () => {
    setPasswordOpen(false);
    setPasswordDraft(emptyPasswordDraft());
  };

  const openCreateRoleModal = () => {
    setCreateRoleDraft(emptyCreateRoleDraft());
    setCreateRoleOpen(true);
    setHint("");
  };

  const closeCreateRoleModal = () => {
    setCreateRoleOpen(false);
    setCreateRoleDraft(emptyCreateRoleDraft());
  };

  const submitCreateRole = async () => {
    const name = createRoleDraft.name.trim();
    if (!name) {
      setHint("请填写角色名称");
      return;
    }
    setSaving(true);
    try {
      const saved = await createAuthRole({
        name,
        description: createRoleDraft.description.trim(),
      });
      setRoles((list) => [...list, saved]);
      setSelectedRoleId(saved.role_id);
      setSidebarTab("roles");
      closeCreateRoleModal();
      setHint(`已创建角色「${saved.name}」，请在右侧配置页面权限`);
    } catch (e) {
      setHint(String(e));
    } finally {
      setSaving(false);
    }
  };

  const saveRoleMeta = async () => {
    if (!selectedRole) return;
    const name = roleNameDraft.trim();
    if (!name) {
      setHint("角色名称不能为空");
      return;
    }
    setSaving(true);
    try {
      const saved = await patchAuthRole(selectedRole.role_id, {
        name,
        description: roleDescDraft.trim(),
      });
      setRoles((list) => list.map((r) => (r.role_id === saved.role_id ? saved : r)));
      setUsers((list) =>
        list.map((u) =>
          u.role_id === saved.role_id ? { ...u, role_name: saved.name, permissions: saved.permissions } : u,
        ),
      );
      setHint(`已更新角色「${saved.name}」`);
    } catch (e) {
      setHint(String(e));
    } finally {
      setSaving(false);
    }
  };

  const saveRolePermissions = async (nextPermissions: string[], message: string) => {
    if (!selectedRole) return;
    setSaving(true);
    try {
      const saved = await patchAuthRole(selectedRole.role_id, { permissions: nextPermissions });
      setRoles((list) => list.map((r) => (r.role_id === saved.role_id ? saved : r)));
      setUsers((list) =>
        list.map((u) => (u.role_id === saved.role_id ? { ...u, permissions: saved.permissions } : u)),
      );
      setHint(message);
    } catch (e) {
      setHint(String(e));
    } finally {
      setSaving(false);
    }
  };

  const toggleRolePermission = async (permId: string) => {
    if (!selectedRole || saving) return;
    const next = new Set(selectedRole.permissions ?? []);
    if (next.has(permId)) next.delete(permId);
    else next.add(permId);
    await saveRolePermissions([...next].sort(), `已更新角色「${selectedRole.name}」的页面权限`);
  };

  const applyRolePreset = async (presetId: string) => {
    const preset = PERM_PRESETS.find((p) => p.id === presetId);
    if (!selectedRole || !preset || saving) return;
    await saveRolePermissions([...preset.ids], `已为角色「${selectedRole.name}」应用「${preset.name}」`);
  };

  const assignUserRole = async (roleId: string) => {
    if (!selectedUser || saving || userLockedAsLastFullAdmin) return;
    if (selectedUser.role_id === roleId) return;
    setSaving(true);
    try {
      const saved = await patchAuthUser(selectedUser.user_id, { role_id: roleId });
      setUsers((list) => list.map((u) => (u.user_id === saved.user_id ? saved : u)));
      setHint(`已将用户「${selectedUser.name}」的角色设为「${saved.role_name ?? roleId}」`);
    } catch (e) {
      setHint(String(e));
    } finally {
      setSaving(false);
    }
  };

  const changeUserPassword = async () => {
    if (!selectedUser) return;
    const err = validatePasswordConfirm(passwordDraft.password, passwordDraft.confirm);
    if (err) {
      setHint(err);
      return;
    }
    setSaving(true);
    try {
      const saved = await patchAuthUser(selectedUser.user_id, { password: passwordDraft.password });
      setUsers((list) => list.map((u) => (u.user_id === saved.user_id ? saved : u)));
      closePasswordModal();
      setHint(`已更新用户「${selectedUser.name}」的登录密码`);
    } catch (e) {
      setHint(String(e));
    } finally {
      setSaving(false);
    }
  };

  const createUser = async () => {
    const name = createDraft.name.trim();
    const account = normalizeAccount(createDraft.account);
    const password = createDraft.password;

    const nameErr = validateUserName(name);
    if (nameErr) {
      setCreateUserError(nameErr);
      return;
    }
    const accountErr = validateLoginAccount(
      createDraft.account,
      users.map((u) => u.account),
    );
    if (accountErr) {
      setCreateUserError(accountErr);
      return;
    }
    const passwordErr = validatePassword(password);
    if (passwordErr) {
      setCreateUserError(passwordErr);
      return;
    }
    if (!createDraft.roleId) {
      setCreateUserError("请选择角色");
      return;
    }

    setCreateUserError("");
    setSaving(true);
    try {
      const saved = await createAuthUser({
        account,
        name,
        password,
        status: "active",
        role_id: createDraft.roleId,
        permissions: [],
      });
      setUsers((list) => [...list, saved]);
      setSelectedUserId(saved.user_id);
      setSidebarTab("users");
      closeCreateModal();
      setHint(`已创建用户「${name}」并绑定角色「${saved.role_name ?? ""}」`);
    } catch (e) {
      const msg = String(e);
      if (msg.includes("已存在") || msg.includes("409")) {
        setCreateUserError("当前账号已存在，不允许重复");
      } else {
        setCreateUserError(msg.replace(/^Error:\s*/, ""));
      }
    } finally {
      setSaving(false);
    }
  };

  const deleteUser = async (user: AuthUserRow) => {
    if (!window.confirm(`确定删除用户「${user.name}」？`)) return;
    setSaving(true);
    try {
      await deleteAuthUser(user.user_id);
      const nextUsers = users.filter((u) => u.user_id !== user.user_id);
      setUsers(nextUsers);
      if (selectedUserId === user.user_id) {
        setSelectedUserId(nextUsers[0]?.user_id ?? "");
      }
      setHint(nextUsers.length ? `已删除用户「${user.name}」` : "已删除全部用户，请新建用户");
    } catch (e) {
      setHint(String(e));
    } finally {
      setSaving(false);
    }
  };

  const deleteRole = async (role: AuthRoleRow) => {
    if (!window.confirm(`确定删除角色「${role.name}」？`)) return;
    setSaving(true);
    try {
      await deleteAuthRole(role.role_id);
      const nextRoles = roles.filter((r) => r.role_id !== role.role_id);
      setRoles(nextRoles);
      if (selectedRoleId === role.role_id) {
        setSelectedRoleId(nextRoles[0]?.role_id ?? "");
      }
      await reload();
      setHint(nextRoles.length ? `已删除角色「${role.name}」` : "已删除全部角色");
    } catch (e) {
      setHint(String(e));
    } finally {
      setSaving(false);
    }
  };

  const toggleUserStatus = async () => {
    if (!selectedUser || userLockedAsLastFullAdmin) return;
    const nextStatus = selectedUser.status === "active" ? "disabled" : "active";
    setSaving(true);
    try {
      const saved = await patchAuthUser(selectedUser.user_id, { status: nextStatus });
      setUsers((list) => list.map((u) => (u.user_id === saved.user_id ? saved : u)));
      setHint(`已${nextStatus === "active" ? "启用" : "停用"}账号「${selectedUser.name}」`);
    } catch (e) {
      setHint(String(e));
    } finally {
      setSaving(false);
    }
  };

  const selectedRoleActivePreset = selectedRole
    ? resolveActivePresetId(selectedRole.permissions ?? [])
    : null;
  const userLockedAsLastFullAdmin = Boolean(
    selectedUser && isLastFullAdminUser(selectedUser, users),
  );

  return (
    <div className="pf-scroll pf-perm-page">
      <header className="pf-perm-top-bar">
        <div className="pf-perm-top-left">
          <div className="pf-perm-title-block">
            <span className="pf-perm-title-mark" aria-hidden>
              ⛨
            </span>
            <h1>权限配置</h1>
          </div>
          <div className="pf-perm-metrics" aria-label="权限统计">
            <span className="pf-perm-metric pf-perm-metric-blue">
              <strong>{stats.users}</strong>
              <em>用户</em>
            </span>
            <span className="pf-perm-metric pf-perm-metric-purple">
              <strong>{stats.roles}</strong>
              <em>角色</em>
            </span>
            <span className="pf-perm-metric pf-perm-metric-green">
              <strong>{stats.activeUsers}</strong>
              <em>启用</em>
            </span>
            <span className="pf-perm-metric pf-perm-metric-orange">
              <strong>{stats.permissions}</strong>
              <em>页面权限</em>
            </span>
          </div>
        </div>
        <div className="pf-perm-header-actions">
          <button
            type="button"
            className="pf-btn pf-btn-primary"
            onClick={openCreateRoleModal}
            disabled={loading || saving}
          >
            新建角色
          </button>
          <button type="button" className="pf-btn pf-btn-primary" onClick={openCreateModal} disabled={loading}>
            新建用户
          </button>
        </div>
      </header>

      {hint ? <div className="pf-perm-status">{hint}</div> : null}
      {loading ? <div className="pf-perm-status">加载用户与角色…</div> : null}

      <div className="pf-perm-layout">
        <aside className="pf-panel pf-perm-sidebar">
          <div className="pf-perm-sidebar-tabs">
            {(
              [
                ["users", "用户列表"],
                ["roles", "角色列表"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={`pf-perm-filter-chip${sidebarTab === id ? " is-active" : ""}`}
                onClick={() => setSidebarTab(id)}
              >
                {label}
              </button>
            ))}
          </div>

          {sidebarTab === "users" ? (
            <>
              <div className="pf-perm-sidebar-head">
                <div className="pf-perm-sidebar-head-top">
                  <h2 className="pf-perm-section-title">用户列表</h2>
                  <div className="pf-perm-sidebar-head-actions">
                    <span className="pf-perm-sidebar-meta">
                      {filteredUsers.length}/{users.length}
                    </span>
                    <button type="button" className="pf-btn pf-btn-sm" onClick={openCreateModal}>
                      新建
                    </button>
                  </div>
                </div>
                <input
                  type="search"
                  className="pf-cell-input pf-perm-search pf-perm-sidebar-search"
                  placeholder="搜索姓名、账号、角色…"
                  value={userKw}
                  onChange={(e) => setUserKw(e.target.value)}
                />
                <div className="pf-perm-filter-row">
                  {(
                    [
                      ["all", "全部"],
                      ["active", "启用"],
                      ["disabled", "停用"],
                    ] as const
                  ).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      className={`pf-perm-filter-chip${statusFilter === id ? " is-active" : ""}`}
                      onClick={() => setStatusFilter(id)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <ul className="pf-perm-user-list">
                {filteredUsers.length === 0 ? (
                  <li className="pf-perm-user-list-empty">
                    {users.length === 0 ? (
                      <>
                        <p>暂无用户</p>
                        <button type="button" className="pf-btn pf-btn-sm pf-btn-primary" onClick={openCreateModal}>
                          新建用户
                        </button>
                      </>
                    ) : (
                      "未找到匹配用户"
                    )}
                  </li>
                ) : (
                  filteredUsers.map((user) => {
                    const cov = permCoverage(user.permissions ?? []);
                    return (
                      <li key={user.user_id}>
                        <button
                          type="button"
                          className={`pf-perm-user-item${selectedUser?.user_id === user.user_id ? " is-active" : ""}`}
                          onClick={() => {
                            setSelectedUserId(user.user_id);
                            setSidebarTab("users");
                            setHint("");
                          }}
                        >
                          <span className="pf-perm-user-avatar" aria-hidden>
                            {user.name.slice(0, 1)}
                          </span>
                          <span className="pf-perm-user-item-body">
                            <span className="pf-perm-user-item-top">
                              <strong>{user.name}</strong>
                              <span className="pf-perm-user-item-badges">
                                <span className={`pf-perm-role-tag${user.role_name ? "" : " is-empty"}`}>
                                  {user.role_name ?? "未分配角色"}
                                </span>
                                <Badge tone={user.status === "active" ? "success" : "draft"}>
                                  {user.status === "active" ? "启用" : "停用"}
                                </Badge>
                              </span>
                            </span>
                            <span className="pf-perm-user-item-meta">
                              <code>{user.account}</code>
                              <span>{cov.count} 项权限</span>
                            </span>
                            <span className="pf-perm-user-item-bar" aria-hidden>
                              <span className="pf-perm-user-item-bar-fill" style={{ width: `${cov.pct}%` }} />
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })
                )}
              </ul>
            </>
          ) : (
            <>
              <div className="pf-perm-sidebar-head">
                <div className="pf-perm-sidebar-head-top">
                  <h2 className="pf-perm-section-title">角色列表</h2>
                  <div className="pf-perm-sidebar-head-actions">
                    <span className="pf-perm-sidebar-meta">
                      {filteredRoles.length}/{roles.length}
                    </span>
                    <button type="button" className="pf-btn pf-btn-sm" onClick={openCreateRoleModal} disabled={saving}>
                      新建
                    </button>
                  </div>
                </div>
                <input
                  type="search"
                  className="pf-cell-input pf-perm-search pf-perm-sidebar-search"
                  placeholder="搜索角色名称…"
                  value={roleKw}
                  onChange={(e) => setRoleKw(e.target.value)}
                />
              </div>
              <ul className="pf-perm-role-list">
                {filteredRoles.length === 0 ? (
                  <li className="pf-perm-user-list-empty">
                    {roles.length === 0 ? (
                      <>
                        <p>暂无角色</p>
                        <button
                          type="button"
                          className="pf-btn pf-btn-sm pf-btn-primary"
                          onClick={openCreateRoleModal}
                          disabled={saving}
                        >
                          新建角色
                        </button>
                      </>
                    ) : (
                      "未找到匹配角色"
                    )}
                  </li>
                ) : (
                  filteredRoles.map((role) => {
                    const cov = permCoverage(role.permissions ?? []);
                    return (
                      <li key={role.role_id}>
                        <button
                          type="button"
                          className={`pf-perm-role-item${selectedRole?.role_id === role.role_id ? " is-active" : ""}`}
                          onClick={() => {
                            setSelectedRoleId(role.role_id);
                            setSidebarTab("roles");
                            setHint("");
                          }}
                        >
                          <span className="pf-perm-user-avatar" aria-hidden>
                            {role.name.slice(0, 1)}
                          </span>
                          <span className="pf-perm-user-item-body">
                            <span className="pf-perm-role-item-top">
                              <strong>{role.name}</strong>
                            </span>
                            {role.description ? <p>{role.description}</p> : null}
                            <span className="pf-perm-role-item-meta">
                              <span>{cov.count} 项权限</span>
                              <span>{cov.pct}% 覆盖</span>
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })
                )}
              </ul>
            </>
          )}
        </aside>

        {sidebarTab === "roles" && selectedRole ? (
          <section className="pf-panel pf-perm-matrix-panel">
            <PermissionHeroStats
              title={selectedRole.name}
              subtitle={
                <>
                  <input
                    className="pf-cell-input pf-perm-role-name-input"
                    value={roleNameDraft}
                    onChange={(e) => setRoleNameDraft(e.target.value)}
                    placeholder="角色名称"
                  />
                  <input
                    className="pf-cell-input pf-perm-role-desc-input"
                    value={roleDescDraft}
                    onChange={(e) => setRoleDescDraft(e.target.value)}
                    placeholder="角色说明（可选）"
                  />
                </>
              }
              avatarText={selectedRole.name}
              permissionIds={selectedRole.permissions ?? []}
            />
            <div className="pf-perm-toolbar">
              <div className="pf-perm-panel-actions">
                <button
                  type="button"
                  className="pf-btn pf-btn-sm pf-btn-primary"
                  onClick={() => void saveRoleMeta()}
                  disabled={saving}
                >
                  保存角色信息
                </button>
                <button
                  type="button"
                  className="pf-btn pf-btn-sm pf-btn-danger"
                  onClick={() => void deleteRole(selectedRole)}
                  disabled={saving}
                >
                  删除角色
                </button>
              </div>
            </div>
            <PermissionMatrix
              permissionIds={selectedRole.permissions ?? []}
              saving={saving}
              activePresetId={selectedRoleActivePreset}
              onToggle={(id) => void toggleRolePermission(id)}
              onApplyPreset={(id) => void applyRolePreset(id)}
              footnote={`权限按角色配置，共 ${(selectedRole.permissions ?? []).length} 项。绑定该角色的用户将自动继承；修改后相关用户需重新登录生效。`}
            />
          </section>
        ) : sidebarTab === "users" && selectedUser ? (
          <section className="pf-panel pf-perm-matrix-panel">
            <PermissionHeroStats
              title={selectedUser.name}
              subtitle={<code>{selectedUser.account}</code>}
              avatarText={selectedUser.name}
              permissionIds={selectedUser.permissions ?? []}
            />
            <div className="pf-perm-toolbar">
              <div className="pf-perm-panel-actions">
                <button type="button" className="pf-btn pf-btn-sm" onClick={openPasswordModal} disabled={saving}>
                  修改密码
                </button>
                <button type="button" className="pf-btn pf-btn-sm" onClick={() => void toggleUserStatus()} disabled={saving || userLockedAsLastFullAdmin}>
                  {selectedUser.status === "active" ? "停用账号" : "启用账号"}
                </button>
                <button
                  type="button"
                  className="pf-btn pf-btn-sm pf-btn-danger"
                  onClick={() => void deleteUser(selectedUser)}
                  disabled={saving}
                >
                  删除用户
                </button>
              </div>
            </div>

            <div className="pf-perm-assign-section pf-perm-assign-section-compact">
              <div className="pf-perm-assign-head">
                <h3>配置角色</h3>
                <p>页面权限仅通过角色配置；请为用户选择角色，权限将自动继承。</p>
              </div>
              {userLockedAsLastFullAdmin ? (
                <p className="pf-perm-create-tip">
                  该账号为当前唯一全权限管理员，无法调整角色。请先将另一名启用用户设为全权限管理员后，再修改本账号。
                </p>
              ) : null}
              {roles.length === 0 ? (
                <p className="pf-perm-create-tip">暂无角色，请先在「角色列表」中新建角色并配置权限。</p>
              ) : (
                <div className="pf-perm-assign-grid">
                  {roles.map((role) => (
                    <button
                      key={role.role_id}
                      type="button"
                      className={`pf-perm-assign-card${selectedUser.role_id === role.role_id ? " is-active" : ""}`}
                      disabled={saving || userLockedAsLastFullAdmin}
                      onClick={() => void assignUserRole(role.role_id)}
                    >
                      <strong>{role.name}</strong>
                      <span>{(role.permissions ?? []).length} 项权限</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <PermissionMatrix
              permissionIds={selectedUser.permissions ?? []}
              saving={saving}
              readOnly
              activePresetId={null}
              onToggle={() => {}}
              onApplyPreset={() => {}}
              footnote={
                userLockedAsLastFullAdmin
                  ? `该账号拥有全部 ${PERMISSIONS.length} 项页面权限（只读保护）。系统需至少保留一名全权限且启用中的管理员。`
                  : selectedUser.role_id
                    ? `当前通过角色「${selectedUser.role_name}」继承 ${knownPermissionIds(selectedUser.permissions ?? []).length} 项权限（只读）。如需调整请至「角色列表」修改该角色。`
                    : "该用户尚未分配角色，请先在上方选择角色；权限将随角色继承。"
              }
            />
          </section>
        ) : (
          <div className="pf-panel pf-perm-empty-panel">
            <p className="pf-perm-empty">
              {sidebarTab === "roles"
                ? roles.length === 0
                  ? "暂无角色，请点击「新建角色」"
                  : "请从左侧选择角色配置页面权限"
                : users.length === 0
                  ? "暂无用户，请先新建用户"
                  : "请从左侧选择用户配置角色"}
            </p>
          </div>
        )}
      </div>

      <Modal
        open={createOpen}
        title="新建用户"
        modalClassName="pf-modal-create-user"
        closeOnBackdrop={false}
        onClose={closeCreateModal}
        footer={
          <>
            <button type="button" className="pf-btn" onClick={closeCreateModal}>
              取消
            </button>
            <button type="button" className="pf-btn pf-btn-primary" onClick={() => void createUser()} disabled={saving}>
              创建
            </button>
          </>
        }
      >
        <p className="pf-perm-create-tip">创建用户时需选择角色，页面权限将随角色继承。</p>
        {createUserError ? <div className="pf-perm-create-error">{createUserError}</div> : null}
        <label className="pf-perm-field">
          <span>姓名</span>
          <input
            className="pf-cell-input"
            value={createDraft.name}
            placeholder="如：周工"
            onChange={(e) => {
              setCreateUserError("");
              setCreateDraft((d) => ({ ...d, name: e.target.value }));
            }}
          />
        </label>
        <label className="pf-perm-field">
          <span>登录账号</span>
          <input
            className="pf-cell-input"
            value={createDraft.account}
            placeholder="如：zhou.gong"
            autoComplete="off"
            onChange={(e) => {
              setCreateUserError("");
              setCreateDraft((d) => ({ ...d, account: e.target.value }));
            }}
          />
        </label>
        <label className="pf-perm-field">
          <span>初始密码</span>
          <input
            type="password"
            className="pf-cell-input"
            value={createDraft.password}
            placeholder="至少 4 位"
            autoComplete="new-password"
            onChange={(e) => {
              setCreateUserError("");
              setCreateDraft((d) => ({ ...d, password: e.target.value }));
            }}
          />
        </label>
        <label className="pf-perm-field pf-perm-field-role">
          <RoleSelect
            value={createDraft.roleId}
            roles={roles}
            disabled={saving}
            onChange={(roleId) => {
              setCreateUserError("");
              setCreateDraft((d) => ({ ...d, roleId }));
            }}
          />
        </label>
      </Modal>

      <Modal
        open={createRoleOpen}
        title="新建角色"
        onClose={closeCreateRoleModal}
        footer={
          <>
            <button type="button" className="pf-btn" onClick={closeCreateRoleModal}>
              取消
            </button>
            <button
              type="button"
              className="pf-btn pf-btn-primary"
              onClick={() => void submitCreateRole()}
              disabled={saving}
            >
              创建
            </button>
          </>
        }
      >
        <p className="pf-perm-create-tip">填写角色名称后创建，再在右侧权限矩阵中勾选页面权限。</p>
        <label className="pf-perm-field">
          <span>角色名称</span>
          <input
            className="pf-cell-input"
            value={createRoleDraft.name}
            placeholder="如：大堂管理"
            autoFocus
            onChange={(e) => setCreateRoleDraft((d) => ({ ...d, name: e.target.value }))}
          />
        </label>
        <label className="pf-perm-field">
          <span>角色说明（可选）</span>
          <input
            className="pf-cell-input"
            value={createRoleDraft.description}
            placeholder="如：负责大堂区域巡检与看板"
            onChange={(e) => setCreateRoleDraft((d) => ({ ...d, description: e.target.value }))}
          />
        </label>
      </Modal>

      <Modal
        open={passwordOpen}
        title={`修改密码 · ${selectedUser?.name ?? ""}`}
        onClose={closePasswordModal}
        footer={
          <>
            <button type="button" className="pf-btn" onClick={closePasswordModal}>
              取消
            </button>
            <button
              type="button"
              className="pf-btn pf-btn-primary"
              onClick={() => void changeUserPassword()}
              disabled={saving}
            >
              保存
            </button>
          </>
        }
      >
        <p className="pf-perm-create-tip">
          为账号 <code>{selectedUser?.account}</code> 设置新密码，保存后立即生效。
        </p>
        <label className="pf-perm-field">
          <span>新密码</span>
          <input
            type="password"
            className="pf-cell-input"
            value={passwordDraft.password}
            placeholder="至少 4 位"
            autoComplete="new-password"
            onChange={(e) => setPasswordDraft((d) => ({ ...d, password: e.target.value }))}
          />
        </label>
        <label className="pf-perm-field">
          <span>确认密码</span>
          <input
            type="password"
            className="pf-cell-input"
            value={passwordDraft.confirm}
            placeholder="再次输入新密码"
            autoComplete="new-password"
            onChange={(e) => setPasswordDraft((d) => ({ ...d, confirm: e.target.value }))}
          />
        </label>
      </Modal>
    </div>
  );
}
