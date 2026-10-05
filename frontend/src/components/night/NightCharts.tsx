import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ECharts } from "echarts/core";
import { api } from "../../api/client";
import type { ChannelInfo, EventType, NightEvent, SeriesData, TimeseriesResponse } from "../../api/types";
import EChart from "../EChart";
import { chartTheme, colorFor, echarts } from "../../lib/echarts";
import { clock, num } from "../../lib/format";
import { useTheme } from "../../hooks/useTheme";

const GRID_LEFT = 58;
const GRID_RIGHT = 18;
const MIN_SPAN = 8_000;
const AHI_CODES = ["OA", "CA", "UA", "H", "RERA"];

interface PanelDef {
  id: string;
  title: string;
  channels: string[];
  optional?: string[];
  height: number;
  yMin?: number;
  yMax?: number;
  zeroLine?: boolean;
  decimals: number;
}

const BASE_PANELS: PanelDef[] = [
  { id: "flow", title: "Flow (L/min)", channels: ["flow"], height: 190, zeroLine: true, decimals: 1 },
  { id: "pressure", title: "Druck (cmH2O)", channels: ["pressure", "ipap", "epap", "mask_pressure"], optional: ["mask_pressure_hi"], height: 150, decimals: 1 },
  { id: "leak", title: "Leckage (L/min)", channels: ["leak"], height: 120, yMin: 0, decimals: 1 },
  { id: "flow_limit", title: "Flusslimitierung", channels: ["flow_limit"], height: 100, yMin: 0, decimals: 2 },
  { id: "snore", title: "Schnarchen", channels: ["snore"], height: 90, yMin: 0, decimals: 2 },
  { id: "resp_rate", title: "Atemfrequenz (/min)", channels: ["resp_rate"], height: 100, decimals: 1 },
  { id: "tidal_volume", title: "Atemzugvolumen (mL)", channels: ["tidal_volume"], height: 100, decimals: 0 },
  { id: "minute_vent", title: "Atemminutenvolumen (L/min)", channels: ["minute_vent", "target_vent"], height: 100, decimals: 1 },
  { id: "ti_te", title: "Inspirations-/Exspirationszeit (s)", channels: ["ti", "te"], height: 90, decimals: 2 },
  { id: "ie_ratio", title: "I:E (Rohwert)", channels: ["ie_ratio"], height: 90, decimals: 2 },
  { id: "spo2", title: "SpO2 (%)", channels: ["spo2"], height: 110, decimals: 0 },
  { id: "pulse", title: "Puls (/min)", channels: ["pulse"], height: 100, decimals: 0 },
];

const HIDDEN_BY_DEFAULT = new Set(["ti_te", "ie_ratio"]);

