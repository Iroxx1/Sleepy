import { useCallback, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { EventsResponse, Insights, MetricDetail, NightDetail, NightEvent } from "../../../src/api/types";
import { Disclaimer, Dot, ErrorMsg, Section, Spinner, Tile } from "../components/ui";
import NightCharts from "../components/NightCharts";
import { clock, dateDe, hm, num, weekday } from "../../../src/lib/format";

export default function NightView() {
  const { id } = useParams();
  const nightId = Number(id);
  const nav = useNavigate();
  const [focus, setFocus] = useState<{ start: number; end: number; key: number } | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [showAll, setShowAll] = useState(false);
  const nq = useQuery({ queryKey: ["m-night", nightId], queryFn: () => api.get<NightDetail>(`/api/nights/${nightId}`) });
  const eq = useQuery({ queryKey: ["m-night-ev", nightId], queryFn: () => api.get<EventsResponse>(`/api/nights/${nightId}/events`) });
  const iq = useQuery({ queryKey: ["m-night-ins", nightId], queryFn: () => api.get<Insights>(`/api/nights/${nightId}/insights`) });
  const m = useMemo(() => {
    const o: Record<string, MetricDetail> = {};
    for (const x of nq.data?.metrics || []) o[x.key] = x;
    return o;
  }, [nq.data]);
  const select = useCallback((e: NightEvent) => {
    setSel(e.id);
    setFocus({ start: e.start_ms, end: Math.max(e.end_ms, e.start_ms + 1000), key: Date.now() });
  }, []);

  if (nq.isLoading) return <Spinner />;
  if (nq.error) return <ErrorMsg error={nq.error} />;
  const d = nq.data!;
  const n = d.night;
  const v = (k: string) => m[k]?.value ?? null;
  const evs = eq.data?.items || [];
  const types = eq.data?.types || {};

  return (
    <div className="m-stack">
      <div className="m-night-nav">
        <button className="m-btn small" disabled={!d.prev_id} onClick={() => nav(`/night/${d.prev_id}`, { replace: true })}>‹</button>
        <div className="center">
          <div className="m-row" style={{ justifyContent: "center" }}>
            <Dot status={n.status} /> <strong>{weekday(n.date)} {dateDe(n.date)}</strong>
          </div>
          <div className="muted small">{clock(n.start_ms)} – {clock(n.end_ms)}</div>
        </div>
        <button className="m-btn small" disabled={!d.next_id} onClick={() => nav(`/night/${d.next_id}`, { replace: true })}>›</button>
      </div>

      <Section>
        <div className="m-grid2">
          <Tile big label="Nutzung" value={hm(v("usage_h"))} sub={`${n.session_count} Sitzung(en)`} />
          <Tile big label="AHI" value={num(v("ahi"), 2)} sub={m.ahi?.source === "device" ? "Gerätewert" : "berechnet"} />
        </div>
        <div className="m-grid3">
          {([
            ["CAI", "cai", 2], ["OAI", "oai", 2], ["HI", "hi", 2], ["UAI", "uai", 2], ["RERA", "rera_index", 2], ["RDI", "rdi", 2],
            ["Leck Med.", "leak.median", 1], ["Leck 95 %", "leak.p95", 1], ["Leck max", "leak.max", 1],
            ["Druck Med.", "pressure.median", 1], ["Druck 95 %", "pressure.p95", 1], ["Druck max", "pressure.max", 1],
            ["EPAP Med.", "epap.median", 1], ["EPAP 95 %", "epap.p95", 1], ["FL 95 %", "flow_limit.p95", 2],
            ["Atemfreq.", "resp_rate.median", 1], ["Minutenvol.", "minute_vent.median", 1], ["Zugvol.", "tidal_volume.median", 0],
            ["SpO2 Med.", "spo2.median", 0], ["SpO2 min", "spo2.min", 0], ["ODI", "odi", 1], ["Puls Ø", "pulse.mean", 0],
          ] as [string, string, number][])
            .filter(([, k]) => v(k) != null)
            .slice(0, showAll ? 99 : 9)
            .map(([l, k, dec]) => <Tile key={k} label={l} value={num(v(k), dec)} />)}
        </div>
        <button className="m-link" onClick={() => setShowAll(!showAll)}>{showAll ? "weniger" : "alle Kennzahlen"}</button>
        {v("spo2.median") == null && <p className="muted small">Keine SpO2-Daten verfügbar.</p>}
        {iq.data && <p className="m-text">{iq.data.summary}</p>}
        {iq.data && iq.data.anomalies.length > 0 && (
          <div className="alert warn small">{iq.data.anomalies.map((a) => <div key={a.key}>{a.text}</div>)}</div>
        )}
        {iq.data && iq.data.observations.length > 0 && (
          <ul className="m-obs">
            {iq.data.observations.map((o, i) => (
              <li key={i} onClick={() => o.start_ms !== undefined && o.end_ms !== undefined && setFocus({ start: o.start_ms, end: o.end_ms, key: Date.now() })}>
                {o.text}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {n.has_detail && d.channels.length > 0 && n.start_ms && n.end_ms ? (
        <Section title="Diagramme">
          <NightCharts nightId={nightId} channels={d.channels} events={evs} types={types} startMs={n.start_ms} endMs={n.end_ms} leakThreshold={d.leak_threshold} focus={focus} />
        </Section>
      ) : (
        <Section title="Diagramme"><p className="muted">Für diese Nacht liegen nur Zusammenfassungswerte vor.</p></Section>
      )}

      <Section title={`Ereignisse (${evs.length})`}>
        {evs.length === 0 && <p className="muted">Keine Ereignisse aufgezeichnet.</p>}
        <div className="m-list">
          {evs.map((e) => (
            <button key={e.id} className={`m-list-item ${sel === e.id ? "selected" : ""}`} onClick={() => select(e)}>
              <span className="ev-chip" style={{ background: types[e.code]?.color }}>{types[e.code]?.short ?? e.code}</span>
              <span className="mono">{clock(e.start_ms, true)}</span>
              <span className="grow muted small">{e.duration_s != null ? `${num(e.duration_s, 0)} s` : ""}</span>
              <span className="small">{e.context.pressure != null ? `${num(e.context.pressure, 1)} cmH2O` : ""}</span>
            </button>
          ))}
        </div>
      </Section>
      <Disclaimer />
    </div>
  );
}
