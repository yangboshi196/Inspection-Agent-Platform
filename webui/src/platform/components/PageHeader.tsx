import type { ReactNode } from "react";
import { Link } from "react-router-dom";

type Props = {
  title: string;
  subtitle?: string;
  eyebrow?: string;
  backTo?: string;
  backLabel?: string;
  actions?: ReactNode;
};

export function PageHeader({ title, subtitle, eyebrow, backTo, backLabel, actions }: Props) {
  return (
    <header className="pf-page-header">
      <div className="pf-page-header-main">
        {backTo ? (
          <Link to={backTo} className="pf-back-link">
            &larr; {backLabel ?? "\u8fd4\u56de"}
          </Link>
        ) : null}
        {eyebrow ? <span className="pf-page-eyebrow">{eyebrow}</span> : null}
        <h1>{title}</h1>
        {subtitle ? <p className="pf-page-subtitle">{subtitle}</p> : null}
      </div>
      {actions ? <div className="pf-page-header-actions">{actions}</div> : null}
    </header>
  );
}
