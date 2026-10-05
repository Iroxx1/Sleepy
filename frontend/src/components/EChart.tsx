import { useEffect, useRef } from "react";
import type { ECharts, EChartsCoreOption } from "echarts/core";
import { echarts } from "../lib/echarts";
import { useTheme } from "../hooks/useTheme";

interface Props {
  option: EChartsCoreOption;
  height?: number | string;
  group?: string;
  notMerge?: boolean;
  onInit?: (chart: ECharts) => void;
  onEvents?: Record<string, (params: any) => void>;
  className?: string;
  ariaLabel?: string;
}

/** Thin React wrapper around an ECharts instance (resize aware). */
export default function EChart({ option, height = 260, group, notMerge, onInit, onEvents, className, ariaLabel }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<ECharts | null>(null);
  const { resolved } = useTheme();

  useEffect(() => {
    if (!ref.current) return;
    const c = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chart.current = c;
    if (group) {
      c.group = group;
      echarts.connect(group);
    }
    onInit?.(c);
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      c.dispose();
      chart.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolved]);

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: notMerge ?? false, lazyUpdate: true });
  }, [option, notMerge, resolved]);

  useEffect(() => {
    const c = chart.current;
    if (!c || !onEvents) return;
    for (const [name, fn] of Object.entries(onEvents)) c.on(name, fn);
    return () => {
      for (const [name, fn] of Object.entries(onEvents)) c.off(name, fn);
    };
  }, [onEvents, resolved]);

  return <div ref={ref} className={className} style={{ width: "100%", height }} role="img" aria-label={ariaLabel} />;
}
