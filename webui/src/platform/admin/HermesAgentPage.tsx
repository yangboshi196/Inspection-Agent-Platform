import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  HERMES_TABS,
  hermesAgentBase,
  hermesDashboardPathFromSlug,
} from "../hermesAgent";

export function HermesAgentPage() {
  const { tab } = useParams<{ tab?: string }>();
  const active = useMemo(
    () => HERMES_TABS.find((x) => x.slug === tab) ?? HERMES_TABS[1],
    [tab],
  );
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [loaded, setLoaded] = useState(false);
  const base = useMemo(() => hermesAgentBase(), []);
  const dashboardPath = useMemo(
    () => hermesDashboardPathFromSlug(active.slug),
    [active.slug],
  );
  const targetSrc = useMemo(
    () => `${base}${dashboardPath}`,
    [base, dashboardPath],
  );
  const [initialSrc] = useState(() => targetSrc);

  const applyEmbeddedOverrides = (frame: HTMLIFrameElement) => {
    try {
      const doc = frame.contentDocument;
      if (!doc) return;
      const styleId = "sia-hermes-embed-overrides";
      let styleEl = doc.getElementById(styleId) as HTMLStyleElement | null;
      if (!styleEl) {
        styleEl = doc.createElement("style");
        styleEl.id = styleId;
        doc.head.appendChild(styleEl);
      }
      styleEl.textContent = `
#app-sidebar { display: none !important; }
#app-sidebar + div { width: 100% !important; max-width: 100% !important; margin-left: 0 !important; }
[aria-controls="app-sidebar"] { display: none !important; }
`;
    } catch {
      // ignore cross-origin access errors
    }
  };

  useEffect(() => {
    const frame = iframeRef.current;
    if (!frame) return;
    if (!loaded) {
      if (frame.src !== targetSrc) frame.src = targetSrc;
      return;
    }
    applyEmbeddedOverrides(frame);
    try {
      const win = frame.contentWindow;
      if (!win || win.location.origin !== window.location.origin) {
        frame.src = targetSrc;
        return;
      }
      if (win.location.pathname !== `${base}${dashboardPath}`) {
        win.history.replaceState({}, "", `${base}${dashboardPath}`);
        win.dispatchEvent(new PopStateEvent("popstate"));
      }
    } catch {
      frame.src = targetSrc;
    }
  }, [base, dashboardPath, loaded, targetSrc]);

  return (
    <div className="pf-hermes-page pf-hermes-page-embed">
      <iframe
        ref={iframeRef}
        className="pf-hermes-frame"
        title={`Hermes Agent - ${active.label}`}
        src={initialSrc}
        onLoad={(e) => {
          setLoaded(true);
          applyEmbeddedOverrides(e.currentTarget);
        }}
      />
    </div>
  );
}
