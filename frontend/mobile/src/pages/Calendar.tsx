import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorMsg, Section } from "../components/ui";
import { num, today } from "../../../src/lib/format";

const MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
const p2 = (n: number) => String(n).padStart(2, "0");
const days = (y: number, m: number) => new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
const first = (y: number, m: number) => (new Date(Date.UTC(y, m, 1)).getUTCDay() + 6) % 7;

export default function Calendar() {
  const nav = useNavigate();
  const t = today();
  const [y, setY] = useState(Number(t.slice(0, 4)));
  const [m, setM] = useState(Number(t.slice(5, 7)) - 1);
  const from = `${y}-${p2(m + 1)}-01`;
  const to = `${y}-${p2(m + 1)}-${p2(days(y, m))}`;
  const q = useQuery({
    queryKey: ["m-cal", from],
    queryFn: () => api.get<{ days: { id: number; date: string; status: string; ahi: number | null; usage_h: number | null }[] }>("/api/nights/calendar", { from, to }),
  });
  const by = useMemo(() => new Map((q.data?.days || []).map((d) => [d.date, d])), [q.data]);
  const shift = (d: number) => {
    let mm = m + d;
    let yy = y;
    if (mm < 0) { mm = 11; yy--; }
    if (mm > 11) { mm = 0; yy++; }
    setM(mm);
    setY(yy);
  };
  return (
    <Section
      title={`${MONTHS[m]} ${y}`}
      right={
        <span className="m-row">
          <button className="m-btn small" onClick={() => shift(-1)}>‹</button>
          <button className="m-btn small" onClick={() => shift(1)}>›</button>
        </span>
      }
    >
      <ErrorMsg error={q.error} />
      <div className="m-cal">
        {["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"].map((w) => <div key={w} className="wd">{w}</div>)}
        {Array.from({ length: first(y, m) }).map((_, i) => <div key={`e${i}`} />)}
        {Array.from({ length: days(y, m) }).map((_, i) => {
          const date = `${y}-${p2(m + 1)}-${p2(i + 1)}`;
          const d = by.get(date);
          return (
            <button key={date} className={`m-day ${d ? d.status : "none"} ${date === t ? "today" : ""}`} disabled={!d} onClick={() => d && nav(`/night/${d.id}`)}>
              <span className="n">{i + 1}</span>
              <span className="a">{d ? num(d.ahi, 1) : ""}</span>
            </button>
          );
        })}
      </div>
      <div className="m-legend small muted">
        <span><span className="dot green" /> unauffällig</span>
        <span><span className="dot yellow" /> auffällig</span>
        <span><span className="dot red" /> viele Ereignisse</span>
        <span>Zahl = AHI</span>
      </div>
    </Section>
  );
}
