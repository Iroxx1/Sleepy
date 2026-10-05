import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { EventsResponse, Insights, MetricDetail, NightDetail as ND, NightEvent } from "../api/types";
import { Card, Disclaimer, ErrorBox, EventChip, Kpi, Loading, StatusDot } from "../components/ui";
import NightCharts from "../components/night/NightCharts";
import EventList from "../components/night/EventList";
import { HourlyChart, PeriEventChart } from "../components/night/InsightsPanel";
import { bytes, clock, dateDe, dateTimeDe, duration, fmtMetric, hm, num, weekday } from "../lib/format";

const GROUPS: { title: string; match: (k: string) => boolean }[] = [
  { title: "Therapie & Indizes", match: (k) => ["usage_h", "session_count", "ahi", "ai", "hi", "oai", "cai", "uai", "rera_index", "rdi", "odi", "csr_pct", "csr_device", "desat_count"].includes(k) },
  { title: "Ereignisanzahl", match: (k) => k.startsWith("count.") },
  { title: "Druck", match: (k) => /^(pressure|epap|ipap|mask_pressure|target_ipap|target_epap)\./.test(k) },
  { title: "Leckage", match: (k) => k.startsWith("leak.") },
  { title: "Atmung", match: (k) => /^(resp_rate|tidal_volume|minute_vent|target_vent|ti|te|ie_ratio|flow_limit|snore)\./.test(k) },
  { title: "Oxymetrie", match: (k) => /^(spo2|pulse)\./.test(k) },
];

