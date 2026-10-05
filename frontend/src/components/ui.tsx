import type { ReactNode } from "react";
import { STATUS_LABEL } from "../lib/format";

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className ?? ""}`}>
      {(title || actions) && (
        <div className="card-head">
          {typeof title === "string" ? <h2>{title}</h2> : title}
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Kpi({ label, value, sub, big, title }: { label: string; value: ReactNode; sub?: ReactNode; big?: boolean; title?: string }) {
  return (
    <div className={`kpi ${big ? "big" : ""}`} title={title}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export function StatusDot({ status }: { status: string }) {
  return <span className={`dot ${status}`} title={STATUS_LABEL[status] ?? status} aria-label={STATUS_LABEL[status] ?? status} />;
}

export function Loading({ text = "Lade …" }: { text?: string }) {
  return (
    <div className="loading">
      <span className="spinner" /> {text}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return <div className="alert err">{msg}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export const DISCLAIMER =
  "Die dargestellten Informationen dienen ausschließlich der technischen Analyse der PAP-Therapiedaten und ersetzen keine ärztliche Beratung.";

export function Disclaimer({ text }: { text?: string }) {
  return <div className="disclaimer">{text || DISCLAIMER}</div>;
}

export function EventChip({ code, color, short }: { code: string; color?: string; short?: string }) {
  return (
    <span className="ev-chip" style={{ background: color || "#64748b" }} title={code}>
      {short || code}
    </span>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="card-head">
          <h2>{title}</h2>
          <button className="ghost" onClick={onClose} aria-label="Schließen">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Progress({ value }: { value: number }) {
  return (
    <div className="progress" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    </div>
  );
}

const ICONS: Record<string, string> = {
  dashboard: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z",
  nights: "M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36A5.39 5.39 0 0 1 12.26 4.1 9.06 9.06 0 0 0 12 3z",
  calendar: "M7 2v2H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2V2h-2v2H9V2H7zm-2 7h14v10H5V9z",
  trends: "M3 17l6-6 4 4 8-8v4h2V3h-8v2h4l-6 6-4-4-7.5 7.5L3 17z",
  compare: "M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h5v2h2V1h-2v2zm0 15H5l5-6v6zm9-15h-5v2h5v13l-5-6v9h5a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2z",
  import: "M5 20h14v-2H5v2zm7-18l-5.5 5.5 1.42 1.42L11 5.83V16h2V5.83l3.08 3.09 1.42-1.42L12 2z",
  devices: "M4 6h16v10H4V6zm-2 12h20v2H2v-2zM2 4v14h20V4H2z",
  reports: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z",
  settings: "M19.14 12.94a7.07 7.07 0 0 0 0-1.88l2.03-1.58-1.92-3.32-2.39.96a7.03 7.03 0 0 0-1.62-.94L14.9 3.6h-3.84l-.36 2.58c-.58.24-1.12.55-1.62.94l-2.39-.96-1.92 3.32 2.03 1.58a7.07 7.07 0 0 0 0 1.88l-2.03 1.58 1.92 3.32 2.39-.96c.5.39 1.04.7 1.62.94l.36 2.58h3.84l.36-2.58c.58-.24 1.12-.55 1.62-.94l2.39.96 1.92-3.32-2.03-1.58zM12.98 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7z",
  menu: "M3 6h18v2H3V6zm0 5h18v2H3v-2zm0 5h18v2H3v-2z",
  search: "M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z",
};

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="currentColor" aria-hidden="true">
      <path d={ICONS[name] || ""} />
    </svg>
  );
}
