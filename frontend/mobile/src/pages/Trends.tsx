import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { PeriodSummary, TrendSeries } from "../../../src/api/types";
import { Chips, Disclaimer, ErrorMsg, Section, Spinner } from "../components/ui";
import MChart, { pinchZoom } from "../components/MChart";
import { chartTheme, colorFor } from "../../../src/lib/echarts";
import { dateDe, fmtMetric, hm, num } from "../../../src/lib/format";
import { useTheme } from "../../../src/hooks/useTheme";

type P = "7" | "30" | "90" | "180" | "365";
const METRICS = ["ahi", "usage_h", "leak.p95", "pressure.p95", "cai", "oai", "hi", "flow_limit.p95", "resp_rate.median", "spo2.median"];
const LABELS: Record<string, string> = {
  ahi: "AHI", usage_h: "Nutzung", "leak.p95": "Leck 95 %", "pressure.p95": "Druck 95 %", cai: "CAI", oai: "OAI", hi: "HI",
  "flow_limit.p95": "FL 95 %", "resp_rate.median": "Atemfrequenz", "spo2.median": "SpO2",
};

function TrendChart({ s, markers, onOpen }: { s: TrendSeries; markers: { date: string; kind: string; name: string }[]; onOpen: (id: number) => void }) {
  const { resolved } = useTheme();
  const option = useMemo(() => {
    const t = chartTheme();
    const color = colorFor(s.key === "usage_h" ? "usage" : s.key.split(".")[0]);
    const bar = s.key === "usage_h";
    const idx = markers.filter((m) => m.kind === "start" && s.x.includes(m.date)).map((m) => ({ xAxis: s.x.indexOf(m.date), name: m.name }));
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis", confine: true, backgroundColor: t.tooltipBg, textStyle: { color: t.text }, valueFormatter: (v: number) => (v == null ? "–" : fmtMetric(v, s.unit, s.decimals)) },
      grid: { left: 36, right: 10, top: 10, bottom: 22 },
      xAxis: { type: "category", data: s.x.map((x) => (x.length === 10 ? dateDe(x).slice(0, 6) : x)), axisLabel: { color: t.muted, fontSize: 9 } },
      yAxis: { type: "value", scale: !bar, axisLabel: { color: t.muted, fontSize: 9 }, splitLine: { lineStyle: { color: t.grid } } },
      dataZoom: [pinchZoom({}), pinchZoom({ axis: "y", id: "y", disabled: true })],
      series: [
        {
          name: s.label, type: bar ? "bar" : "line", data: s.y, showSymbol: s.x.length < 60, symbolSize: 4, itemStyle: { color, opacity: bar ? 0.75 : 1 },
          markLine: idx.length ? { symbol: "none", silent: true, lineStyle: { color: "#9333ea", type: "dashed" }, label: { show: false }, data: idx } : undefined,
        },
        ...(s.rolling7 ? [{ name: "Ø 7 Tage", type: "line", data: s.rolling7, showSymbol: false, lineStyle: { color: t.text, opacity: 0.55, width: 2 }, itemStyle: { color: t.text } }] : []),
      ],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s, markers, resolved]);
  return <MChart option={option} height={190} onEvents={{ click: (p: { dataIndex: number }) => { const id = s.night_ids?.[p.dataIndex]; if (id) onOpen(id); } }} />;
}

export default function Trends() {
  const nav = useNavigate();
  const [p, setP] = useState<P>("30");
  const [sel, setSel] = useState<string[]>(["ahi", "usage_h", "leak.p95", "pressure.p95"]);
  const bucket = p === "365" ? "week" : "day";
  const sq = useQuery({ queryKey: ["m-sum", p], queryFn: () => api.get<PeriodSummary>("/api/statistics/summary", { preset: p }) });
  const tq = useQuery({ queryKey: ["m-trends", p, sel.join(","), bucket], queryFn: () => api.get<{ series: Record<string, TrendSeries> }>("/api/statistics/trends", { preset: p, metrics: sel.join(","), bucket }), enabled: sel.length > 0 });
  const mk = useQuery({ queryKey: ["m-hw-tl"], queryFn: () => api.get<{ date: string; kind: string; name: string }[]>("/api/hardware/timeline") });
  const s = sq.data;
  return (
    <div className="m-stack">
      <Chips<P> value={p} onChange={setP} options={[["7", "7 T"], ["30", "30 T"], ["90", "90 T"], ["180", "6 M"], ["365", "1 J"]]} />
      <ErrorMsg error={sq.error || tq.error} />
      {s && (
        <Section title={`${dateDe(s.from)} – ${dateDe(s.to)}`}>
          <table className="m-table">
            <thead><tr><th /><th>Ø</th><th>Median</th><th>Min</th><th>Max</th></tr></thead>
            <tbody>
              {["usage_h", "ahi", "leak.p95", "pressure.p95"].filter((k) => s.stats[k]).map((k) => {
                const x = s.stats[k];
                const f = (v: number) => (k === "usage_h" ? hm(v) : num(v, x.decimals > 1 ? 2 : 1));
                return <tr key={k}><td>{LABELS[k]}</td><td>{f(x.mean)}</td><td>{f(x.median)}</td><td>{f(x.min)}</td><td>{f(x.max)}</td></tr>;
              })}
            </tbody>
          </table>
          <p className="muted small">
            {s.compliance.nights_with_data}/{s.compliance.days} Nächte mit Daten · {num(s.compliance.pct_ge_4h, 0)} % mit ≥ 4 h
            {Object.values(s.trends).filter((t) => t.direction !== "stabil").map((t) => ` · ${t.label} ${t.direction}`).join("")}
          </p>
        </Section>
      )}
      <div className="m-chips wrap">
        {METRICS.map((k) => (
          <button key={k} className={sel.includes(k) ? "active" : ""} onClick={() => setSel(sel.includes(k) ? sel.filter((x) => x !== k) : [...sel, k])}>{LABELS[k]}</button>
        ))}
      </div>
      {tq.isLoading && <Spinner />}
      {sel.map((k) => {
        const ser = tq.data?.series[k];
        if (!ser) return null;
        return (
          <Section key={k} title={ser.label}>
            {ser.y.some((v) => v != null) ? <TrendChart s={ser} markers={mk.data || []} onOpen={(id) => nav(`/night/${id}`)} /> : <p className="muted">Keine Daten verfügbar.</p>}
          </Section>
        );
      })}
      <p className="m-hint">Zwei Finger zum Zoomen · Punkt antippen öffnet die Nacht · lila Linie = neue Hardware</p>
      <Disclaimer />
    </div>
  );
}
