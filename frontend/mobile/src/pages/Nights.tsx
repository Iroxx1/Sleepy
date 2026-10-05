import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { NightRow } from "../../../src/api/types";
import { Chips, Dot, ErrorMsg, Spinner } from "../components/ui";
import { dateDe, hm, num, weekday } from "../../../src/lib/format";

type F = "all" | "ahi5" | "leak" | "short" | "ca";
const QUERIES: Record<F, string | undefined> = { all: undefined, ahi5: "ahi>5", leak: "leak>24", short: "usage<4h", ca: "event:CA" };

export default function Nights() {
  const nav = useNavigate();
  const [f, setF] = useState<F>("all");
  const [limit, setLimit] = useState(60);
  const q = useQuery({
    queryKey: ["m-nights", f, limit],
    queryFn: () => api.get<{ total: number; items: NightRow[] }>("/api/nights", { q: QUERIES[f], limit }),
    placeholderData: keepPreviousData,
  });
  return (
    <div className="m-stack">
      <Chips<F> value={f} onChange={setF} options={[["all", "Alle"], ["ahi5", "AHI > 5"], ["leak", "Leck > 24"], ["short", "< 4 h"], ["ca", "mit CA"]]} />
      <ErrorMsg error={q.error} />
      {q.isLoading && <Spinner />}
      <div className="m-list cards">
        {q.data?.items.map((r) => (
          <button key={r.id} className="m-night-row" onClick={() => nav(`/night/${r.id}`)}>
            <Dot status={r.status} />
            <div className="grow">
              <div><strong>{weekday(r.date)} {dateDe(r.date)}</strong>{r.notes && " 📝"}</div>
              <div className="muted small">{hm(r.usage_h)} · Leck 95 % {num(r.metrics["leak.p95"], 1)} · Druck 95 % {num(r.metrics["pressure.p95"], 1)}</div>
            </div>
            <div className="right">
              <div className="m-ahi">{num(r.metrics.ahi, 1)}</div>
              <div className="muted small">AHI</div>
            </div>
          </button>
        ))}
      </div>
      {q.data && q.data.total > limit && <button className="m-btn" onClick={() => setLimit(limit + 60)}>Weitere laden ({q.data.total - limit})</button>}
      {q.data && q.data.total === 0 && <p className="muted center">Keine Nächte gefunden.</p>}
    </div>
  );
}
