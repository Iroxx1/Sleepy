import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { EventType, PeriodSummary, TrendSeries } from "../api/types";
import { useDevice } from "../hooks/useDevice";
import { useTheme } from "../hooks/useTheme";
import { Card, Disclaimer, ErrorBox, Kpi, Loading } from "../components/ui";
import EChart from "../components/EChart";
import { chartTheme, colorFor } from "../lib/echarts";
import { dateDe, fmtMetric, hm, num } from "../lib/format";

export const PRESETS: [string, string][] = [
  ["7", "7 Tage"],
  ["30", "30 Tage"],
  ["90", "90 Tage"],
  ["180", "6 Monate"],
  ["365", "1 Jahr"],
  ["all", "Alles"],
  ["custom", "Zeitraum"],
];

const METRIC_CHOICES: [string, string][] = [
  ["ahi", "AHI"],
  ["usage_h", "Nutzungsdauer"],
  ["cai", "CAI"],
  ["oai", "OAI"],
  ["hi", "HI"],
  ["rdi", "RDI"],
  ["rera_index", "RERA-Index"],
  ["leak.p95", "Leckage 95 %"],
  ["leak.median", "Leckage Median"],
  ["pressure.p95", "Druck 95 %"],
  ["pressure.median", "Druck Median"],
  ["epap.median", "EPAP Median"],
  ["flow_limit.p95", "Flusslimitierung 95 %"],
  ["snore.p95", "Schnarchen 95 %"],
  ["resp_rate.median", "Atemfrequenz"],
  ["tidal_volume.median", "Atemzugvolumen"],
  ["minute_vent.median", "Atemminutenvolumen"],
  ["spo2.median", "SpO2 Median"],
  ["pulse.mean", "Puls"],
  ["odi", "ODI"],
  ["csr_pct", "CSR-Anteil"],
];

export function PeriodPicker({
  preset,
  setPreset,
  from,
  to,
  setFrom,
  setTo,
}: {
  preset: string;
  setPreset: (p: string) => void;
  from: string;
  to: string;
  setFrom: (s: string) => void;
  setTo: (s: string) => void;
}) {
  return (
    <div className="row">
      <div className="btn-group">
        {PRESETS.map(([k, l]) => (
          <button key={k} className={`small ${preset === k ? "active" : ""}`} onClick={() => setPreset(k)}>
            {l}
          </button>
        ))}
      </div>
      {preset === "custom" && (
        <>
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="Von" />
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="Bis" />
        </>
      )}
    </div>
  );
}

export interface HwMarker {
  date: string;
  kind: "start" | "end";
  name: string;
  category_label: string;
}

function TrendChart({ s, onClick, markers }: { s: TrendSeries; onClick: (id: number) => void; markers?: HwMarker[] }) {
  const { resolved } = useTheme();
  const option = useMemo(() => {
    const t = chartTheme();
    const color = colorFor(s.key.split(".")[0] === "usage_h" ? "usage" : s.key.split(".")[0]);
    const isBar = s.key === "usage_h" || s.x.length <= 45;
    const series: object[] = [
      {
        name: s.label,
        type: isBar ? "bar" : "line",
        data: s.y.map((v) => (v == null ? null : +v.toFixed(3))),
        itemStyle: { color, opacity: isBar ? 0.75 : 1, borderRadius: isBar ? [2, 2, 0, 0] : 0 },
        showSymbol: s.x.length < 120,
        symbolSize: 4,
        connectNulls: false,
      },
    ];
    const idx = (d: string) => s.x.indexOf(d);
    const marks = (markers || []).filter((m) => m.kind === "start" && idx(m.date) >= 0);
    if (marks.length) {
      (series[0] as Record<string, unknown>).markLine = {
        silent: false,
        symbol: "none",
        lineStyle: { color: "#9333ea", type: "dashed", width: 1.5 },
        label: { formatter: (p: { name: string }) => p.name, color: t.muted, fontSize: 10, position: "insideEndTop" },
        data: marks.map((m) => ({ xAxis: idx(m.date), name: `${m.category_label}: ${m.name}` })),
      };
    }
    if (s.rolling7) {
      series.push({ name: "Ø 7 Tage", type: "line", data: s.rolling7.map((v) => (v == null ? null : +v.toFixed(3))), showSymbol: false, lineStyle: { width: 2, color: t.text, opacity: 0.6 }, itemStyle: { color: t.text } });
    }
    if (s.min && s.max) {
      series.push({ name: "Min", type: "line", data: s.min, showSymbol: false, lineStyle: { type: "dotted", color }, itemStyle: { color } });
      series.push({ name: "Max", type: "line", data: s.max, showSymbol: false, lineStyle: { type: "dotted", color }, itemStyle: { color } });
    }
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: {
        trigger: "axis",
        backgroundColor: t.tooltipBg,
        textStyle: { color: t.text },
        valueFormatter: (v: number) => (v == null ? "–" : fmtMetric(v, s.unit, s.decimals)),
      },
      legend: { textStyle: { color: t.muted }, top: 0 },
      grid: { left: 48, right: 16, top: 30, bottom: 50 },
      xAxis: { type: "category", data: s.x.map((x) => (x.length === 10 ? dateDe(x).slice(0, 6) : x)), axisLabel: { color: t.muted } },
      yAxis: { type: "value", scale: !isBar, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.grid } }, name: s.unit, nameTextStyle: { color: t.muted } },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 8 }],
      series,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s, resolved, markers]);
  return (
    <EChart
      option={option}
      height={260}
      notMerge
      onEvents={{
        click: (p: { dataIndex: number }) => {
          const id = s.night_ids?.[p.dataIndex];
          if (id) onClick(id);
        },
      }}
    />
  );
}

