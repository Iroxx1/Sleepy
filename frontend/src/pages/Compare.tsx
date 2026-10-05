import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQueries, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { EventType, NightRow, TimeseriesResponse } from "../api/types";
import { useDevice } from "../hooks/useDevice";
import { useTheme } from "../hooks/useTheme";
import { Card, Disclaimer, Empty, ErrorBox, Loading, StatusDot } from "../components/ui";
import EChart from "../components/EChart";
import { chartTheme, EXTRA_COLORS } from "../lib/echarts";
import { dateDe, fmtMetric, num, weekday } from "../lib/format";

interface CompareResp {
  items: (NightRow & { all_metrics: Record<string, number>; event_counts: Record<string, number> })[];
  metrics: { key: string; label: string; unit: string; decimals: number }[];
}

const LOWER_BETTER = new Set(["ahi", "ai", "hi", "oai", "cai", "uai", "rdi", "rera_index", "leak.p95", "leak.median", "leak.max", "odi"]);
const OVERLAY_CHANNELS: [string, string][] = [
  ["pressure", "Druck"],
  ["leak", "Leckage"],
  ["flow_limit", "Flusslimitierung"],
  ["resp_rate", "Atemfrequenz"],
  ["tidal_volume", "Atemzugvolumen"],
  ["minute_vent", "Atemminutenvolumen"],
  ["spo2", "SpO2"],
];

