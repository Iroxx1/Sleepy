import { useEffect, useRef } from "react";
import type { ECharts, EChartsCoreOption } from "echarts/core";
import { echarts } from "../../../src/lib/echarts";
import { useTheme } from "../../../src/hooks/useTheme";

interface Props {
  option: EChartsCoreOption;
  height: number;
  group?: string;
  onInit?: (c: ECharts) => void;
  onEvents?: Record<string, (p: any) => void>;
  notMerge?: boolean;
}

/**
 * ECharts wrapper for touch screens.  The container allows vertical page
 * scrolling (touch-action: pan-y) while two-finger pinch gestures are handled
 * by ECharts (dataZoom "inside") to zoom into the time axis / scale.
 */
export default function MChart({ option, height, group, onInit, onEvents, notMerge = true }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<ECharts | null>(null);
  const { resolved } = useTheme();

  useEffect(() => {
    const el = ref.current!;
    const c = echarts.init(el, undefined, { renderer: "canvas" });
    chart.current = c;
    if (group) {
      c.group = group;
      echarts.connect(group);
    }
    const allowScroll = () => el.querySelectorAll<HTMLElement>("div, canvas").forEach((n) => (n.style.touchAction = "pan-y"));
    allowScroll();
    c.on("finished", allowScroll);
    onInit?.(c);
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      c.dispose();
      chart.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolved]);

  useEffect(() => {
    chart.current?.setOption(option, { notMerge, lazyUpdate: true });
  }, [option, notMerge, resolved]);

  useEffect(() => {
    const c = chart.current;
    if (!c || !onEvents) return;
    for (const [k, fn] of Object.entries(onEvents)) c.on(k, fn);
    return () => {
      for (const [k, fn] of Object.entries(onEvents)) c.off(k, fn);
    };
  }, [onEvents, resolved]);

  return <div ref={ref} style={{ width: "100%", height, touchAction: "pan-y" }} />;
}

/** inside-dataZoom definition used by all mobile charts (pinch = zoom). */
export function pinchZoom(opts: { id?: string; axis?: "x" | "y"; pan?: boolean; disabled?: boolean; start?: number; end?: number } = {}) {
  const pan = !!opts.pan;
  return {
    type: "inside",
    id: opts.id,
    ...(opts.axis === "y" ? { yAxisIndex: 0 } : { xAxisIndex: 0 }),
    filterMode: "none",
    disabled: !!opts.disabled,
    zoomOnMouseWheel: true,
    moveOnMouseMove: pan,
    moveOnMouseWheel: false,
    preventDefaultMouseMove: pan,
    minValueSpan: opts.axis === "y" ? undefined : 10_000,
    start: opts.start,
    end: opts.end,
  };
}