export default function Trends() {
  const { deviceId } = useDevice();
  const nav = useNavigate();
  const { resolved } = useTheme();
  const [preset, setPreset] = useState("30");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [metrics, setMetrics] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("sleepy-trend-metrics") || "") as string[];
    } catch {
      return ["ahi", "usage_h", "leak.p95", "pressure.p95"];
    }
  });
  const period = preset === "custom" ? { from: from || undefined, to: to || undefined } : { preset };
  const sq = useQuery({
    queryKey: ["stats-summary", period, deviceId],
    queryFn: () => api.get<PeriodSummary>("/api/statistics/summary", { ...period, device_id: deviceId }),
    enabled: preset !== "custom" || (!!from && !!to),
  });
  const span = sq.data ? (Date.parse(sq.data.to) - Date.parse(sq.data.from)) / 86400000 : 30;
  const bucket = span > 400 ? "month" : span > 190 ? "week" : "day";
  const tq = useQuery({
    queryKey: ["trends", period, deviceId, metrics.join(","), bucket],
    queryFn: () =>
      api.get<{ series: Record<string, TrendSeries> }>("/api/statistics/trends", {
        ...period,
        device_id: deviceId,
        metrics: metrics.join(","),
        bucket,
      }),
    enabled: metrics.length > 0 && (preset !== "custom" || (!!from && !!to)),
  });
  const markers = useQuery({ queryKey: ["hw-timeline"], queryFn: () => api.get<HwMarker[]>("/api/hardware/timeline") });
  const types = useQuery({ queryKey: ["event-types"], queryFn: () => api.get<Record<string, EventType>>("/api/events/types") });

  function toggleMetric(k: string) {
    const n = metrics.includes(k) ? metrics.filter((x) => x !== k) : [...metrics, k];
    setMetrics(n);
    try {
      localStorage.setItem("sleepy-trend-metrics", JSON.stringify(n));
    } catch {
      /* ignore */
    }
  }

  const eventsOption = useMemo(() => {
    const s = sq.data;
    if (!s) return null;
    const t = chartTheme();
    const ty = types.data || {};
    const entries = Object.entries(s.event_totals).filter(([c]) => c !== "OTHER");
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "item", backgroundColor: t.tooltipBg, textStyle: { color: t.text } },
      grid: [
        { left: 90, right: 16, top: 10, bottom: "55%" },
        { left: 40, right: 16, top: "58%", bottom: 24 },
      ],
      xAxis: [
        { type: "value", gridIndex: 0, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.grid } } },
        { type: "category", gridIndex: 1, data: Array.from({ length: 24 }, (_, h) => `${h}`), axisLabel: { color: t.muted }, name: "Uhr", nameTextStyle: { color: t.muted } },
      ],
      yAxis: [
        { type: "category", gridIndex: 0, data: entries.map(([c]) => ty[c]?.name ?? c), axisLabel: { color: t.muted } },
        { type: "value", gridIndex: 1, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.grid } }, minInterval: 1 },
      ],
      series: [
        {
          type: "bar",
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: entries.map(([c, n]) => ({ value: n, itemStyle: { color: ty[c]?.color } })),
          label: { show: true, position: "right", color: t.muted },
        },
        {
          name: "Apnoen/Hypopnoen nach Uhrzeit",
          type: "bar",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: Array.from({ length: 24 }, (_, h) => s.events_by_clock_hour[String(h)] ?? 0),
          itemStyle: { color: "#2563eb" },
        },
      ],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sq.data, types.data, resolved]);

  const s = sq.data;
  const prev = s?.previous;
  return (
    <div className="stack">
      <Card>
        <PeriodPicker preset={preset} setPreset={setPreset} from={from} to={to} setFrom={setFrom} setTo={setTo} />
      </Card>
      <ErrorBox error={sq.error} />
      {sq.isLoading && <Loading />}
      {s && (
        <>
          <Card title={`Überblick ${dateDe(s.from)} – ${dateDe(s.to)}`}>
            <div className="kpis">
              <Kpi label="Nächte mit Daten" value={`${s.compliance.nights_with_data}/${s.compliance.days}`} sub={`${num(s.compliance.pct_nights_used, 0)} %`} />
              <Kpi label="Nächte ≥ 4 h" value={`${num(s.compliance.pct_ge_4h, 0)} %`} sub={`${s.compliance.nights_ge_4h} Nächte`} />
              <Kpi label="Ø Nutzung" value={hm(s.stats.usage_h?.mean)} sub={prev?.means.usage_h != null ? `Vorher ${hm(prev.means.usage_h)}` : undefined} />
              <Kpi label="Ø AHI" value={num(s.stats.ahi?.mean, 2)} sub={`Median ${num(s.stats.ahi?.median, 2)}${prev?.means.ahi != null ? ` · vorher Ø ${num(prev.means.ahi, 2)}` : ""}`} />
              <Kpi label="Ø Leck 95 %" value={num(s.stats["leak.p95"]?.mean, 1)} sub="L/min" />
              <Kpi label="Ø Druck 95 %" value={num(s.stats["pressure.p95"]?.mean, 1)} sub="cmH2O" />
              <Kpi label="Gesamtstunden" value={num(s.compliance.total_hours, 0)} />
              {s.best && (
                <Kpi label="Niedrigster AHI" value={num(s.best.ahi, 2)} sub={<Link to={`/nights/${s.best.id}`}>{dateDe(s.best.date)}</Link>} />
              )}
              {s.worst && (
                <Kpi label="Höchster AHI" value={num(s.worst.ahi, 2)} sub={<Link to={`/nights/${s.worst.id}`}>{dateDe(s.worst.date)}</Link>} />
              )}
            </div>
            {Object.values(s.trends).some((t) => t.direction !== "stabil") && (
              <div className="alert info" style={{ marginTop: "0.75rem" }}>
                <strong>Statistische Trends:</strong>{" "}
                {Object.values(s.trends)
                  .filter((t) => t.direction !== "stabil")
                  .map((t) => `${t.label} ${t.direction} (${num(t.slope_per_30d, 2)} ${t.unit} / 30 Tage)`)
                  .join(" · ")}
              </div>
            )}
          </Card>

          <Card title="Statistik">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Kennzahl</th>
                    <th className="num">n</th>
                    <th className="num">Mittel</th>
                    <th className="num">Median</th>
                    <th className="num">Min</th>
                    <th className="num">Max</th>
                    <th className="num">Std.-Abw.</th>
                    <th className="num">5 %</th>
                    <th className="num">95 %</th>
                    <th className="num">Vorperiode Ø</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.values(s.stats).map((st) => (
                    <tr key={st.key}>
                      <td>
                        {st.label}
                        {st.unit && st.unit !== "h" && <span className="muted"> ({st.unit})</span>}
                      </td>
                      <td className="num">{st.n}</td>
                      <td className="num">{fmtMetric(st.mean, st.unit === "h" ? "h" : "", st.decimals)}</td>
                      <td className="num">{fmtMetric(st.median, st.unit === "h" ? "h" : "", st.decimals)}</td>
                      <td className="num">{fmtMetric(st.min, st.unit === "h" ? "h" : "", st.decimals)}</td>
                      <td className="num">{fmtMetric(st.max, st.unit === "h" ? "h" : "", st.decimals)}</td>
                      <td className="num">{fmtMetric(st.std, st.unit === "h" ? "h" : "", st.decimals)}</td>
                      <td className="num">{fmtMetric(st.p5, st.unit === "h" ? "h" : "", st.decimals)}</td>
                      <td className="num">{fmtMetric(st.p95, st.unit === "h" ? "h" : "", st.decimals)}</td>
                      <td className="num muted">{prev?.means[st.key] != null ? fmtMetric(prev.means[st.key], st.unit === "h" ? "h" : "", st.decimals) : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      <Card title="Trend-Diagramme">
        <div className="channel-picker" style={{ marginBottom: "0.75rem" }}>
          {METRIC_CHOICES.map(([k, l]) => (
            <label key={k} className="check small">
              <input type="checkbox" checked={metrics.includes(k)} onChange={() => toggleMetric(k)} /> {l}
            </label>
          ))}
        </div>
        {(markers.data || []).some((m) => m.kind === "start") && bucket === "day" && (
          <p className="muted small">Lila gestrichelte Linien: Beginn neuer Hardware (z. B. neue Maske) laut Bereich „Hardware“.</p>
        )}
        {bucket !== "day" && <p className="muted small">Langer Zeitraum: Werte als {bucket === "week" ? "Wochen" : "Monats"}-Mittel mit Min/Max (aggregiert).</p>}
        <ErrorBox error={tq.error} />
        {tq.isLoading && <Loading />}
        <div className="grid cols-2">
          {metrics.map((k) => {
            const ser = tq.data?.series[k];
            if (!ser) return null;
            const hasData = ser.y.some((v) => v != null);
            return (
              <div key={k}>
                <h3>
                  {ser.label}
                  {ser.trend && ser.trend.direction !== "stabil" && <span className="badge info" style={{ marginLeft: 8 }}>{ser.trend.direction}</span>}
                </h3>
                {hasData ? <TrendChart s={ser} markers={markers.data} onClick={(id) => nav(`/nights/${id}`)} /> : <p className="muted">Keine Daten für diese Kennzahl verfügbar.</p>}
              </div>
            );
          })}
        </div>
      </Card>

      {eventsOption && (
        <Card title="Ereignisverteilung">
          <EChart option={eventsOption} height={420} notMerge />
        </Card>
      )}
      <Disclaimer />
    </div>
  );
}
