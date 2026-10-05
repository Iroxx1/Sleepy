import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, qs } from "../api/client";
import type { PeriodSummary } from "../api/types";
import { useDevice } from "../hooks/useDevice";
import { Card, Disclaimer, ErrorBox, Kpi, Loading, StatusDot } from "../components/ui";
import { addDays, dateDe, hm, num, today } from "../lib/format";

interface Report {
  title: string;
  from: string;
  to: string;
  summary: PeriodSummary;
  highlights: string[];
  anomalies: { date: string; night_id: number; text: string }[];
  nights: { id: number; date: string; status: string; usage_h: number | null; all_metrics: Record<string, number> }[];
  disclaimer: string;
}

export default function Reports() {
  const { deviceId } = useDevice();
  const [kind, setKind] = useState<"week" | "month" | "custom">("week");
  const [weekStart, setWeekStart] = useState("");
  const [month, setMonth] = useState(today().slice(0, 7));
  const [from, setFrom] = useState(addDays(today(), -29));
  const [to, setTo] = useState(today());
  const params = useMemo(() => {
    const p: Record<string, string | number | null> = { device_id: deviceId };
    if (kind === "week" && weekStart) p.start = weekStart;
    if (kind === "month") p.month = month;
    if (kind === "custom") {
      p.start = from;
      p.end = to;
    }
    return p;
  }, [kind, weekStart, month, from, to, deviceId]);
  const q = useQuery({ queryKey: ["report", kind, params], queryFn: () => api.get<Report>(`/api/reports/${kind}`, { ...params, format: "json" }) });
  const url = (fmt: string, download = false) => `/api/reports/${kind}${qs({ ...params, format: fmt, download: download || undefined })}`;

  // export section
  const [exFrom, setExFrom] = useState("");
  const [exTo, setExTo] = useState("");
  const [withTs, setWithTs] = useState(false);
  const [sep, setSep] = useState("comma");
  const formats = useQuery({ queryKey: ["export-formats"], queryFn: () => api.get<{ parquet: boolean }>("/api/export/formats") });
  const exParams = { from: exFrom || undefined, to: exTo || undefined, device_id: deviceId ?? undefined };

  const r = q.data;
  return (
    <div className="stack">
      <Card title="Berichte">
        <div className="row">
          <div className="btn-group">
            <button className={kind === "week" ? "active" : ""} onClick={() => setKind("week")}>
              Wochenbericht
            </button>
            <button className={kind === "month" ? "active" : ""} onClick={() => setKind("month")}>
              Monatsbericht
            </button>
            <button className={kind === "custom" ? "active" : ""} onClick={() => setKind("custom")}>
              Zeitraum
            </button>
          </div>
          {kind === "week" && (
            <label className="field">
              Woche mit Tag
              <input type="date" value={weekStart} onChange={(e) => setWeekStart(e.target.value)} />
            </label>
          )}
          {kind === "month" && (
            <label className="field">
              Monat
              <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
            </label>
          )}
          {kind === "custom" && (
            <>
              <label className="field">
                Von
                <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
              </label>
              <label className="field">
                Bis
                <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
              </label>
            </>
          )}
          <span className="grow" />
          <a className="btn" href={url("html")} target="_blank" rel="noreferrer">
            HTML öffnen
          </a>
          <a className="btn" href={url("html", true)}>
            HTML
          </a>
          <a className="btn primary" href={url("pdf", true)}>
            PDF
          </a>
          <a className="btn" href={url("csv", true)}>
            CSV
          </a>
          <a className="btn" href={url("json", true)}>
            JSON
          </a>
        </div>
      </Card>
      <ErrorBox error={q.error} />
      {q.isLoading && <Loading />}
      {r && (
        <Card title={`${r.title} · ${dateDe(r.from)} – ${dateDe(r.to)}`}>
          <div className="kpis">
            <Kpi label="Nächte" value={`${r.summary.compliance.nights_with_data}/${r.summary.compliance.days}`} />
            <Kpi label="Ø Nutzung" value={hm(r.summary.stats.usage_h?.mean)} />
            <Kpi label="Ø AHI" value={num(r.summary.stats.ahi?.mean, 2)} sub={`Median ${num(r.summary.stats.ahi?.median, 2)}`} />
            <Kpi label="Ø Leck 95 %" value={num(r.summary.stats["leak.p95"]?.mean, 1)} sub="L/min" />
            <Kpi label="Tage ≥ 4 h" value={`${num(r.summary.compliance.pct_ge_4h, 0)} %`} />
          </div>
          <h3 style={{ marginTop: "1rem" }}>Zusammenfassung</h3>
          <ul className="obs-list">
            {r.highlights.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
          {r.anomalies.length > 0 && (
            <>
              <h3>Statistische Auffälligkeiten</h3>
              <ul className="obs-list">
                {r.anomalies.map((a, i) => (
                  <li key={i}>
                    <Link to={`/nights/${a.night_id}`}>{dateDe(a.date)}</Link>: {a.text}
                  </li>
                ))}
              </ul>
            </>
          )}
          <h3>Nächte</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th />
                  <th>Datum</th>
                  <th className="num">Nutzung</th>
                  <th className="num">AHI</th>
                  <th className="num">Leck 95 %</th>
                  <th className="num">Druck 95 %</th>
                </tr>
              </thead>
              <tbody>
                {r.nights.map((n) => (
                  <tr key={n.id}>
                    <td>
                      <StatusDot status={n.status} />
                    </td>
                    <td>
                      <Link to={`/nights/${n.id}`}>{dateDe(n.date)}</Link>
                    </td>
                    <td className="num">{hm(n.usage_h)}</td>
                    <td className="num">{num(n.all_metrics.ahi, 2)}</td>
                    <td className="num">{num(n.all_metrics["leak.p95"], 1)}</td>
                    <td className="num">{num(n.all_metrics["pressure.p95"], 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card title="Datenexport">
        <div className="row" style={{ alignItems: "flex-end" }}>
          <label className="field">
            Von (optional)
            <input type="date" value={exFrom} onChange={(e) => setExFrom(e.target.value)} />
          </label>
          <label className="field">
            Bis (optional)
            <input type="date" value={exTo} onChange={(e) => setExTo(e.target.value)} />
          </label>
          <label className="field">
            CSV-Trennzeichen
            <select value={sep} onChange={(e) => setSep(e.target.value)}>
              <option value="comma">Komma</option>
              <option value="semicolon">Semikolon (Excel DE)</option>
            </select>
          </label>
        </div>
        <div className="grid cols-2" style={{ marginTop: "1rem" }}>
          <div>
            <h3>Analysierte Daten</h3>
            <div className="row">
              <a className="btn small" href={`/api/export/nights.csv${qs({ ...exParams, sep })}`}>
                Nächte CSV
              </a>
              <a className="btn small" href={`/api/export/nights.json${qs(exParams)}`}>
                Nächte JSON
              </a>
              {formats.data?.parquet ? (
                <a className="btn small" href={`/api/export/nights.parquet${qs(exParams)}`}>
                  Nächte Parquet
                </a>
              ) : (
                <span className="muted small" title="Optional: pip install pandas pyarrow">
                  Parquet nicht installiert
                </span>
              )}
              <a className="btn small" href={`/api/export/events.csv${qs(exParams)}`}>
                Ereignisse CSV
              </a>
              <a className="btn small" href={`/api/export/events.json${qs(exParams)}`}>
                Ereignisse JSON
              </a>
            </div>
            <div className="row" style={{ marginTop: "0.75rem" }}>
              <label className="check small">
                <input type="checkbox" checked={withTs} onChange={(e) => setWithTs(e.target.checked)} /> inkl. aller Zeitreihen in voller Auflösung (groß!)
              </label>
              <a className="btn small primary" href={`/api/export/archive.zip${qs({ ...exParams, timeseries: withTs || undefined })}`}>
                Komplettexport ZIP
              </a>
            </div>
          </div>
          <div>
            <h3>Originaldaten</h3>
            <p className="small muted">Die unveränderten Originaldateien in der Verzeichnisstruktur der SD-Karte (jeweils neueste Version).</p>
            <a className="btn small" href={`/api/export/raw.zip${qs(exParams)}`}>
              Originaldaten ZIP
            </a>
          </div>
        </div>
      </Card>
      <Disclaimer />
    </div>
  );
}
