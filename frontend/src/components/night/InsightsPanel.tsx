import { useMemo } from "react";
import type { EventType, Insights } from "../../api/types";
import EChart from "../EChart";
import { chartTheme, colorFor } from "../../lib/echarts";
import { clock, num } from "../../lib/format";
import { useTheme } from "../../hooks/useTheme";

const PERI_LABEL: Record<string, string> = {
  pressure: "Druck (cmH2O)",
  epap: "EPAP (cmH2O)",
  leak: "Leckage (L/min)",
  flow_limit: "Flusslimitierung",
  snore: "Schnarchen",
  resp_rate: "Atemfrequenz",
  tidal_volume: "Atemzugvolumen (mL)",
  spo2: "SpO2 (%)",
  pulse: "Puls",
};

export function HourlyChart({ ins, types }: { ins: Insights; types: Record<string, EventType> }) {
  const { resolved } = useTheme();
  const option = useMemo(() => {
    const t = chartTheme();
    const codes = [...new Set(ins.hourly.flatMap((h) => Object.keys(h.counts)))];
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis", backgroundColor: t.tooltipBg, textStyle: { color: t.text } },
      legend: { textStyle: { color: t.muted }, top: 0 },
      grid: { left: 36, right: 12, top: 30, bottom: 24 },
      xAxis: { type: "category", data: ins.hourly.map((h) => clock(h.start_ms)), axisLabel: { color: t.muted } },
      yAxis: { type: "value", minInterval: 1, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.grid } } },
      series: codes.map((c) => ({
        name: types[c]?.short ?? c,
        type: "bar",
        stack: "e",
        data: ins.hourly.map((h) => h.counts[c] ?? 0),
        itemStyle: { color: types[c]?.color },
      })),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ins, types, resolved]);
  if (!ins.hourly.length) return null;
  return <EChart option={option} height={200} notMerge />;
}

export function PeriEventChart({ ins }: { ins: Insights }) {
  const { resolved } = useTheme();
  const entries = Object.entries(ins.peri_event);
  const option = useMemo(() => {
    const t = chartTheme();
    const n = entries.length;
    const grids = entries.map((_, i) => ({ left: 48, right: 12, top: 26 + i * 92, height: 62 }));
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis", backgroundColor: t.tooltipBg, textStyle: { color: t.text } },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      title: entries.map(([c, d], i) => ({
        text: `${PERI_LABEL[c] ?? c} · Nachtmedian ${num(d.night_median, c === "flow_limit" ? 2 : 1)}`,
        top: 8 + i * 92,
        left: 48,
        textStyle: { fontSize: 11, color: t.muted, fontWeight: "normal" },
      })),
      grid: grids,
      xAxis: entries.map((_, i) => ({
        type: "value",
        gridIndex: i,
        min: -180,
        max: 180,
        axisLabel: { show: i === n - 1, color: t.muted, formatter: (v: number) => `${v} s` },
        splitLine: { lineStyle: { color: t.grid } },
      })),
      yAxis: entries.map((_, i) => ({
        type: "value",
        gridIndex: i,
        scale: true,
        splitNumber: 2,
        axisLabel: { color: t.muted, fontSize: 10 },
        splitLine: { lineStyle: { color: t.grid } },
      })),
      series: entries.map(([c, d], i) => ({
        name: PERI_LABEL[c] ?? c,
        type: "line",
        xAxisIndex: i,
        yAxisIndex: i,
        showSymbol: false,
        data: d.offsets_s.map((o, k) => [o, d.mean[k]]),
        itemStyle: { color: colorFor(c, i) },
        markLine: { silent: true, symbol: "none", data: [{ xAxis: 0 }], lineStyle: { color: "#dc2626", type: "dashed" }, label: { show: false } },
      })),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ins, resolved]);
  if (!entries.length) return <p className="muted small">Zu wenige Ereignisse für eine ereignisbezogene Mittelung (mindestens 3).</p>;
  return (
    <>
      <EChart option={option} height={40 + entries.length * 92} notMerge />
      <p className="muted small">
        Mittelwert der Kanäle über alle Apnoen/Hypopnoen ({entries[0][1].n_events} Ereignisse), ausgerichtet am Ereignisbeginn (0 s).
        Rein statistische Darstellung.
      </p>
    </>
  );
}
