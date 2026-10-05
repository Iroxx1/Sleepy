import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ECharts } from "echarts/core";
import { api } from "../api";
import type { ChannelInfo, EventType, NightEvent, SeriesData, TimeseriesResponse } from "../../../src/api/types";
import { chartTheme, colorFor, echarts } from "../../../src/lib/echarts";
import { clock, num } from "../../../src/lib/format";
import { useTheme } from "../../../src/hooks/useTheme";
import MChart, { pinchZoom } from "./MChart";

const GRID_L = 44;
const GRID_R = 10;
const AHI = ["OA", "CA", "UA", "H", "RERA"];

interface Panel {
  id: string;
  title: string;
  channels: string[];
  height: number;
  yMin?: number;
  dec: number;
  zero?: boolean;
}

const PANELS: Panel[] = [
  { id: "flow", title: "Flow (L/min)", channels: ["flow"], height: 170, dec: 1, zero: true },
  { id: "pressure", title: "Druck (cmH2O)", channels: ["pressure", "ipap", "epap"], height: 130, dec: 1 },
  { id: "leak", title: "Leckage (L/min)", channels: ["leak"], height: 110, yMin: 0, dec: 1 },
  { id: "flow_limit", title: "Flusslimitierung", channels: ["flow_limit"], height: 95, yMin: 0, dec: 2 },
  { id: "resp_rate", title: "Atemfrequenz (/min)", channels: ["resp_rate"], height: 95, dec: 1 },
  { id: "tidal_volume", title: "Atemzugvolumen (mL)", channels: ["tidal_volume"], height: 95, dec: 0 },
  { id: "minute_vent", title: "Minutenvolumen (L/min)", channels: ["minute_vent"], height: 95, dec: 1 },
  { id: "snore", title: "Schnarchen", channels: ["snore"], height: 85, yMin: 0, dec: 2 },
  { id: "mask_pressure", title: "Maskendruck (cmH2O)", channels: ["mask_pressure"], height: 95, dec: 1 },
  { id: "spo2", title: "SpO2 (%)", channels: ["spo2"], height: 100, dec: 0 },
  { id: "pulse", title: "Puls (/min)", channels: ["pulse"], height: 95, dec: 0 },
];
const DEFAULT_HIDDEN = ["snore", "mask_pressure", "tidal_volume"];
const PREF_KEY = "sleepy-m-hidden-panels";

interface Props {
  nightId: number;
  channels: ChannelInfo[];
  events: NightEvent[];
  types: Record<string, EventType>;
  startMs: number;
  endMs: number;
  leakThreshold: number;
  focus: { start: number; end: number; key: number } | null;
}

function merge(base: SeriesData | undefined, detail: SeriesData | undefined, a: number, b: number): (number | null)[][] {
  const out: (number | null)[][] = [];
  if (base) for (let i = 0; i < base.t.length; i++) if (base.t[i] < a) out.push([base.t[i], base.v[i]]);
  if (detail) for (let i = 0; i < detail.t.length; i++) out.push([detail.t[i], detail.v[i]]);
  if (base) for (let i = 0; i < base.t.length; i++) if (base.t[i] > b) out.push([base.t[i], base.v[i]]);
  if (!detail) return base ? base.t.map((t, i) => [t, base.v[i]]) : [];
  return out;
}