interface Props {
  nightId: number;
  channels: ChannelInfo[];
  events: NightEvent[];
  eventTypes: Record<string, EventType>;
  startMs: number;
  endMs: number;
  leakThreshold: number;
  focus: { start: number; end: number; key: number } | null;
  onRangeChange?: (r: [number, number]) => void;
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function loadPrefs(): { hidden: string[]; extras: string[] } {
  try {
    return JSON.parse(localStorage.getItem("sleepy-night-panels") || "") as { hidden: string[]; extras: string[] };
  } catch {
    return { hidden: [...HIDDEN_BY_DEFAULT], extras: [] };
  }
}

export default function NightCharts({ nightId, channels, events, eventTypes, startMs, endMs, leakThreshold, focus, onRangeChange }: Props) {
  const { resolved } = useTheme();
  const full: [number, number] = useMemo(() => [startMs - 60_000, endMs + 60_000], [startMs, endMs]);
  const [range, setRange] = useState<[number, number]>(full);
  const [mode, setMode] = useState<"select" | "pan">("select");
  const [highlight, setHighlight] = useState<{ start: number; end: number } | null>(null);
  const [prefs, setPrefs] = useState(loadPrefs);
  const [showFlags, setShowFlags] = useState(true);
  const stackRef = useRef<HTMLDivElement>(null);
  const charts = useRef<Map<string, ECharts>>(new Map());
  const [width, setWidth] = useState(1200);
  const group = `night-${nightId}`;

  useEffect(() => setRange(full), [full]);
  useEffect(() => onRangeChange?.(range), [range, onRangeChange]);
  useEffect(() => {
    if (focus) {
      const pad = Math.max(60_000, (focus.end - focus.start) * 1.5);
      setRange([focus.start - pad, focus.end + pad]);
      setHighlight({ start: focus.start, end: focus.end });
      stackRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [focus]);
  useEffect(() => {
    try {
      localStorage.setItem("sleepy-night-panels", JSON.stringify(prefs));
    } catch {
      /* ignore */
    }
  }, [prefs]);

  // ------------------------------------------------------------ panels
  const available = useMemo(() => new Map(channels.map((c) => [c.code, c])), [channels]);
  const panels = useMemo(() => {
    const out: PanelDef[] = [];
    const used = new Set<string>();
    for (const p of BASE_PANELS) {
      const chs = p.channels.filter((c) => available.has(c));
      const opt = (p.optional || []).filter((c) => available.has(c));
      [...chs, ...opt].forEach((c) => used.add(c));
      if (chs.length || opt.length) out.push({ ...p, channels: chs, optional: opt });
    }
    // any other channel (unknown / manufacturer specific) gets its own panel
    for (const c of channels) {
      if (used.has(c.code) || c.code === "trig_cycle_event") continue;
      out.push({ id: `x:${c.code}`, title: `${c.name}${c.unit ? ` (${c.unit})` : ""}`, channels: [c.code], height: 90, decimals: 2 });
    }
    return out;
  }, [available, channels]);

  const visiblePanels = useMemo(
    () => panels.filter((p) => !prefs.hidden.includes(p.id) && !(p.id.startsWith("x:") && !prefs.extras.includes(p.id))),
    [panels, prefs],
  );
  const wantedChannels = useMemo(() => {
    const s = new Set<string>();
    for (const p of visiblePanels) {
      p.channels.forEach((c) => s.add(c));
      (p.optional || []).forEach((c) => prefs.extras.includes(c) && s.add(c));
    }
    return [...s].sort();
  }, [visiblePanels, prefs.extras]);

  useEffect(() => {
    const el = stackRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  // ------------------------------------------------------------ data
  const dRange = useDebounced(range, 180);
  const points = Math.min(6000, Math.max(400, Math.round(width * 1.6)));
  const q = useQuery({
    queryKey: ["ts", nightId, wantedChannels.join(","), Math.round(dRange[0] / 1000), Math.round(dRange[1] / 1000), points],
    queryFn: () =>
      api.get<TimeseriesResponse>(`/api/nights/${nightId}/timeseries`, {
        channels: wantedChannels.join(","),
        start: Math.round(dRange[0]),
        end: Math.round(dRange[1]),
        points,
      }),
    enabled: wantedChannels.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  });
  const overview = useQuery({
    queryKey: ["ts-overview", nightId],
    queryFn: () =>
      api.get<TimeseriesResponse>(`/api/nights/${nightId}/timeseries`, {
        channels: ["pressure", "leak", "mask_pressure"].filter((c) => available.has(c)).join(",") || channels[0]?.code,
        points: 900,
      }),
    enabled: channels.length > 0,
    staleTime: Infinity,
  });

  // ------------------------------------------------------------ interaction
  const timeAt = useCallback(
    (clientX: number) => {
      const el = stackRef.current!;
      const rect = el.getBoundingClientRect();
      const w = rect.width - GRID_LEFT - GRID_RIGHT;
      const f = Math.min(1, Math.max(0, (clientX - rect.left - GRID_LEFT) / w));
      return range[0] + f * (range[1] - range[0]);
    },
    [range],
  );

  const clamp = useCallback(
    (a: number, b: number): [number, number] => {
      let span = Math.max(MIN_SPAN, b - a);
      const fullSpan = full[1] - full[0];
      if (span > fullSpan) span = fullSpan;
      let s = a;
      if (s < full[0]) s = full[0];
      if (s + span > full[1]) s = full[1] - span;
      return [s, s + span];
    },
    [full],
  );

  const zoom = useCallback(
    (factor: number, center?: number) => {
      setRange(([a, b]) => {
        const c = center ?? (a + b) / 2;
        return clamp(c - (c - a) * factor, c + (b - c) * factor);
      });
    },
    [clamp],
  );
  const pan = useCallback(
    (frac: number) => {
      setRange(([a, b]) => clamp(a + (b - a) * frac, b + (b - a) * frac));
    },
    [clamp],
  );

  useEffect(() => {
    const el = stackRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        const d = e.shiftKey ? e.deltaY : e.deltaX;
        pan(d > 0 ? 0.1 : -0.1);
      } else {
        zoom(e.deltaY > 0 ? 1.25 : 0.8, timeAt(e.clientX));
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoom, pan, timeAt]);

  const drag = useRef<{ x: number; t: number; range: [number, number] } | null>(null);
  const [sel, setSel] = useState<{ x0: number; x1: number } | null>(null);
  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    const rect = stackRef.current!.getBoundingClientRect();
    if (e.clientX - rect.left < GRID_LEFT) return;
    drag.current = { x: e.clientX, t: timeAt(e.clientX), range };
    (e.target as Element).setPointerCapture?.(e.pointerId);
    if (mode === "select") setSel({ x0: e.clientX - rect.left, x1: e.clientX - rect.left });
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const rect = stackRef.current!.getBoundingClientRect();
    if (mode === "pan") {
      const w = rect.width - GRID_LEFT - GRID_RIGHT;
      const [a, b] = drag.current.range;
      const dt = ((e.clientX - drag.current.x) / w) * (b - a);
      setRange(clamp(a - dt, b - dt));
    } else {
      setSel((s) => (s ? { ...s, x1: e.clientX - rect.left } : s));
    }
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (!drag.current) return;
    if (mode === "select" && sel) {
      const t0 = drag.current.t;
      const t1 = timeAt(e.clientX);
      if (Math.abs(sel.x1 - sel.x0) > 6) setRange(clamp(Math.min(t0, t1), Math.max(t0, t1)));
    }
    drag.current = null;
    setSel(null);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowLeft") pan(-0.2);
    else if (e.key === "ArrowRight") pan(0.2);
    else if (e.key === "+" || e.key === "=") zoom(0.7);
    else if (e.key === "-") zoom(1.4);
    else if (e.key === "0" || e.key === "Escape") {
      setRange(full);
      setHighlight(null);
    } else return;
    e.preventDefault();
  };

  const setSpan = (ms: number) => {
    const c = (range[0] + range[1]) / 2;
    setRange(clamp(c - ms / 2, c + ms / 2));
  };

  // ------------------------------------------------------------ options
  const theme = useMemo(() => chartTheme(), [resolved]);
  const data = q.data?.channels || {};
  const eventsInView = useMemo(
    () => events.filter((e) => e.end_ms >= range[0] - 60_000 && e.start_ms <= range[1] + 60_000),
    [events, range],
  );

  const baseAxis = useCallback(
    (isLast: boolean) => ({
      type: "time" as const,
      min: range[0],
      max: range[1],
      axisLabel: { show: isLast, color: theme.muted, formatter: (v: number) => clock(v, range[1] - range[0] < 15 * 60_000), hideOverlap: true },
      axisTick: { show: isLast },
      axisLine: { lineStyle: { color: theme.axis } },
      splitLine: { show: true, lineStyle: { color: theme.grid } },
      axisPointer: { show: true, snap: false, label: { show: isLast, formatter: (p: { value: number }) => clock(p.value, true) } },
    }),
    [range, theme],
  );

  const highlightArea = useMemo(
    () =>
      highlight
        ? {
            silent: true,
            itemStyle: { color: "rgba(37,99,235,0.14)" },
            data: [[{ xAxis: highlight.start }, { xAxis: Math.max(highlight.end, highlight.start + 1000) }]],
          }
        : undefined,
    [highlight],
  );

  const tooltip = useCallback(
    (decimals: Record<string, number>, units: Record<string, string>) => ({
      trigger: "axis" as const,
      backgroundColor: theme.tooltipBg,
      borderColor: theme.axis,
      textStyle: { color: theme.text, fontSize: 12 },
      axisPointer: { type: "line" as const, lineStyle: { color: theme.muted, type: "dashed" as const } },
      formatter: (params: { axisValue: number; seriesName: string; value: [number, number | null]; color: string; seriesId: string }[]) => {
        if (!params.length) return "";
        let s = `<b>${clock(params[0].axisValue, true)}</b>`;
        for (const p of params) {
          if (p.value?.[1] === null || p.value?.[1] === undefined) continue;
          s += `<br/><span style="display:inline-block;width:8px;height:8px;border-radius:4px;background:${p.color};margin-right:4px"></span>${p.seriesName}: <b>${num(p.value[1], decimals[p.seriesId] ?? 2)}</b> ${units[p.seriesId] ?? ""}`;
        }
        return s;
      },
    }),
    [theme],
  );

  const panelOption = useCallback(
    (p: PanelDef, isLast: boolean) => {
      const chs = [...p.channels, ...(p.optional || []).filter((c) => prefs.extras.includes(c))];
      const decimals: Record<string, number> = {};
      const units: Record<string, string> = {};
      const series: object[] = chs.map((c, i) => {
        const d: SeriesData | undefined = data[c];
        decimals[c] = p.decimals;
        units[c] = available.get(c)?.unit ?? "";
        const pts = d ? d.t.map((t, k) => [t, d.v[k]]) : [];
        return {
          id: c,
          name: available.get(c)?.name ?? c,
          type: "line",
          data: pts,
          showSymbol: false,
          connectNulls: false,
          sampling: undefined,
          lineStyle: { width: c === "flow" ? 1 : 1.4, opacity: c === "mask_pressure_hi" ? 0.6 : 1 },
          itemStyle: { color: colorFor(c, i) },
          step: ["pressure", "epap", "ipap"].includes(c) && (d?.rate ?? 1) <= 1 ? "end" : undefined,
          emphasis: { disabled: true },
          animation: false,
          z: c === "mask_pressure_hi" ? 1 : 2,
        };
      });
      const s0 = series[0] as Record<string, unknown> | undefined;
      if (s0) {
        const markLines: object[] = [];
        if (p.id === "leak") markLines.push({ yAxis: leakThreshold, lineStyle: { color: "#dc2626", type: "dashed" }, label: { formatter: `${leakThreshold} L/min`, color: theme.muted, position: "insideEndTop" } });
        if (p.zeroLine) markLines.push({ yAxis: 0, lineStyle: { color: theme.muted, type: "solid", opacity: 0.4 }, label: { show: false } });
        const flagAreas: object[] = [];
        if (p.id === "flow" && showFlags) {
          const flagged = eventsInView.filter((e) => AHI_CODES.includes(e.code) || e.code === "CSR").slice(0, 400);
          for (const e of flagged) {
            const color = eventTypes[e.code]?.color ?? "#64748b";
            if (e.code !== "CSR") {
              markLines.push({
                xAxis: e.end_ms,
                lineStyle: { color, type: "solid", width: 1.5 },
                label: { formatter: eventTypes[e.code]?.short ?? e.code, color, position: "end", fontWeight: "bold", fontSize: 10 },
              });
            }
            if (e.end_ms > e.start_ms) flagAreas.push([{ xAxis: e.start_ms, itemStyle: { color, opacity: 0.1 } }, { xAxis: e.end_ms }]);
          }
        }
        s0.markLine = markLines.length ? { silent: true, symbol: "none", animation: false, data: markLines } : undefined;
        const areas = [...flagAreas, ...(highlightArea?.data ?? [])];
        s0.markArea = areas.length ? { silent: true, itemStyle: { color: "rgba(37,99,235,0.14)" }, data: areas } : undefined;
      }
      const ch0 = available.get(p.channels[0] ?? "");
      return {
        backgroundColor: "transparent",
        animation: false,
        grid: { left: GRID_LEFT, right: GRID_RIGHT, top: 24, bottom: isLast ? 26 : 6 },
        xAxis: baseAxis(isLast),
        yAxis: {
          type: "value",
          scale: p.yMin === undefined,
          min: p.yMin ?? (p.id === "spo2" ? (v: { min: number }) => Math.max(70, Math.floor(v.min - 2)) : undefined),
          max: p.yMax ?? (p.id === "spo2" ? 100 : undefined),
          splitNumber: 3,
          axisLabel: { color: theme.muted, fontSize: 10, formatter: (v: number) => v.toLocaleString("de-DE", { maximumFractionDigits: 3 }) },
          splitLine: { lineStyle: { color: theme.grid } },
        },
        tooltip: tooltip(decimals, units),
        legend: { show: false },
        series,
        aria: { enabled: true, label: { description: `${p.title}${ch0 ? "" : ""}` } },
      };
    },
    [data, available, prefs.extras, leakThreshold, theme, showFlags, eventsInView, eventTypes, highlightArea, baseAxis, tooltip],
  );

  const lanes = useMemo(() => {
    const codes = [...new Set(events.map((e) => e.code))];
    const order = ["OA", "CA", "UA", "H", "RERA", "CSR", "DESAT", "OTHER"];
    codes.sort((a, b) => (order.indexOf(a) + 100 * +(order.indexOf(a) < 0)) - (order.indexOf(b) + 100 * +(order.indexOf(b) < 0)));
    return codes;
  }, [events]);

  const eventsOption = useMemo(() => {
    const items = eventsInView.map((e) => ({
      value: [lanes.indexOf(e.code), e.start_ms, Math.max(e.end_ms, e.start_ms + 1), e.id],
      itemStyle: { color: eventTypes[e.code]?.color ?? "#64748b" },
      name: e.code,
      ev: e,
    }));
    return {
      backgroundColor: "transparent",
      animation: false,
      grid: { left: GRID_LEFT, right: GRID_RIGHT, top: 8, bottom: 6 },
      xAxis: baseAxis(false),
      yAxis: {
        type: "category",
        data: lanes.map((c) => eventTypes[c]?.short ?? c),
        inverse: true,
        axisLabel: { color: theme.muted, fontSize: 10, fontWeight: "bold" },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: theme.axis } },
        splitLine: { show: true, lineStyle: { color: theme.grid } },
      },
      tooltip: {
        trigger: "item",
        backgroundColor: theme.tooltipBg,
        borderColor: theme.axis,
        textStyle: { color: theme.text, fontSize: 12 },
        formatter: (p: { data: { ev: NightEvent } }) => {
          const e = p.data.ev;
          return `<b>${eventTypes[e.code]?.name ?? e.code}</b><br/>${clock(e.start_ms, true)} – ${clock(e.end_ms, true)}<br/>Dauer: ${
            e.duration_s != null ? num(e.duration_s, 0) + " s" : "–"
          }`;
        },
      },
      series: [
        {
          type: "custom",
          renderItem: (params: { coordSys: { x: number; y: number; width: number; height: number } }, apiR: {
            value: (i: number) => number;
            coord: (v: number[]) => number[];
            size: (v: number[]) => number[];
            style: () => object;
          }) => {
            const lane = apiR.value(0);
            const s = apiR.coord([apiR.value(1), lane]);
            const e = apiR.coord([apiR.value(2), lane]);
            const h = Math.max(6, apiR.size([0, 1])[1] * 0.62);
            const rect = echarts.graphic.clipRectByRect(
              { x: s[0], y: s[1] - h / 2, width: Math.max(3, e[0] - s[0]), height: h },
              { x: params.coordSys.x, y: params.coordSys.y, width: params.coordSys.width, height: params.coordSys.height },
            );
            return rect ? { type: "rect", transition: [], shape: rect, style: apiR.style() } : null;
          },
          encode: { x: [1, 2], y: 0 },
          data: items,
          markArea: highlightArea,
        },
      ],
    };
  }, [eventsInView, lanes, eventTypes, baseAxis, theme, highlightArea]);

  const overviewOption = useMemo(() => {
    const d = overview.data?.channels || {};
    const series: object[] = Object.entries(d).map(([c, s], i) => ({
      name: available.get(c)?.name ?? c,
      type: "line",
      showSymbol: false,
      data: s.t.map((t, k) => [t, s.v[k]]),
      lineStyle: { width: 1 },
      itemStyle: { color: colorFor(c, i) },
      yAxisIndex: c === "leak" ? 1 : 0,
      areaStyle: c === "leak" ? { opacity: 0.15 } : undefined,
    }));
    series.push({
      type: "scatter",
      data: events.filter((e) => AHI_CODES.includes(e.code)).map((e) => ({ value: [e.end_ms, 0], itemStyle: { color: eventTypes[e.code]?.color } })),
      symbol: "rect",
      symbolSize: [2, 10],
      yAxisIndex: 2,
      silent: true,
      markArea: {
        silent: true,
        itemStyle: { color: "rgba(37,99,235,0.18)", borderColor: "#2563eb", borderWidth: 1 },
        data: [[{ xAxis: range[0] }, { xAxis: range[1] }]],
      },
    });
    return {
      backgroundColor: "transparent",
      animation: false,
      grid: { left: GRID_LEFT, right: GRID_RIGHT, top: 4, bottom: 18 },
      xAxis: {
        type: "time",
        min: full[0],
        max: full[1],
        axisLabel: { color: theme.muted, fontSize: 10, formatter: (v: number) => clock(v) },
        splitLine: { show: false },
        axisLine: { lineStyle: { color: theme.axis } },
      },
      yAxis: [
        { type: "value", show: false, scale: true },
        { type: "value", show: false, min: 0 },
        { type: "value", show: false, min: 0, max: 1 },
      ],
      series,
    };
  }, [overview.data, events, eventTypes, range, full, theme, available]);

  const panelOptions = useMemo(
    () => visiblePanels.map((p, i) => panelOption(p, i === visiblePanels.length - 1)),
    [visiblePanels, panelOption],
  );

  const register = (id: string) => (c: ECharts) => {
    charts.current.set(id, c);
  };

  const overviewClick = (e: React.MouseEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const w = rect.width - GRID_LEFT - GRID_RIGHT;
    const f = Math.min(1, Math.max(0, (e.clientX - rect.left - GRID_LEFT) / w));
    const t = full[0] + f * (full[1] - full[0]);
    const span = range[1] - range[0];
    setRange(clamp(t - span / 2, t + span / 2));
  };

  const togglePanel = (id: string) => {
    if (id.startsWith("x:")) {
      setPrefs((p) => ({ ...p, extras: p.extras.includes(id) ? p.extras.filter((x) => x !== id) : [...p.extras, id] }));
    } else {
      setPrefs((p) => ({ ...p, hidden: p.hidden.includes(id) ? p.hidden.filter((x) => x !== id) : [...p.hidden, id] }));
    }
  };
  const toggleExtra = (c: string) =>
    setPrefs((p) => ({ ...p, extras: p.extras.includes(c) ? p.extras.filter((x) => x !== c) : [...p.extras, c] }));

  const spanMin = (range[1] - range[0]) / 60_000;
  const anyDownsampled = Object.values(data).some((d) => d.downsampled);

  return (
    <div>
      <div className="chart-toolbar">
        <div className="btn-group" role="group" aria-label="Zeitfenster">
          <button className="small" onClick={() => { setRange(full); setHighlight(null); }} title="Reset Zoom (Taste 0 / Doppelklick)">
            Ganze Nacht
          </button>
          <button className="small" onClick={() => setSpan(3600_000)}>1 h</button>
          <button className="small" onClick={() => setSpan(15 * 60_000)}>15 min</button>
          <button className="small" onClick={() => setSpan(5 * 60_000)}>5 min</button>
          <button className="small" onClick={() => setSpan(60_000)}>1 min</button>
        </div>
        <div className="btn-group">
          <button className="small" onClick={() => pan(-0.5)} aria-label="Zurück">◀</button>
          <button className="small" onClick={() => zoom(0.6)} aria-label="Hineinzoomen">＋</button>
          <button className="small" onClick={() => zoom(1.6)} aria-label="Herauszoomen">－</button>
          <button className="small" onClick={() => pan(0.5)} aria-label="Vor">▶</button>
        </div>
        <div className="btn-group" role="group" aria-label="Maus-Modus">
          <button className={`small ${mode === "select" ? "active" : ""}`} onClick={() => setMode("select")} title="Bereich mit der Maus aufziehen zum Zoomen">
            Bereich wählen
          </button>
          <button className={`small ${mode === "pan" ? "active" : ""}`} onClick={() => setMode("pan")} title="Mit der Maus verschieben">
            Verschieben
          </button>
        </div>
        <label className="check small">
          <input type="checkbox" checked={showFlags} onChange={(e) => setShowFlags(e.target.checked)} /> Ereignisse im Flow
        </label>
        <span className="grow" />
        <span className="muted small nowrap">
          {clock(range[0], spanMin < 15)} – {clock(range[1], spanMin < 15)} ({spanMin >= 60 ? `${num(spanMin / 60, 1)} h` : `${num(spanMin, spanMin < 5 ? 1 : 0)} min`})
          {q.isFetching ? " · lädt …" : anyDownsampled ? " · reduziert (Min/Max)" : " · volle Auflösung"}
        </span>
      </div>
      <details style={{ marginBottom: "0.5rem" }}>
        <summary className="small muted">Kanäle ein-/ausblenden</summary>
        <div className="channel-picker" style={{ marginTop: "0.5rem" }}>
          {panels.map((p) => {
            const on = p.id.startsWith("x:") ? prefs.extras.includes(p.id) : !prefs.hidden.includes(p.id);
            return (
              <label key={p.id} className="check small">
                <input type="checkbox" checked={on} onChange={() => togglePanel(p.id)} />
                {p.title}
              </label>
            );
          })}
          {panels.flatMap((p) =>
            (p.optional || []).map((c) => (
              <label key={c} className="check small">
                <input type="checkbox" checked={prefs.extras.includes(c)} onChange={() => toggleExtra(c)} />
                {available.get(c)?.name ?? c} (in „{p.title}“)
              </label>
            )),
          )}
        </div>
      </details>
      <div className="chart-panel" onClick={overviewClick} style={{ cursor: "pointer" }} title="Klicken, um das Zeitfenster zu verschieben">
        <EChart option={overviewOption} height={64} notMerge />
      </div>
      <div
        ref={stackRef}
        className={`chart-stack mode-${mode} ${drag.current && mode === "pan" ? "dragging" : ""}`}
        tabIndex={0}
        onKeyDown={onKey}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onDoubleClick={() => {
          setRange(full);
          setHighlight(null);
        }}
        aria-label="Synchronisierte Diagramme. Mausrad zoomt, Umschalt+Mausrad verschiebt, Pfeiltasten verschieben, +/- zoomen, 0 setzt zurück."
      >
        {sel && <div className="sel-overlay" style={{ left: Math.min(sel.x0, sel.x1), width: Math.abs(sel.x1 - sel.x0) }} />}
        {events.length > 0 && (
          <div className="chart-panel">
            <span className="panel-title">Ereignisse</span>
            <EChart option={eventsOption} height={Math.max(70, 18 * lanes.length + 20)} group={group} onInit={register("events")} notMerge />
          </div>
        )}
        {visiblePanels.map((p, i) => (
          <div className="chart-panel" key={p.id}>
            <span className="panel-title">
              {p.title}
              {p.channels.length + (p.optional || []).filter((c) => prefs.extras.includes(c)).length > 1 && (
                <>
                  {" · "}
                  {[...p.channels, ...(p.optional || []).filter((c) => prefs.extras.includes(c))].map((c, k) => (
                    <span key={c} className="legend-item" style={{ marginRight: 8 }}>
                      <span className="legend-swatch" style={{ background: colorFor(c, k) }} />
                      {available.get(c)?.name}
                    </span>
                  ))}
                </>
              )}
            </span>
            <EChart option={panelOptions[i]} height={p.height} group={group} onInit={register(p.id)} notMerge />
          </div>
        ))}
      </div>
      <p className="muted small" style={{ marginTop: "0.5rem" }}>
        Bedienung: Mausrad = Zoom an der Mausposition · Umschalt+Mausrad = verschieben · Bereich aufziehen = Zoom · Doppelklick = ganze Nacht ·
        Tastatur: ←/→, +/−, 0. Ereignismarker im Flow liegen am vom Gerät gespeicherten Zeitpunkt (Ende des Ereignisses), die Fläche zeigt die Dauer.
      </p>
    </div>
  );
}
