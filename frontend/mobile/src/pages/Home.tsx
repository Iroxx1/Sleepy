import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { Dashboard, HardwareList } from "../../../src/api/types";
import { Disclaimer, Dot, ErrorMsg, Section, Spinner, Tile } from "../components/ui";
import MChart, { pinchZoom } from "../components/MChart";
import { chartTheme, PALETTE } from "../../../src/lib/echarts";
import { useTheme } from "../../../src/hooks/useTheme";
import { dateDe, hm, num, weekday } from "../../../src/lib/format";

export default function Home() {
  const nav = useNavigate();
  const { resolved } = useTheme();
  const q = useQuery({ queryKey: ["m-dashboard"], queryFn: () => api.get<Dashboard>("/api/dashboard") });
  const hw = useQuery({ queryKey: ["m-hardware"], queryFn: () => api.get<HardwareList>("/api/hardware") });

  const option = useMemo(() => {
    const s = q.data?.series30;
    if (!s) return null;
    const t = chartTheme();
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis", backgroundColor: t.tooltipBg, textStyle: { color: t.text }, confine: true },
      legend: { data: ["AHI", "Nutzung (h)"], textStyle: { color: t.muted }, top: 0, itemWidth: 14 },
      grid: { left: 30, right: 30, top: 28, bottom: 22 },
      xAxis: { type: "category", data: s.map((x) => dateDe(x.date).slice(0, 6)), axisLabel: { color: t.muted, fontSize: 10 } },
      yAxis: [
        { type: "value", axisLabel: { color: t.muted, fontSize: 10 }, splitLine: { lineStyle: { color: t.grid } } },
        { type: "value", axisLabel: { color: t.muted, fontSize: 10 }, splitLine: { show: false } },
      ],
      dataZoom: [pinchZoom({ start: s.length > 14 ? 50 : 0, end: 100 })],
      series: [
        { name: "Nutzung (h)", type: "bar", yAxisIndex: 1, data: s.map((x) => (x.usage_h == null ? null : +x.usage_h.toFixed(2))), itemStyle: { color: PALETTE.usage, opacity: 0.35 } },
        {
          name: "AHI",
          type: "line",
          data: s.map((x) => (x.ahi == null ? null : +x.ahi.toFixed(2))),
          itemStyle: { color: PALETTE.ahi },
          symbolSize: 6,
          markLine: q.data?.thresholds
            ? { silent: true, symbol: "none", lineStyle: { color: "#dc2626", type: "dashed" }, data: [{ yAxis: q.data.thresholds.ahi_yellow }], label: { show: false } }
            : undefined,
        },
      ],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q.data, resolved]);

  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorMsg error={q.error} />;
  const d = q.data!;
  if (d.empty) return <Section title="Noch keine Daten"><p>Bitte zuerst SD-Karten-Daten über die Weboberfläche importieren.</p><Disclaimer /></Section>;
  const ln = d.last_night!;
  const m = ln.all_metrics;
  const hints = (hw.data?.items || []).filter((i) => i.active && i.due && i.due.status !== "ok");

  return (
    <div className="m-stack">
      {d.short_summary && <div className="m-summary">{d.short_summary}</div>}
      <Section
        title={
          <span className="m-row">
            <Dot status={ln.status} /> {weekday(ln.date)} {dateDe(ln.date)}
          </span>
        }
        right={<button className="m-btn small" onClick={() => nav(`/night/${ln.id}`)}>Details ›</button>}
      >
        <div className="m-grid2">
          <Tile big label="Nutzung" value={hm(ln.usage_h)} sub={`${ln.session_count} Sitzung(en)`} />
          <Tile big label="AHI" value={num(m.ahi, 1)} sub="Ereignisse/h" />
        </div>
        <div className="m-grid3">
          <Tile label="CAI" value={num(m.cai, 1)} />
          <Tile label="OAI" value={num(m.oai, 1)} />
          <Tile label="HI" value={num(m.hi, 1)} />
          <Tile label="Leck 95 %" value={num(m["leak.p95"], 1)} sub="L/min" />
          <Tile label="Druck 95 %" value={num(m["pressure.p95"], 1)} sub="cmH2O" />
          {m["flow_limit.p95"] !== undefined ? <Tile label="FL 95 %" value={num(m["flow_limit.p95"], 2)} /> : <Tile label="RERA" value={num(m.rera_index, 1)} />}
          {m["spo2.median"] !== undefined && <Tile label="SpO2" value={`${num(m["spo2.median"], 0)} %`} />}
        </div>
        {ln.anomalies.length > 0 && (
          <div className="alert warn small">
            {ln.anomalies.map((a) => (
              <div key={a.key}>{a.text}</div>
            ))}
          </div>
        )}
      </Section>
      {hints.length > 0 && (
        <div className="alert info small">
          {hints.map((i) => (
            <div key={i.id}>
              {i.category_label} „{i.name}“: {i.due!.status === "due" ? `Intervall seit ${-i.due!.days_left} Tagen erreicht` : `Wechsel in ${i.due!.days_left} Tagen`}
            </div>
          ))}
        </div>
      )}
      <Section title="Durchschnitt">
        <table className="m-table">
          <thead>
            <tr><th /><th>7 Tage</th><th>30 Tage</th></tr>
          </thead>
          <tbody>
            <tr><td>AHI Ø</td><td>{num(d.agg7?.ahi_mean, 2)}</td><td>{num(d.agg30?.ahi_mean, 2)}</td></tr>
            <tr><td>Nutzung Ø</td><td>{hm(d.agg7?.usage_mean)}</td><td>{hm(d.agg30?.usage_mean)}</td></tr>
            <tr><td>Leck 95 % Ø</td><td>{num(d.agg7?.leak_p95_mean, 1)}</td><td>{num(d.agg30?.leak_p95_mean, 1)}</td></tr>
            <tr><td>Tage ≥ 4 h</td><td>{num(d.agg7?.compliance_pct, 0)} %</td><td>{num(d.agg30?.compliance_pct, 0)} %</td></tr>
          </tbody>
        </table>
      </Section>
      {option && (
        <Section title="AHI & Nutzung (30 Tage)">
          <MChart
            option={option}
            height={230}
            onEvents={{ click: (p: { dataIndex: number }) => { const s = d.series30?.[p.dataIndex]; if (s) nav(`/night/${s.id}`); } }}
          />
          <p className="m-hint">Mit zwei Fingern zoomen · Balken antippen öffnet die Nacht</p>
        </Section>
      )}
      <Section title="Letzte Nächte">
        <div className="m-list">
          {(d.recent || []).slice(0, 7).map((r) => (
            <button key={r.id} className="m-list-item" onClick={() => nav(`/night/${r.id}`)}>
              <Dot status={r.status} />
              <span className="grow">{weekday(r.date)} {dateDe(r.date)}</span>
              <span className="muted">{hm(r.usage_h)}</span>
              <strong>AHI {num(r.metrics.ahi, 1)}</strong>
            </button>
          ))}
        </div>
      </Section>
      <Disclaimer />
    </div>
  );
}
