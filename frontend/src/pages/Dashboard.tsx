import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Dashboard as DashboardT, HardwareList } from "../api/types";
import { useDevice } from "../hooks/useDevice";
import { Card, Disclaimer, Empty, ErrorBox, Kpi, Loading, StatusDot } from "../components/ui";
import EChart from "../components/EChart";
import { chartTheme, PALETTE } from "../lib/echarts";
import { dateDe, hm, num, weekday } from "../lib/format";
import { useTheme } from "../hooks/useTheme";
import NightTable from "../components/NightTable";

export default function Dashboard() {
  const { deviceId } = useDevice();
  const nav = useNavigate();
  const { resolved } = useTheme();
  const q = useQuery({
    queryKey: ["dashboard", deviceId],
    queryFn: () => api.get<DashboardT>("/api/dashboard", { device_id: deviceId }),
  });

  const hw = useQuery({ queryKey: ["hardware"], queryFn: () => api.get<HardwareList>("/api/hardware") });
  const hwHints = (hw.data?.items || []).filter((i) => i.active && i.due && i.due.status !== "ok");

  const trendOption = useMemo(() => {
    const d = q.data;
    if (!d?.series30) return null;
    const t = chartTheme();
    const th = d.thresholds!;
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis", backgroundColor: t.tooltipBg, textStyle: { color: t.text } },
      legend: { data: ["AHI", "Nutzung (h)"], textStyle: { color: t.muted }, top: 0 },
      grid: { left: 40, right: 44, top: 30, bottom: 28 },
      xAxis: {
        type: "category",
        data: d.series30.map((s) => dateDe(s.date).slice(0, 6)),
        axisLabel: { color: t.muted },
        axisLine: { lineStyle: { color: t.axis } },
      },
      yAxis: [
        { type: "value", name: "AHI", axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.grid } }, nameTextStyle: { color: t.muted } },
        { type: "value", name: "h", axisLabel: { color: t.muted }, splitLine: { show: false }, nameTextStyle: { color: t.muted } },
      ],
      series: [
        {
          name: "Nutzung (h)",
          type: "bar",
          yAxisIndex: 1,
          data: d.series30.map((s) => (s.usage_h == null ? null : +s.usage_h.toFixed(2))),
          itemStyle: { color: PALETTE.usage, opacity: 0.35, borderRadius: [3, 3, 0, 0] },
        },
        {
          name: "AHI",
          type: "line",
          data: d.series30.map((s) => (s.ahi == null ? null : +s.ahi.toFixed(2))),
          itemStyle: { color: PALETTE.ahi },
          symbolSize: 6,
          connectNulls: false,
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: "#dc2626", type: "dashed" },
            data: [{ yAxis: th.ahi_yellow, label: { formatter: `${th.ahi_yellow}`, color: t.muted } }],
          },
        },
      ],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q.data, resolved]);

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  if (d.empty)
    return (
      <Card title="Willkommen bei Sleepy">
        <Empty>
          Noch keine Therapiedaten vorhanden. <Link to="/import">Jetzt SD-Karten-Daten importieren</Link>.
        </Empty>
        <Disclaimer text={d.disclaimer} />
      </Card>
    );
  const ln = d.last_night!;
  const m = ln.all_metrics;
  return (
    <div className="stack">
      <Card
        title={
          <div className="row">
            <StatusDot status={ln.status} />
            <h2 style={{ margin: 0 }}>
              Letzte Nacht · {weekday(ln.date)} {dateDe(ln.date)}
            </h2>
          </div>
        }
        actions={
          <Link className="btn primary" to={`/nights/${ln.id}`}>
            Nacht analysieren
          </Link>
        }
      >
        <div className="kpis">
          <Kpi big label="Nutzung" value={hm(ln.usage_h)} sub={`${ln.session_count} Sitzung(en)`} />
          <Kpi big label="AHI" value={num(m.ahi, 1)} sub="Ereignisse/h" />
          <Kpi label="CAI" value={num(m.cai, 1)} />
          <Kpi label="OAI" value={num(m.oai, 1)} />
          <Kpi label="HI" value={num(m.hi, 1)} />
          <Kpi label="Leck 95 %" value={num(m["leak.p95"], 1)} sub="L/min" />
          <Kpi label="Druck 95 %" value={num(m["pressure.p95"], 1)} sub="cmH2O" />
          {m["flow_limit.p95"] !== undefined && <Kpi label="Flusslim. 95 %" value={num(m["flow_limit.p95"], 2)} />}
          {m["spo2.median"] !== undefined && <Kpi label="SpO2 Median" value={num(m["spo2.median"], 0)} sub="%" />}
        </div>
        {ln.summary && <p style={{ marginBottom: 0 }}>{ln.summary}</p>}
        {ln.anomalies.length > 0 && (
          <div className="alert warn" style={{ marginTop: "0.75rem" }}>
            <strong>Statistisch auffällig:</strong>
            <ul className="obs-list">
              {ln.anomalies.map((a) => (
                <li key={a.key}>{a.text}</li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      {hwHints.length > 0 && (
        <div className="alert info">
          <strong>Hardware:</strong>{" "}
          {hwHints.map((i) => (
            <span key={i.id} style={{ marginRight: 12 }}>
              {i.category_label} „{i.name}“ –{" "}
              {i.due!.status === "due" ? `dein Austauschintervall ist seit ${-i.due!.days_left} Tagen erreicht` : `Austausch laut deinem Intervall in ${i.due!.days_left} Tagen`}
            </span>
          ))}{" "}
          <Link to="/hardware">zur Hardware →</Link>
        </div>
      )}

      <div className="grid cols-2">
        <Card title="Letzte 7 Tage">
          <div className="kpis">
            <Kpi label="Ø AHI" value={num(d.agg7?.ahi_mean, 2)} sub={`Median ${num(d.agg7?.ahi_median, 2)}`} />
            <Kpi label="Ø Nutzung" value={hm(d.agg7?.usage_mean)} />
            <Kpi label="Ø Leck 95 %" value={num(d.agg7?.leak_p95_mean, 1)} sub="L/min" />
            <Kpi label="Tage ≥ 4 h" value={`${num(d.agg7?.compliance_pct, 0)} %`} sub={`${d.agg7?.nights} Nächte`} />
          </div>
        </Card>
        <Card title="Letzte 30 Tage">
          <div className="kpis">
            <Kpi label="Ø AHI" value={num(d.agg30?.ahi_mean, 2)} sub={`Median ${num(d.agg30?.ahi_median, 2)}`} />
            <Kpi label="Ø Nutzung" value={hm(d.agg30?.usage_mean)} />
            <Kpi label="Ø Leck 95 %" value={num(d.agg30?.leak_p95_mean, 1)} sub="L/min" />
            <Kpi label="Tage ≥ 4 h" value={`${num(d.agg30?.compliance_pct, 0)} %`} sub={`${d.agg30?.nights} Nächte`} />
          </div>
        </Card>
      </div>

      {trendOption && (
        <Card title="AHI und Nutzungsdauer – 30 Tage" actions={<Link to="/trends">Alle Trends →</Link>}>
          <EChart
            option={trendOption}
            height={260}
            onEvents={{
              click: (p: { dataIndex: number }) => {
                const s = d.series30?.[p.dataIndex];
                if (s) nav(`/nights/${s.id}`);
              },
            }}
          />
        </Card>
      )}

      <Card title="Letzte Nächte" actions={<Link to="/nights">Alle Nächte →</Link>}>
        <NightTable rows={d.recent || []} />
      </Card>
      <Disclaimer text={d.disclaimer} />
    </div>
  );
}