export default function NightCharts({ nightId, channels, events, types, startMs, endMs, leakThreshold, focus }: Props) {
  const { resolved } = useTheme();
  const full = useMemo<[number, number]>(() => [startMs - 60_000, endMs + 60_000], [startMs, endMs]);
  const [view, setView] = useState<[number, number]>(full);
  const [pan, setPan] = useState(false);
  const [yZoom, setYZoom] = useState(false);
  const [highlight, setHighlight] = useState<{ start: number; end: number } | null>(null);
  const [hidden, setHidden] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(PREF_KEY) || "null") ?? DEFAULT_HIDDEN;
    } catch {
      return DEFAULT_HIDDEN;
    }
  });
  const charts = useRef<Map<string, ECharts>>(new Map());
  const wrap = useRef<HTMLDivElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const group = `m-night-${nightId}`;
  const width = typeof window !== "undefined" ? window.innerWidth : 400;

  const available = useMemo(() => new Map(channels.map((c) => [c.code, c])), [channels]);
  const panels = useMemo(
    () => PANELS.map((p) => ({ ...p, channels: p.channels.filter((c) => available.has(c)) })).filter((p) => p.channels.length),
    [available],
  );
  const shown = panels.filter((p) => !hidden.includes(p.id));
  const wanted = [...new Set(shown.flatMap((p) => p.channels))].sort().join(",");

  useEffect(() => {
    try {
      localStorage.setItem(PREF_KEY, JSON.stringify(hidden));
    } catch {
      /* ignore */
    }
  }, [hidden]);

  // ---------------------------------------------------------------- data
  const base = useQuery({
    queryKey: ["m-ts-base", nightId, wanted],
    queryFn: () => api.get<TimeseriesResponse>(`/api/nights/${nightId}/timeseries`, { channels: wanted, points: Math.min(1600, width * 2) }),
    enabled: !!wanted,
    staleTime: Infinity,
  });
  const span = view[1] - view[0];
  const zoomed = span < (full[1] - full[0]) * 0.6;
  const da = Math.max(full[0], view[0] - span * 0.5);
  const db = Math.min(full[1], view[1] + span * 0.5);
  const detail = useQuery({
    queryKey: ["m-ts-detail", nightId, wanted, Math.round(da / 2000), Math.round(db / 2000)],
    queryFn: () =>
      api.get<TimeseriesResponse>(`/api/nights/${nightId}/timeseries`, {
        channels: wanted,
        start: Math.round(da),
        end: Math.round(db),
        points: Math.min(5000, Math.round(width * 3 * ((db - da) / Math.max(span, 1)))),
      }),
    enabled: !!wanted && zoomed,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  });

  // ---------------------------------------------------------- zoom state
  const readWindow = useCallback((c: ECharts) => {
    const w = c.getWidth();
    const a = c.convertFromPixel({ xAxisIndex: 0 }, GRID_L) as unknown as number;
    const b = c.convertFromPixel({ xAxisIndex: 0 }, w - GRID_R) as unknown as number;
    if (Number.isFinite(a) && Number.isFinite(b) && b > a) {
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setView([a, b]), 250);
    }
  }, []);

  const zoomTo = useCallback(
    (a: number, b: number) => {
      const s = Math.max(10_000, b - a);
      let x = Math.max(full[0], a);
      if (x + s > full[1]) x = Math.max(full[0], full[1] - s);
      for (const c of charts.current.values()) {
        c.dispatchAction({ type: "dataZoom", dataZoomId: "dzx", startValue: x, endValue: x + s });
      }
      setView([x, x + s]);
    },
    [full],
  );

  useEffect(() => {
    if (focus) {
      const pad = Math.max(60_000, (focus.end - focus.start) * 1.5);
      setHighlight({ start: focus.start, end: focus.end });
      zoomTo(focus.start - pad, focus.end + pad);
      wrap.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [focus, zoomTo]);

  // ------------------------------------------------------------- options
  const theme = useMemo(() => chartTheme(), [resolved]);
  const xAxis = useCallback(
    (last: boolean) => ({
      type: "time",
      min: full[0],
      max: full[1],
      axisLabel: { show: last, color: theme.muted, fontSize: 10, formatter: (v: number) => clock(v), hideOverlap: true },
      axisTick: { show: last },
      axisLine: { lineStyle: { color: theme.axis } },
      splitLine: { show: true, lineStyle: { color: theme.grid } },
      axisPointer: { show: true, label: { show: false } },
    }),
    [full, theme],
  );
  const highlightArea = highlight
    ? [[{ xAxis: highlight.start }, { xAxis: Math.max(highlight.end, highlight.start + 1000) }]]
    : [];

  const panelOption = (p: Panel, last: boolean) => {
    const series = p.channels.map((c, i) => {
      const d = merge(base.data?.channels[c], zoomed ? detail.data?.channels[c] : undefined, da, db);
      const s: Record<string, unknown> = {
        id: c,
        name: available.get(c)?.name ?? c,
        type: "line",
        data: d,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: c === "flow" ? 1 : 1.4 },
        itemStyle: { color: colorFor(c, i) },
        animation: false,
        emphasis: { disabled: true },
      };
      if (i === 0) {
        const lines: object[] = [];
        if (p.id === "leak") lines.push({ yAxis: leakThreshold, lineStyle: { color: "#dc2626", type: "dashed" }, label: { show: false } });
        if (p.zero) lines.push({ yAxis: 0, lineStyle: { color: theme.muted, opacity: 0.4, type: "solid" }, label: { show: false } });
        const areas: object[] = [...highlightArea];
        if (p.id === "flow") {
          for (const e of events.filter((x) => AHI.includes(x.code)).slice(0, 300)) {
            const col = types[e.code]?.color ?? "#64748b";
            lines.push({ xAxis: e.end_ms, lineStyle: { color: col, width: 1.2, type: "solid" }, label: { formatter: types[e.code]?.short ?? e.code, color: col, fontSize: 9, position: "end" } });
            if (e.end_ms > e.start_ms) areas.push([{ xAxis: e.start_ms, itemStyle: { color: col, opacity: 0.12 } }, { xAxis: e.end_ms }]);
          }
        }
        s.markLine = { silent: true, symbol: "none", animation: false, data: lines };
        s.markArea = { silent: true, itemStyle: { color: "rgba(37,99,235,0.15)" }, data: areas };
      }
      return s;
    });
    return {
      backgroundColor: "transparent",
      animation: false,
      grid: { left: GRID_L, right: GRID_R, top: p.id === "flow" ? 30 : 18, bottom: last ? 22 : 4 },
      xAxis: xAxis(last),
      yAxis: {
        type: "value",
        scale: p.yMin === undefined,
        min: p.yMin,
        max: p.id === "spo2" ? 100 : undefined,
        splitNumber: 3,
        axisLabel: { color: theme.muted, fontSize: 9, formatter: (v: number) => v.toLocaleString("de-DE", { maximumFractionDigits: 2 }) },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: theme.tooltipBg,
        textStyle: { color: theme.text, fontSize: 11 },
        formatter: (ps: { axisValue: number; seriesName: string; value: [number, number | null]; color: string }[]) => {
          if (!ps.length) return "";
          let s = `<b>${clock(ps[0].axisValue, true)}</b>`;
          for (const x of ps) if (x.value?.[1] != null) s += `<br/>${x.seriesName}: <b>${num(x.value[1], p.dec)}</b>`;
          return s;
        },
      },
      dataZoom: [
        pinchZoom({ id: "dzx", pan, disabled: yZoom }),
        pinchZoom({ id: `dzy-${p.id}`, axis: "y", disabled: !yZoom, pan }),
      ],
      series,
    };
  };

  const lanes = useMemo(() => {
    const order = ["OA", "CA", "UA", "H", "RERA", "CSR", "DESAT", "OTHER"];
    return [...new Set(events.map((e) => e.code))].sort((a, b) => order.indexOf(a) - order.indexOf(b));
  }, [events]);

  const eventsOption = {
    backgroundColor: "transparent",
    animation: false,
    grid: { left: GRID_L, right: GRID_R, top: 16, bottom: 4 },
    xAxis: xAxis(false),
    yAxis: {
      type: "category",
      data: lanes.map((c) => types[c]?.short ?? c),
      inverse: true,
      axisLabel: { color: theme.muted, fontSize: 9, fontWeight: "bold" },
      axisTick: { show: false },
      splitLine: { show: true, lineStyle: { color: theme.grid } },
    },
    tooltip: {
      trigger: "item",
      confine: true,
      backgroundColor: theme.tooltipBg,
      textStyle: { color: theme.text, fontSize: 11 },
      formatter: (p: { data: { ev: NightEvent } }) =>
        `<b>${types[p.data.ev.code]?.name ?? p.data.ev.code}</b><br/>${clock(p.data.ev.start_ms, true)} · ${p.data.ev.duration_s != null ? num(p.data.ev.duration_s, 0) + " s" : "–"}`,
    },
    dataZoom: [pinchZoom({ id: "dzx", pan, disabled: yZoom })],
    series: [
      {
        type: "custom",
        renderItem: (params: { coordSys: { x: number; y: number; width: number; height: number } }, a: { value: (i: number) => number; coord: (v: number[]) => number[]; size: (v: number[]) => number[]; style: () => object }) => {
          const s = a.coord([a.value(1), a.value(0)]);
          const e = a.coord([a.value(2), a.value(0)]);
          const h = Math.max(6, a.size([0, 1])[1] * 0.6);
          const rect = echarts.graphic.clipRectByRect({ x: s[0], y: s[1] - h / 2, width: Math.max(3, e[0] - s[0]), height: h }, params.coordSys);
          return rect ? { type: "rect", shape: rect, style: a.style() } : null;
        },
        encode: { x: [1, 2], y: 0 },
        data: events.map((e) => ({ value: [lanes.indexOf(e.code), e.start_ms, Math.max(e.end_ms, e.start_ms + 1)], itemStyle: { color: types[e.code]?.color ?? "#64748b" }, ev: e })),
      },
    ],
  };

  const overviewOption = useMemo(() => {
    const d = base.data?.channels || {};
    const key = ["pressure", "leak", "flow_limit"].find((c) => d[c]) ?? Object.keys(d)[0];
    const s = key ? d[key] : undefined;
    return {
      backgroundColor: "transparent",
      animation: false,
      grid: { left: GRID_L, right: GRID_R, top: 2, bottom: 2 },
      xAxis: { type: "time", min: full[0], max: full[1], show: false },
      yAxis: { type: "value", show: false, scale: true },
      series: [
        {
          type: "line",
          showSymbol: false,
          data: s ? s.t.map((t, i) => [t, s.v[i]]) : [],
          lineStyle: { width: 1, color: theme.muted },
          markArea: { silent: true, itemStyle: { color: "rgba(37,99,235,0.22)", borderColor: "#2563eb", borderWidth: 1 }, data: [[{ xAxis: view[0] }, { xAxis: view[1] }]] },
        },
      ],
    };
  }, [base.data, full, view, theme]);

  const register = (id: string) => (c: ECharts) => {
    charts.current.set(id, c);
    c.on("datazoom", () => readWindow(c));
  };

  const spanMin = span / 60000;
  return (
    <div ref={wrap}>
      <div className="m-chart-toolbar">
        <button onClick={() => { setHighlight(null); zoomTo(full[0], full[1]); }}>Ganze Nacht</button>
        <button onClick={() => zoomTo(view[0] + span * 0.25, view[1] - span * 0.25)} aria-label="Hineinzoomen">＋</button>
        <button onClick={() => zoomTo(view[0] - span * 0.5, view[1] + span * 0.5)} aria-label="Herauszoomen">－</button>
        <button onClick={() => zoomTo(view[0] - span * 0.5, view[1] - span * 0.5)} aria-label="Zurück">◀</button>
        <button onClick={() => zoomTo(view[0] + span * 0.5, view[1] + span * 0.5)} aria-label="Vor">▶</button>
        <button className={pan ? "active" : ""} onClick={() => setPan(!pan)}>✋ Verschieben</button>
        <button className={yZoom ? "active" : ""} onClick={() => setYZoom(!yZoom)}>↕ Skala</button>
      </div>
      <div className="m-chart-range">
        {clock(view[0])} – {clock(view[1])} · {spanMin >= 60 ? `${num(spanMin / 60, 1)} h` : `${num(spanMin, spanMin < 5 ? 1 : 0)} min`}
        {base.isFetching || detail.isFetching ? " · lädt …" : zoomed && !detail.data?.channels.flow?.downsampled ? " · volle Auflösung" : ""}
      </div>
      <div
        className="m-overview"
        onClick={(e) => {
          const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
          const f = Math.min(1, Math.max(0, (e.clientX - r.left - GRID_L) / (r.width - GRID_L - GRID_R)));
          const t = full[0] + f * (full[1] - full[0]);
          zoomTo(t - span / 2, t + span / 2);
        }}
      >
        <MChart option={overviewOption} height={36} />
      </div>
      {events.length > 0 && (
        <div className="m-panel">
          <span className="m-panel-title">Ereignisse</span>
          <MChart option={eventsOption} height={Math.max(64, 16 * lanes.length + 24)} group={group} onInit={register("events")} notMerge={false} />
        </div>
      )}
      {shown.map((p, i) => (
        <div className="m-panel" key={p.id}>
          <span className="m-panel-title">{p.title}</span>
          <MChart option={panelOption(p, i === shown.length - 1)} height={p.height} group={group} onInit={register(p.id)} notMerge={false} />
        </div>
      ))}
      <p className="m-hint">
        Zwei Finger: zoomen (Zeit; mit „↕ Skala“ die Werte-Achse). Ein Finger: Seite scrollen bzw. mit „✋ Verschieben“ das Zeitfenster bewegen.
        Antippen zeigt Werte. Leiste oben antippen springt an diese Stelle.
      </p>
      <details className="m-details">
        <summary>Kanäle auswählen</summary>
        <div className="m-chips wrap">
          {panels.map((p) => (
            <button key={p.id} className={hidden.includes(p.id) ? "" : "active"} onClick={() => setHidden(hidden.includes(p.id) ? hidden.filter((x) => x !== p.id) : [...hidden, p.id])}>
              {p.title.replace(/ \(.*\)/, "")}
            </button>
          ))}
        </div>
      </details>
    </div>
  );
}
