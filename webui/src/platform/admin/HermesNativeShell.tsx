import { Suspense, lazy } from "react";
import { MemoryRouter, Navigate, Route, Routes } from "react-router-dom";
import { PageHeaderProvider } from "@hermes/contexts/PageHeaderProvider";
import { SystemActionsProvider } from "@hermes/contexts/SystemActions";
import { I18nProvider } from "@hermes/i18n";
import { ThemeProvider } from "@hermes/themes";
import "@hermes/index.css";

const ConfigPage = lazy(() => import("@hermes/pages/ConfigPage"));
const DocsPage = lazy(() => import("@hermes/pages/DocsPage"));
const EnvPage = lazy(() => import("@hermes/pages/EnvPage"));
const SessionsPage = lazy(() => import("@hermes/pages/SessionsPage"));
const LogsPage = lazy(() => import("@hermes/pages/LogsPage"));
const AnalyticsPage = lazy(() => import("@hermes/pages/AnalyticsPage"));
const ModelsPage = lazy(() => import("@hermes/pages/ModelsPage"));
const CronPage = lazy(() => import("@hermes/pages/CronPage"));
const ProfilesPage = lazy(() => import("@hermes/pages/ProfilesPage"));
const SkillsPage = lazy(() => import("@hermes/pages/SkillsPage"));
const PluginsPage = lazy(() => import("@hermes/pages/PluginsPage"));
const ChatPage = lazy(() => import("@hermes/pages/ChatPage"));

export function HermesNativeShell({
  dashboardPath,
  routeKey,
}: {
  dashboardPath: string;
  routeKey: string;
}) {
  return (
    <div className="pf-hermes-native-shell">
      <MemoryRouter initialEntries={[dashboardPath]} key={routeKey}>
        <I18nProvider>
          <ThemeProvider>
            <SystemActionsProvider>
              <PageHeaderProvider pluginTabs={[]}>
                <Suspense fallback={<div className="pf-hermes-status">正在按需加载 Hermes 页面…</div>}>
                  <Routes>
                    <Route path="/" element={<Navigate to="/sessions" replace />} />
                    <Route path="/chat" element={<ChatPage isActive />} />
                    <Route path="/sessions" element={<SessionsPage />} />
                    <Route path="/analytics" element={<AnalyticsPage />} />
                    <Route path="/models" element={<ModelsPage />} />
                    <Route path="/logs" element={<LogsPage />} />
                    <Route path="/cron" element={<CronPage />} />
                    <Route path="/skills" element={<SkillsPage />} />
                    <Route path="/plugins" element={<PluginsPage />} />
                    <Route path="/profiles" element={<ProfilesPage />} />
                    <Route path="/config" element={<ConfigPage />} />
                    <Route path="/env" element={<EnvPage />} />
                    <Route path="/docs" element={<DocsPage />} />
                    <Route path="*" element={<Navigate to={dashboardPath} replace />} />
                  </Routes>
                </Suspense>
              </PageHeaderProvider>
            </SystemActionsProvider>
          </ThemeProvider>
        </I18nProvider>
      </MemoryRouter>
    </div>
  );
}
