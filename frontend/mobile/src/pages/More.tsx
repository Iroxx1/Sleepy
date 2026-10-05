import { useQuery } from "@tanstack/react-query";
import { api, getConnection, isNative } from "../api";
import { useMobileAuth } from "../auth";
import type { HardwareList } from "../../../src/api/types";
import { Chips, Disclaimer, Section } from "../components/ui";
import { useTheme } from "../../../src/hooks/useTheme";
import { dateDe, num } from "../../../src/lib/format";

declare const __APP_VERSION__: string;

export default function More() {
  const { user, logout } = useMobileAuth();
  const { mode, setMode } = useTheme();
  const hw = useQuery({ queryKey: ["m-hardware"], queryFn: () => api.get<HardwareList>("/api/hardware") });
  const conn = getConnection();
  const active = (hw.data?.items || []).filter((i) => i.active);
  return (
    <div className="m-stack">
      <Section title="Hardware">
        {active.length === 0 && <p className="muted">Keine Hardware erfasst (in der Weboberfläche unter „Hardware“).</p>}
        <div className="m-list">
          {active.map((i) => {
            const st = i.reading_stats.blower_hours ?? Object.values(i.reading_stats)[0];
            return (
              <div key={i.id} className="m-hw">
                <div className="m-row between">
                  <div>
                    <div className="muted small">{i.category_label}</div>
                    <strong>{i.name}</strong>
                  </div>
                  {i.due && (
                    <span className={`badge ${i.due.status === "due" ? "err" : i.due.status === "soon" ? "warn" : "ok"}`}>
                      {i.due.status === "due" ? `seit ${-i.due.days_left} T fällig` : i.due.status === "soon" ? `in ${i.due.days_left} T` : dateDe(i.due.due_on)}
                    </span>
                  )}
                </div>
                <div className="small muted">
                  seit {dateDe(i.started_on)}{i.age_days != null && ` (${i.age_days} Tage)`}
                  {i.therapy_usage && ` · ${num(i.therapy_usage.hours, 0)} h Therapie`}
                </div>
                {st && (
                  <div className="small">
                    {st.label}: <strong>{num(st.latest_value, 0)} h</strong> ({dateDe(st.latest_on)})
                    {st.per_day != null && ` · Ø ${num(st.per_day, 1)} h/Tag`}
                    {st.projection && ` · ${num(st.projection.pct_used, 0)} % der erwarteten Laufzeit`}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </Section>
      <Section title="Darstellung">
        <Chips value={mode} onChange={setMode} options={[["system", "System"], ["light", "Hell"], ["dark", "Dunkel"]]} />
      </Section>
      <Section title="Verbindung">
        <p className="small">
          Angemeldet als <strong>{user?.username}</strong>
          {isNative() && <><br />Server: <span className="mono">{conn.baseUrl}</span></>}
        </p>
        <button className="m-btn danger" onClick={() => logout()}>Abmelden</button>
      </Section>
      <p className="muted small center">Sleepy Mobile {__APP_VERSION__}</p>
      <Disclaimer />
    </div>
  );
}
