import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Status, Thresholds } from "../api/types";
import { useDevice } from "../hooks/useDevice";
import { Card, ErrorBox, Loading } from "../components/ui";
import { hm, num, STATUS_LABEL, today } from "../lib/format";

interface Day {
  id: number;
  date: string;
  device_id: number;
  status: Status;
  ahi: number | null;
  usage_h: number | null;
  leak_p95: number | null;
}

const MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
const WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

function pad(n: number) {
  return String(n).padStart(2, "0");
}
function iso(y: number, m: number, d: number) {
  return `${y}-${pad(m + 1)}-${pad(d)}`;
}
function daysIn(y: number, m: number) {
  return new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
}
function firstWeekday(y: number, m: number) {
  return (new Date(Date.UTC(y, m, 1)).getUTCDay() + 6) % 7; // Monday = 0
}

export default function Calendar() {
  const { deviceId } = useDevice();
  const nav = useNavigate();
  const t = today();
  const [view, setView] = useState<"month" | "year">("month");
  const [year, setYear] = useState(Number(t.slice(0, 4)));
  const [month, setMonth] = useState(Number(t.slice(5, 7)) - 1);

  const from = view === "month" ? iso(year, month, 1) : `${year}-01-01`;
  const to = view === "month" ? iso(year, month, daysIn(year, month)) : `${year}-12-31`;
  const q = useQuery({
    queryKey: ["calendar", from, to, deviceId],
    queryFn: () => api.get<{ thresholds: Thresholds; days: Day[] }>("/api/nights/calendar", { from, to, device_id: deviceId }),
  });
  const byDate = useMemo(() => {
    const m = new Map<string, Day>();
    for (const d of q.data?.days || []) if (!m.has(d.date)) m.set(d.date, d);
    return m;
  }, [q.data]);

  const shift = (delta: number) => {
    if (view === "year") return setYear(year + delta);
    let m = month + delta;
    let y = year;
    if (m < 0) {
      m = 11;
      y--;
    } else if (m > 11) {
      m = 0;
      y++;
    }
    setMonth(m);
    setYear(y);
  };

  const th = q.data?.thresholds;
  return (
    <div className="stack">
      <Card
        title={
          <div className="row">
            <button onClick={() => shift(-1)} aria-label="Zurück">
              ◀
            </button>
            <h2 style={{ margin: 0, minWidth: 170, textAlign: "center" }}>{view === "month" ? `${MONTHS[month]} ${year}` : year}</h2>
            <button onClick={() => shift(1)} aria-label="Vor">
              ▶
            </button>
          </div>
        }
        actions={
          <div className="btn-group">
            <button className={view === "month" ? "active" : ""} onClick={() => setView("month")}>
              Monat
            </button>
            <button className={view === "year" ? "active" : ""} onClick={() => setView("year")}>
              Jahr
            </button>
          </div>
        }
      >
        <ErrorBox error={q.error} />
        {q.isLoading && <Loading />}
        {view === "month" ? (
          <div className="cal">
            {WD.map((w) => (
              <div key={w} className="wd">
                {w}
              </div>
            ))}
            {Array.from({ length: firstWeekday(year, month) }).map((_, i) => (
              <div key={`e${i}`} className="day out" />
            ))}
            {Array.from({ length: daysIn(year, month) }).map((_, i) => {
              const date = iso(year, month, i + 1);
              const d = byDate.get(date);
              return (
                <div
                  key={date}
                  className={`day ${d ? `has ${d.status}` : ""} ${date === t ? "today" : ""}`}
                  onClick={() => d && nav(`/nights/${d.id}`)}
                  title={d ? STATUS_LABEL[d.status] : "keine Daten"}
                  role={d ? "button" : undefined}
                  tabIndex={d ? 0 : undefined}
                  onKeyDown={(e) => d && e.key === "Enter" && nav(`/nights/${d.id}`)}
                >
                  <span className="n">{i + 1}</span>
                  {d ? (
                    <>
                      <span>AHI {num(d.ahi, 1)}</span>
                      <span className="extra muted">{hm(d.usage_h)}</span>
                    </>
                  ) : (
                    <span className="muted extra">⚪</span>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="year">
            {MONTHS.map((name, m) => (
              <div key={name} className="mini-month">
                <div className="small" style={{ fontWeight: 600, marginBottom: 4, cursor: "pointer" }} onClick={() => { setMonth(m); setView("month"); }}>
                  {name}
                </div>
                <div className="cells">
                  {Array.from({ length: firstWeekday(year, m) }).map((_, i) => (
                    <div key={`e${i}`} className="cell empty" />
                  ))}
                  {Array.from({ length: daysIn(year, m) }).map((_, i) => {
                    const date = iso(year, m, i + 1);
                    const d = byDate.get(date);
                    return (
                      <div
                        key={date}
                        className={`cell ${d ? `has ${d.status}` : ""}`}
                        title={`${date}${d ? ` · AHI ${num(d.ahi, 1)} · ${hm(d.usage_h)}` : " · keine Daten"}`}
                        onClick={() => d && nav(`/nights/${d.id}`)}
                      />
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="row small muted" style={{ marginTop: "1rem" }}>
          <span className="legend-item">
            <span className="dot green" /> unauffällig
          </span>
          <span className="legend-item">
            <span className="dot yellow" /> auffällig
          </span>
          <span className="legend-item">
            <span className="dot red" /> viele Ereignisse
          </span>
          <span className="legend-item">
            <span className="dot none" /> keine Daten
          </span>
          {th && (
            <span>
              · Schwellen: AHI ≥ {th.ahi_yellow} gelb / ≥ {th.ahi_red} rot, Nutzung &lt; {th.usage_min_h} h gelb, Leck 95 % &gt; {th.leak_p95_max} L/min gelb
              (in den Einstellungen anpassbar; keine medizinische Bewertung)
            </span>
          )}
        </div>
      </Card>
    </div>
  );
}
