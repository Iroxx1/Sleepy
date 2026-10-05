import type { ReactNode } from "react";

export function Section({ title, right, children }: { title?: ReactNode; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="m-card">
      {(title || right) && (
        <div className="m-card-head">
          {title && <h2>{title}</h2>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Tile({ label, value, sub, big, onClick }: { label: string; value: ReactNode; sub?: ReactNode; big?: boolean; onClick?: () => void }) {
  return (
    <div className={`m-tile ${big ? "big" : ""}`} onClick={onClick}>
      <div className="l">{label}</div>
      <div className="v">{value}</div>
      {sub && <div className="s">{sub}</div>}
    </div>
  );
}

export function Dot({ status }: { status: string }) {
  return <span className={`dot ${status}`} />;
}

export function Spinner({ text = "Lade …" }: { text?: string }) {
  return (
    <div className="m-loading">
      <span className="spinner" /> {text}
    </div>
  );
}

export function ErrorMsg({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="alert err">{error instanceof Error ? error.message : String(error)}</div>;
}

export const DISCLAIMER =
  "Die dargestellten Informationen dienen ausschließlich der technischen Analyse der PAP-Therapiedaten und ersetzen keine ärztliche Beratung.";

export function Disclaimer() {
  return <p className="m-disclaimer">{DISCLAIMER}</p>;
}

export function Chips<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="m-chips">
      {options.map(([k, l]) => (
        <button key={k} className={value === k ? "active" : ""} onClick={() => onChange(k)}>
          {l}
        </button>
      ))}
    </div>
  );
}
