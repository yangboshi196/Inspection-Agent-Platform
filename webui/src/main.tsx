import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./platform/AuthContext";
import "./index.css";
import "./platform/platform.css";
import "./platform/dataCenter/data-center.css";
import "./platform/dataCenter/smart-assistant.css";

/** Hermes 嵌入：在任意模块读取 BASE 之前同步注入前缀。 */
if (typeof window !== "undefined") {
  window.__HERMES_BASE_PATH__ = import.meta.env.DEV ? "/api/hermes" : "/hermes-agent";
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <HashRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </HashRouter>
  </React.StrictMode>,
);