export default function Compare() {
  const [sp, setSp] = useSearchParams();
  const { deviceId } = useDevice();
  const { resolved } = useTheme();
  const ids = (sp.get("ids") || "").split(",").filter(Boolean).map(Number);
  const [overlay, setOverlay] = useState("pressure");
  const [pickDate, setPickDate] = useState("");

  const cq = useQuery({
    queryKey: ["compare", ids.join(",")],
    queryFn: () => api.get<CompareResp>("/api/nights/compare", { ids: ids.join(",") }),
    enabled: ids.length > 0,
  });
  const types = useQuery({ queryKey: ["event-types"], queryFn: () => api.get<Record<string, EventType>>("/api/events/types") });
  const recent = useQuery({
    queryKey: ["nights-recent-pick", deviceId],
    queryFn: () => api.get<{ items: NightRow[] }>("/api/nights", { device_id: deviceId, limit: 60 }),
  });
  const series = useQueries({
    queries: ids.map((id) => ({
      queryKey: ["cmp-ts", id, overlay],
      queryFn: () => api.get<TimeseriesResponse>(`/api/nights/${id}/timeseries`, { channels: overlay, points: 700 }),
      staleTime: 5 * 60_000,
    })),
  });

  const setIds = (n: number[]) => {
    const s = new URLSearchParams(sp);
    s.set("ids", n.join(","));
    setSp(s, { replace: true });
  };
  const add = (id: number) => !ids.includes(id) && ids.length < 12 && setIds([...ids, id]);
  const remove = (id: number) => setIds(ids.filter((x) => x !== id));

  const items = cq.data?.items || [];
  const ty = types.data || {};

  const barsOption = useMemo(() => {
    if (!items.length) return null;
    const t = chartTheme();
    const cats = items.map((r) => dateDe(r.date).slice(0, 6));
    const codes = [...new Set(items.flatMap((r) => Object.keys(r.event_counts)))].filter((c) => c !== "OTHER");
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", backgroundColor: t.tooltipBg, textStyle: { color: t.text } },
      legend: { textStyle: { color: t.muted }, top: 0, right: 0, data: codes.map((c) => ty[c]?.short ?? c) },
      grid: [
        { left: 40, right: 10, top: 44, width: "28%", bottom: 24 },
        { left: "37%", right: 10, top: 44, width: "28%", bottom: 24 },
        { left: "70%", right: 10, top: 44, bottom: 24 },
      ],
      xAxis: [0, 1, 2].map((i) => ({ type: "category", gridIndex: i, data: cats, axisLabel: { color: t.muted } })),
      yAxis: [0, 1, 2].map((i) => ({
        type: "value",
        gridIndex: i,
        axisLabel: { color: t.muted },
        splitLine: { lineStyle: { color: t.grid } },
        name: ["AHI", "Nutzung (h)", "Ereignisse"][i],
        nameTextStyle: { color: t.muted },
      })),
      series: [
        { name: "AHI", type: "bar", xAxisIndex: 0, yAxisIndex: 0, data: items.map((r) => +(r.all_metrics.ahi ?? 0).toFixed(2)), itemStyle: { color: "#2563eb" } },
        { name: "Nutzung", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: items.map((r) => +(r.all_metrics.usage_h ?? 0).toFixed(2)), itemStyle: { color: "#16a34a" } },
        ...codes.map((c) => ({
          name: ty[c]?.short ?? c,
          type: "bar",
          stack: "ev",
          xAxisIndex: 2,
          yAxisIndex: 2,
          data: items.map((r) => r.event_counts[c] ?? 0),
          itemStyle: { color: ty[c]?.color },
        })),
      ],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, ty, resolved]);

  const overlayOption = useMemo(() => {
    const t = chartTheme();
    const ser = series
      .map((s, i) => {
        const ch = s.data?.channels[overlay];
        const night = items.find((r) => r.id === ids[i]);
        if (!ch || !night || !ch.t.length) return null;
        const t0 = night.start_ms ?? ch.t[0];
        return {
          name: dateDe(night.date),
          type: "line",
          showSymbol: false,
          data: ch.t.map((tt, k) => [(tt - t0) / 3600000, ch.v[k]]),
          lineStyle: { width: 1.2 },
          itemStyle: { color: EXTRA_COLORS[i % EXTRA_COLORS.length] },
        };
      })
      .filter(Boolean);
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis", backgroundColor: t.tooltipBg, textStyle: { color: t.text }, valueFormatter: (v: number) => num(v, 2) },
      legend: { textStyle: { color: t.muted }, top: 0 },
      grid: { left: 48, right: 16, top: 30, bottom: 44 },
      xAxis: { type: "value", name: "Stunden seit Therapiebeginn", nameLocation: "middle", nameGap: 26, axisLabel: { color: t.muted }, nameTextStyle: { color: t.muted } },
      yAxis: { type: "value", scale: true, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.grid } } },
      dataZoom: [{ type: "inside" }],
      series: ser,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series.map((s) => s.dataUpdatedAt).join(","), items, overlay, resolved]);

  const best = (key: string) => {
    const vals = items.map((r) => r.all_metrics[key]).filter((v) => v != null);
    if (vals.length < 2 || !LOWER_BETTER.has(key)) return { min: undefined, max: undefined };
    return { min: Math.min(...vals), max: Math.max(...vals) };
  };

  return (
    <div className="stack">
      <Card title="Nächte auswählen">
        <div className="row">
          {items.map((r) => (
            <span key={r.id} className="badge info">
              {dateDe(r.date)}{" "}
              <button className="small ghost" onClick={() => remove(r.id)} aria-label="Entfernen">
                ✕
              </button>
            </span>
          ))}
          <select value="" onChange={(e) => e.target.value && add(Number(e.target.value))} aria-label="Nacht hinzufügen">
            <option value="">+ Nacht hinzufügen …</option>
            {(recent.data?.items || [])
              .filter((r) => !ids.includes(r.id))
              .map((r) => (
                <option key={r.id} value={r.id}>
                  {weekday(r.date)} {dateDe(r.date)} · AHI {num(r.metrics.ahi, 1)}
                </option>
              ))}
          </select>
          <input type="date" value={pickDate} onChange={(e) => setPickDate(e.target.value)} aria-label="Datum" />
          <button
            className="small"
            disabled={!pickDate}
            onClick={async () => {
              try {
                const r = await api.get<{ id: number }>(`/api/nights/by-date/${pickDate}`, { device_id: deviceId });
                add(r.id);
              } catch {
                alert("Keine Daten für dieses Datum");
              }
            }}
          >
            Datum hinzufügen
          </button>
        </div>
        <p className="muted small" style={{ marginBottom: 0 }}>
          Tipp: In der Liste <Link to="/nights">Nächte</Link> mehrere Nächte ankreuzen und „vergleichen“ wählen.
        </p>
      </Card>
      {ids.length === 0 && <Empty>Bitte mindestens zwei Nächte auswählen.</Empty>}
      <ErrorBox error={cq.error} />
      {cq.isLoading && <Loading />}
      {items.length > 0 && (
        <>
          <Card title="Kennzahlen im Vergleich">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Kennzahl</th>
                    {items.map((r) => (
                      <th key={r.id} className="num">
                        <Link to={`/nights/${r.id}`}>
                          <StatusDot status={r.status} /> {weekday(r.date)} {dateDe(r.date)}
                        </Link>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {cq.data!.metrics
                    .filter((m) => !m.key.startsWith("count.") && !/\.(p5|p25|p75|min|mean)$/.test(m.key))
                    .map((m) => {
                      const b = best(m.key);
                      return (
                        <tr key={m.key}>
                          <td>{m.label}</td>
                          {items.map((r) => {
                            const v = r.all_metrics[m.key];
                            const style = v != null && v === b.min ? { color: "var(--ok)", fontWeight: 600 } : v != null && v === b.max ? { color: "var(--danger)", fontWeight: 600 } : undefined;
                            return (
                              <td key={r.id} className="num" style={style}>
                                {fmtMetric(v, m.unit, m.decimals)}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  <tr>
                    <td>
                      <strong>Ereignisse</strong>
                    </td>
                    {items.map((r) => (
                      <td key={r.id} className="num small">
                        {Object.entries(r.event_counts)
                          .map(([c, n]) => `${ty[c]?.short ?? c} ${n}`)
                          .join(" · ") || "–"}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </Card>
          {barsOption && (
            <Card title="AHI, Nutzung und Ereignisse">
              <EChart option={barsOption} height={300} notMerge />
            </Card>
          )}
          <Card
            title="Überlagerung"
            actions={
              <select value={overlay} onChange={(e) => setOverlay(e.target.value)} aria-label="Kanal">
                {OVERLAY_CHANNELS.map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            }
          >
            <EChart option={overlayOption} height={320} notMerge />
          </Card>
        </>
      )}
      <Disclaimer />
    </div>
  );
}