function MetricsTable({ metrics }: { metrics: MetricDetail[] }) {
  const used = new Set<string>();
  const groups = GROUPS.map((g) => {
    const items = metrics.filter((m) => !used.has(m.key) && g.match(m.key));
    items.forEach((m) => used.add(m.key));
    return { ...g, items };
  });
  const rest = metrics.filter((m) => !used.has(m.key));
  if (rest.length) groups.push({ title: "Weitere Kanäle", match: () => true, items: rest });
  return (
    <div className="grid cols-2">
      {groups
        .filter((g) => g.items.length)
        .map((g) => (
          <div key={g.title}>
            <h3>{g.title}</h3>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Kennzahl</th>
                    <th className="num">Wert</th>
                    <th className="num" title="Vom Gerät berechnet (z. B. STR.edf)">Gerät</th>
                    <th className="num" title="Von Sleepy aus den Rohdaten berechnet">Berechnet</th>
                  </tr>
                </thead>
                <tbody>
                  {g.items.map((m) => (
                    <tr key={m.key}>
                      <td>{m.label}</td>
                      <td className="num">
                        <strong>{fmtMetric(m.value, m.unit, m.decimals)}</strong>
                      </td>
                      <td className="num muted">{m.device != null ? num(m.device, m.decimals) : "–"}</td>
                      <td className="num muted">{m.computed != null ? num(m.computed, m.decimals) : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
    </div>
  );
}

function Notes({ id, text }: { id: number; text: string | null }) {
  const qc = useQueryClient();
  const [v, setV] = useState(text || "");
  useEffect(() => setV(text || ""), [text]);
  const m = useMutation({
    mutationFn: () => api.patch(`/api/nights/${id}`, { notes: v }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["night", id] }),
  });
  return (
    <div className="stack" style={{ gap: "0.5rem" }}>
      <textarea rows={3} value={v} onChange={(e) => setV(e.target.value)} placeholder="Eigene Notizen zu dieser Nacht (z. B. neue Maske, Erkältung …)" />
      <div className="row">
        <button className="small" onClick={() => m.mutate()} disabled={m.isPending || v === (text || "")}>
          Notiz speichern
        </button>
        {m.isSuccess && <span className="small muted">gespeichert</span>}
        <ErrorBox error={m.error} />
      </div>
    </div>
  );
}

export default function NightDetail() {
  const { id } = useParams();
  const nightId = Number(id);
  const [tab, setTab] = useState<"analysis" | "metrics" | "details">("analysis");
  const [focus, setFocus] = useState<{ start: number; end: number; key: number } | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<number | null>(null);

  const nq = useQuery({ queryKey: ["night", nightId], queryFn: () => api.get<ND>(`/api/nights/${nightId}`) });
  const eq = useQuery({ queryKey: ["night-events", nightId], queryFn: () => api.get<EventsResponse>(`/api/nights/${nightId}/events`) });
  const iq = useQuery({ queryKey: ["night-insights", nightId], queryFn: () => api.get<Insights>(`/api/nights/${nightId}/insights`) });

  useEffect(() => {
    setFocus(null);
    setSelectedEvent(null);
  }, [nightId]);

  const onSelectEvent = useCallback((e: NightEvent) => {
    setSelectedEvent(e.id);
    setFocus({ start: e.start_ms, end: Math.max(e.end_ms, e.start_ms + 1000), key: Date.now() });
  }, []);

  const zoomTo = (start?: number, end?: number) => {
    if (start === undefined || end === undefined) return;
    setFocus({ start, end, key: Date.now() });
  };

  const types = eq.data?.types || {};
  const disp = useMemo(() => {
    const out: Record<string, MetricDetail> = {};
    for (const m of nq.data?.metrics || []) out[m.key] = m;
    return out;
  }, [nq.data]);

  if (nq.isLoading) return <Loading />;
  if (nq.error) return <ErrorBox error={nq.error} />;
  const d = nq.data!;
  const n = d.night;
  const v = (k: string) => disp[k]?.value ?? null;
  const src = (k: string) => (disp[k]?.source === "device" ? "Gerätewert" : disp[k]?.source === "computed" ? "berechnet" : undefined);

  return (
    <div className="stack">
      <Card
        title={
          <div className="row">
            <StatusDot status={n.status} />
            <h1 style={{ margin: 0 }}>
              {weekday(n.date)} {dateDe(n.date)}
            </h1>
            <span className="muted small">
              {clock(n.start_ms)} – {clock(n.end_ms)} · {n.device?.model ?? n.device?.manufacturer} (SN {n.device?.serial})
            </span>
          </div>
        }
        actions={
          <>
            {d.prev_id && (
              <Link className="btn small" to={`/nights/${d.prev_id}`}>
                ← Vorherige
              </Link>
            )}
            {d.next_id && (
              <Link className="btn small" to={`/nights/${d.next_id}`}>
                Nächste →
              </Link>
            )}
            <a className="btn small" href={`/api/export/nights/${nightId}/timeseries.csv`}>
              Rohsignale (CSV)
            </a>
          </>
        }
      >
        <div className="kpis">
          <Kpi big label="Therapiezeit" value={hm(v("usage_h"))} sub={`${n.session_count} Sitzung(en)`} />
          <Kpi big label="AHI" value={num(v("ahi"), 2)} sub={src("ahi")} title={disp.ahi ? `Gerät: ${num(disp.ahi.device, 2)} · berechnet: ${num(disp.ahi.computed, 2)}` : undefined} />
          {v("ai") != null && <Kpi label="AI" value={num(v("ai"), 2)} />}
          {v("hi") != null && <Kpi label="HI" value={num(v("hi"), 2)} />}
          {v("oai") != null && <Kpi label="OAI" value={num(v("oai"), 2)} />}
          {v("cai") != null && <Kpi label="CAI" value={num(v("cai"), 2)} />}
          {v("uai") != null && <Kpi label="UAI" value={num(v("uai"), 2)} />}
          {v("rera_index") != null && <Kpi label="RERA-Index" value={num(v("rera_index"), 2)} />}
          {v("rdi") != null && <Kpi label="RDI" value={num(v("rdi"), 2)} />}
          {v("odi") != null && <Kpi label="ODI (3 %)" value={num(v("odi"), 2)} sub="berechnet" />}
          {v("leak.median") != null && <Kpi label="Leck Median" value={num(v("leak.median"), 1)} sub="L/min" />}
          {v("leak.p95") != null && <Kpi label="Leck 95 %" value={num(v("leak.p95"), 1)} sub={`max ${num(v("leak.max"), 1)} L/min`} />}
          {v("pressure.median") != null && <Kpi label="Druck Median" value={num(v("pressure.median"), 1)} sub="cmH2O" />}
          {v("pressure.p95") != null && <Kpi label="Druck 95 %" value={num(v("pressure.p95"), 1)} sub={`max ${num(v("pressure.max"), 1)}`} />}
          {v("epap.median") != null && <Kpi label="EPAP Median" value={num(v("epap.median"), 1)} sub={`95 %: ${num(v("epap.p95"), 1)}`} />}
          {v("ipap.median") != null && <Kpi label="IPAP Median" value={num(v("ipap.median"), 1)} sub={`95 %: ${num(v("ipap.p95"), 1)}`} />}
          {v("flow_limit.p95") != null && <Kpi label="Flusslim. 95 %" value={num(v("flow_limit.p95"), 2)} sub={`Median ${num(v("flow_limit.median"), 2)}`} />}
          {v("resp_rate.median") != null && <Kpi label="Atemfrequenz" value={num(v("resp_rate.median"), 1)} sub="/min (Median)" />}
          {v("minute_vent.median") != null && <Kpi label="Minutenvol." value={num(v("minute_vent.median"), 1)} sub="L/min (Median)" />}
          {v("tidal_volume.median") != null && <Kpi label="Atemzugvol." value={num(v("tidal_volume.median"), 0)} sub="mL (Median)" />}
          {v("snore.p95") != null && <Kpi label="Schnarchen 95 %" value={num(v("snore.p95"), 2)} />}
          {v("spo2.median") != null ? (
            <Kpi label="SpO2 Median" value={num(v("spo2.median"), 0)} sub={`min ${num(v("spo2.min"), 0)} %`} />
          ) : (
            <Kpi label="SpO2" value="–" sub="Keine SpO2-Daten verfügbar" />
          )}
          {v("pulse.mean") != null && <Kpi label="Puls Ø" value={num(v("pulse.mean"), 0)} sub="/min" />}
        </div>
        {!n.has_detail && (
          <div className="alert info" style={{ marginTop: "0.75rem" }}>
            Für diese Nacht liegen nur die Tageszusammenfassungswerte des Geräts vor (keine Detaildateien im DATALOG).
          </div>
        )}
      </Card>

      <div className="tabs" role="tablist">
        <button className={tab === "analysis" ? "active" : ""} onClick={() => setTab("analysis")}>
          Analyse & Diagramme
        </button>
        <button className={tab === "metrics" ? "active" : ""} onClick={() => setTab("metrics")}>
          Alle Kennzahlen
        </button>
        <button className={tab === "details" ? "active" : ""} onClick={() => setTab("details")}>
          Sitzungen, Einstellungen & Herkunft
        </button>
      </div>

      {tab === "analysis" && (
        <>
          <Card title="Zusammenfassung">
            {iq.isLoading && <Loading text="Analysiere …" />}
            <ErrorBox error={iq.error} />
            {iq.data && (
              <div className="stack" style={{ gap: "0.75rem" }}>
                <p style={{ margin: 0 }}>{iq.data.summary}</p>
                {iq.data.anomalies.length > 0 && (
                  <div className="alert warn">
                    <strong>Statistisch auffällig (im Vergleich zu deinen letzten {iq.data.baseline.nights} Nächten):</strong>
                    <ul className="obs-list">
                      {iq.data.anomalies.map((a) => (
                        <li key={a.key}>{a.text}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {iq.data.observations.length > 0 && (
                  <div>
                    <strong>Beobachtungen</strong>
                    <ul className="obs-list">
                      {iq.data.observations.map((o, i) => (
                        <li key={i}>
                          {o.text}{" "}
                          {o.start_ms !== undefined && (
                            <button className="small ghost" onClick={() => zoomTo(o.start_ms, o.end_ms)}>
                              anzeigen
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <Disclaimer text={iq.data.disclaimer} />
              </div>
            )}
          </Card>

          {n.has_detail && d.channels.length > 0 ? (
            <Card title="Diagramme">
              <NightCharts
                nightId={nightId}
                channels={d.channels}
                events={eq.data?.items || []}
                eventTypes={types}
                startMs={n.start_ms!}
                endMs={n.end_ms!}
                leakThreshold={d.leak_threshold}
                focus={focus}
              />
            </Card>
          ) : (
            <Card title="Diagramme">
              <p className="muted">Keine Signaldaten (Zeitreihen) für diese Nacht vorhanden.</p>
            </Card>
          )}

          <div className="grid cols-2">
            <Card title={`Ereignisse (${eq.data?.items.length ?? 0})`}>
              {eq.data && (
                <EventList
                  events={eq.data.items}
                  types={types}
                  contextChannels={eq.data.context_channels}
                  selectedId={selectedEvent}
                  onSelect={onSelectEvent}
                />
              )}
            </Card>
            <div className="stack">
              <Card title="Ereignisse pro Stunde">{iq.data && <HourlyChart ins={iq.data} types={types} />}</Card>
              {iq.data && iq.data.clusters.length > 0 && (
                <Card title="Ereignis-Cluster">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Zeitraum</th>
                        <th className="num">Anzahl</th>
                        <th>Typen</th>
                        <th className="num">Rate/h</th>
                      </tr>
                    </thead>
                    <tbody>
                      {iq.data.clusters.map((c) => (
                        <tr key={c.start_ms} className="clickable" onClick={() => zoomTo(c.start_ms, c.end_ms)}>
                          <td>
                            {clock(c.start_ms)} – {clock(c.end_ms)}
                          </td>
                          <td className="num">{c.count}</td>
                          <td>
                            {Object.entries(c.by_code).map(([k, nn]) => (
                              <span key={k} style={{ marginRight: 4 }}>
                                <EventChip code={k} color={types[k]?.color} short={`${nn}× ${types[k]?.short ?? k}`} />
                              </span>
                            ))}
                          </td>
                          <td className="num">{num(c.rate_per_hour, 0)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              )}
            </div>
          </div>
          <Card title="Kanäle rund um Ereignisse">{iq.data && <PeriEventChart ins={iq.data} />}</Card>
          <Card title="Notizen">
            <Notes id={nightId} text={n.notes_text} />
          </Card>
        </>
      )}

      {tab === "metrics" && (
        <Card title="Alle verfügbaren Kennzahlen">
          <p className="muted small">
            Es werden nur Werte angezeigt, die tatsächlich aus den Daten verfügbar sind. „Gerät“ = vom PAP-Gerät selbst berechnet (z. B.
            STR.edf), „Berechnet“ = von Sleepy aus den Detaildaten berechnet. Für die Ereignisindizes wird standardmäßig der Gerätewert
            angezeigt.
          </p>
          <MetricsTable metrics={d.metrics} />
        </Card>
      )}

      {tab === "details" && (
        <div className="stack">
          <Card title="Sitzungen (Maske auf/ab)">
            <table className="table">
              <thead>
                <tr>
                  <th>Beginn</th>
                  <th>Ende</th>
                  <th className="num">Dauer</th>
                  <th>Quelle</th>
                  <th>Dateien</th>
                </tr>
              </thead>
              <tbody>
                {d.sessions.map((s) => (
                  <tr key={s.id} className="clickable" onClick={() => { setTab("analysis"); zoomTo(s.start_ms, s.end_ms); }}>
                    <td>{clock(s.start_ms, true)}</td>
                    <td>{clock(s.end_ms, true)}</td>
                    <td className="num">{duration(s.duration_s)}</td>
                    <td>{s.source === "detail" ? "Detaildaten" : "Zusammenfassung"}</td>
                    <td className="small mono">{s.files.map((f) => f.split("/").pop()).join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          <div className="grid cols-2">
            <Card title="Geräteeinstellungen dieser Nacht">
              {d.settings.length ? (
                <table className="table">
                  <tbody>
                    {d.settings.map((s) => (
                      <tr key={s.key}>
                        <td>{s.label}</td>
                        <td className="num">{String(s.value)}</td>
                        <td className="muted small mono">{s.key}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="muted">Keine Einstellungen verfügbar.</p>
              )}
            </Card>
            <Card title="Kanäle">
              <table className="table">
                <thead>
                  <tr>
                    <th>Kanal</th>
                    <th>Label (Rohdatei)</th>
                    <th className="num">Rate</th>
                    <th>Einheit</th>
                  </tr>
                </thead>
                <tbody>
                  {d.channels.map((c) => (
                    <tr key={c.code} title={c.conversion ?? undefined}>
                      <td>{c.name}</td>
                      <td className="mono small">{c.label}</td>
                      <td className="num">{num(c.sample_rate, c.sample_rate < 1 ? 1 : 0)} Hz</td>
                      <td>
                        {c.unit}
                        {c.conversion && <span className="muted small"> ({c.conversion})</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>
          <Card title="Herkunft der Daten (Rohdateien)">
            <p className="muted small">
              Parser {n.parser} {n.parser_version} · zuletzt berechnet {dateTimeDe(n.updated_at)}. Alle Originaldateien sind unverändert archiviert.
            </p>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Datei (Pfad auf der SD-Karte)</th>
                    <th className="num">Größe</th>
                    <th>SHA-256</th>
                    <th>Importiert</th>
                  </tr>
                </thead>
                <tbody>
                  {d.source_files.map((f) => (
                    <tr key={f.rel_path}>
                      <td className="mono small">{f.rel_path}</td>
                      <td className="num">{bytes(f.size)}</td>
                      <td className="mono small" title={f.sha256 ?? ""}>
                        {f.sha256?.slice(0, 16)}…
                      </td>
                      <td className="small">{dateTimeDe(f.imported_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          {n.warnings.length > 0 && (
            <Card title="Hinweise beim Einlesen">
              <ul className="obs-list small">
                {n.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </Card>
          )}
          {Object.keys(d.summary_raw).length > 0 && (
            <Card title="Rohwerte der Tageszusammenfassung (Gerät)">
              <details>
                <summary className="small">{Object.keys(d.summary_raw).length} Werte anzeigen</summary>
                <table className="table">
                  <tbody>
                    {Object.entries(d.summary_raw).map(([k, val]) => (
                      <tr key={k}>
                        <td className="mono small">{k}</td>
                        <td className="num small">{Array.isArray(val) ? val.join(", ") : String(val)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            </Card>
          )}
        </div>
      )}
      <Disclaimer text={d.disclaimer} />
    </div>
  );
}
