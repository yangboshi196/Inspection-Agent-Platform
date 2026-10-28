import { FormEvent, useState } from "react";

import { Navigate, useNavigate } from "react-router-dom";

import { useAuth } from "./AuthContext";



export function LoginPage() {

  const navigate = useNavigate();

  const { isAuthenticated, loading, login } = useAuth();

  const [username, setUsername] = useState("zhang.gong");

  const [password, setPassword] = useState("demo1234");

  const [error, setError] = useState("");

  const [submitting, setSubmitting] = useState(false);



  if (!loading && isAuthenticated) {

    return <Navigate to="/portal" replace />;

  }



  const handleSubmit = async (event: FormEvent) => {

    event.preventDefault();

    if (!username.trim()) {

      setError("请输入账号");

      return;

    }

    if (!password) {

      setError("请输入密码");

      return;

    }

    setSubmitting(true);

    setError("");

    try {

      await login(username, password);

      navigate("/portal", { replace: true });

    } catch (e) {

      setError(e instanceof Error ? e.message : "登录失败");

    } finally {

      setSubmitting(false);

    }

  };



  return (

    <div className="pf-login">

      <div className="pf-login-bg" aria-hidden>

        <div className="pf-login-bg-grid" />

        <div className="pf-login-bg-glow pf-login-bg-glow-a" />

        <div className="pf-login-bg-glow pf-login-bg-glow-b" />

      </div>



      <div className="pf-login-shell">

        <section className="pf-login-brand">

          <div className="pf-login-brand-mark">巡</div>

          <h1>安全生产智能巡检系统</h1>

          <p>视频与传感融合巡检 · 规范知识驱动 · 运行态势可视</p>

          <ul className="pf-login-brand-points">

            <li>用户看板：巡检 KPI、报告与事件跟踪</li>

            <li>管理端：巡检业务编排、设备与知识库维护</li>

          </ul>

        </section>



        <section className="pf-login-card">

          <div className="pf-login-card-head">

            <span className="pf-login-tag">角色登录</span>

            <h2>欢迎回来</h2>

            <p>演示账号默认密码均为 demo1234</p>

          </div>



          <form className="pf-login-form" onSubmit={(e) => void handleSubmit(e)}>

            <label className="pf-login-field">

              <span>账号</span>

              <input

                type="text"

                autoComplete="username"

                placeholder="zhang.gong / li.min / wang.audit"

                value={username}

                onChange={(event) => setUsername(event.target.value)}

              />

            </label>



            <label className="pf-login-field">

              <span>密码</span>

              <input

                type="password"

                autoComplete="current-password"

                placeholder="demo1234"

                value={password}

                onChange={(event) => setPassword(event.target.value)}

              />

            </label>



            {error ? <p className="pf-login-error">{error}</p> : null}



            <button type="submit" className="pf-login-submit" disabled={submitting || loading}>

              {submitting ? "登录中…" : "登录"}

            </button>

          </form>



          <p className="pf-login-foot">

            张工（全权限）· 李敏（运维配置）· 王审计（用户端只读）· 密码 demo1234

          </p>

        </section>

      </div>

    </div>

  );

}

