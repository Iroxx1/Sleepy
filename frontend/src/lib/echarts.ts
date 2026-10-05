// Tree-shaken ECharts build (only what Sleepy uses).
import * as echarts from "echarts/core";
import { BarChart, CustomChart, HeatmapChart, LineChart, ScatterChart } from "echarts/charts";
import {
  CalendarComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TitleComponent,
  ToolboxComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  LineChart,
  BarChart,
  ScatterChart,
  CustomChart,
  HeatmapChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  MarkAreaComponent,
  DataZoomComponent,
  ToolboxComponent,
  TitleComponent,
  VisualMapComponent,
  CalendarComponent,
  CanvasRenderer,
]);

export { echarts };

export interface ChartTheme {
  text: string;
  muted: string;
  grid: string;
  axis: string;
  bg: string;
  tooltipBg: string;
}

export function chartTheme(): ChartTheme {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string, d: string) => s.getPropertyValue(n).trim() || d;
  return {
    text: v("--text", "#111827"),
    muted: v("--muted", "#6b7280"),
    grid: v("--chart-grid", "#e5e7eb"),
    axis: v("--border", "#d1d5db"),
    bg: v("--surface", "#ffffff"),
    tooltipBg: v("--surface-2", "#ffffff"),
  };
}

export const PALETTE = {
  flow: "#2563eb",
  pressure: "#16a34a",
  epap: "#0ea5e9",
  ipap: "#22c55e",
  mask_pressure: "#a855f7",
  mask_pressure_hi: "#84cc16",
  leak: "#f59e0b",
  flow_limit: "#0891b2",
  snore: "#65a30d",
  resp_rate: "#db2777",
  tidal_volume: "#7c3aed",
  minute_vent: "#0d9488",
  target_vent: "#64748b",
  spo2: "#e11d48",
  pulse: "#ea580c",
  ahi: "#2563eb",
  usage: "#16a34a",
} as Record<string, string>;

export const EXTRA_COLORS = ["#475569", "#9333ea", "#0f766e", "#b45309", "#be123c", "#4d7c0f", "#1d4ed8"];

export function colorFor(code: string, i = 0): string {
  return PALETTE[code] || PALETTE[code.replace(/_\d+$/, "")] || EXTRA_COLORS[i % EXTRA_COLORS.length];
}
