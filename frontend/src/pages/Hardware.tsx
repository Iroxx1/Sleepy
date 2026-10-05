import { useMemo, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Device, HardwareItem, HardwareList } from "../api/types";
import { Card, Empty, ErrorBox, Kpi, Loading, Modal, Progress } from "../components/ui";
import EChart from "../components/EChart";
import { chartTheme } from "../lib/echarts";
import { dateDe, num, today } from "../lib/format";
import { useTheme } from "../hooks/useTheme";

type Form = {
  category: string;
  name: string;
  manufacturer: string;
  model: string;
  size: string;
  serial: string;
  device_id: string;
  started_on: string;
  ended_on: string;
  replace_after_days: string;
  expected_hours: string;
  notes: string;
};

const EMPTY: Form = {
  category: "mask", name: "", manufacturer: "", model: "", size: "", serial: "", device_id: "",
  started_on: today(), ended_on: "", replace_after_days: "", expected_hours: "", notes: "",
};

const INTERVAL_HINT: Record<string, string> = {
  mask: "z. B. 365 (laut Hersteller/Krankenkasse)",
  cushion: "z. B. 90–180",
  filter: "z. B. 30",
  tube: "z. B. 180–365",
  humidifier: "z. B. 180–365",
};

function age(days: number | null): string {
  if (days == null) return "–";
  if (days < 60) return `${days} Tage`;
  const months = days / 30.44;
  if (months < 24) return `${num(months, 1)} Monate`;
  return `${num(days / 365.25, 1)} Jahre`;
}

function toBody(f: Form) {
  const n = (s: string) => (s.trim() === "" ? null : Number(s));
  const t = (s: string) => (s.trim() === "" ? null : s.trim());
  return {
    category: f.category,
    name: f.name.trim(),
    manufacturer: t(f.manufacturer),
    model: t(f.model),
    size: t(f.size),
    serial: t(f.serial),
    device_id: n(f.device_id),
    started_on: t(f.started_on),
    ended_on: t(f.ended_on),
    replace_after_days: n(f.replace_after_days),
    expected_hours: n(f.expected_hours),
    notes: t(f.notes),
  };
}

function ItemForm({ initial, categories, devices, onSave, onCancel }: {
  initial: Form;
  categories: Record<string, string>;
  devices: Device[];
  onSave: (f: Form) => Promise<void>;
  onCancel: () => void;
}) {
  const [f, setF] = useState<Form>(initial);
  const [err, setErr] = useState<unknown>(null);
  const set = (k: keyof Form) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      await onSave(f);
    } catch (x) {
      setErr(x);
    }
  }
  return (
    <form className="form" style={{ maxWidth: "none" }} onSubmit={submit}>
      <div className="grid cols-2">
        <label className="field">Kategorie
          <select value={f.category} onChange={set("category")}>
            {Object.entries(categories).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
        <label className="field">Bezeichnung *
          <input required value={f.name} onChange={set("name")} placeholder="z. B. AirFit F20" />
        </label>
        <label className="field">Hersteller<input value={f.manufacturer} onChange={set("manufacturer")} /></label>
        <label className="field">Modell<input value={f.model} onChange={set("model")} /></label>
        <label className="field">Größe<input value={f.size} onChange={set("size")} placeholder="S / M / L …" /></label>
        <label className="field">Seriennummer<input value={f.serial} onChange={set("serial")} /></label>
        <label className="field">In Gebrauch seit<input type="date" value={f.started_on} onChange={set("started_on")} /></label>
        <label className="field">Außer Gebrauch seit (leer = aktiv)<input type="date" value={f.ended_on} onChange={set("ended_on")} /></label>
        <label className="field">Austauschintervall (Tage)
          <input type="number" min={1} value={f.replace_after_days} onChange={set("replace_after_days")} placeholder={INTERVAL_HINT[f.category] ?? "optional"} />
        </label>
        {f.category === "device" && (
          <label className="field">Erwartete Laufzeit Turbine (h, optional)
            <input type="number" min={1} value={f.expected_hours} onChange={set("expected_hours")} placeholder="nur falls bekannt" />
          </label>
        )}
        <label className="field">Zugehöriges Gerät (für Nutzungsstunden)
          <select value={f.device_id} onChange={set("device_id")}>
            <option value="">alle Geräte</option>
            {devices.map((d) => <option key={d.id} value={d.id}>{d.display_name || `${d.model ?? d.manufacturer} (${d.serial})`}</option>)}
          </select>
        </label>
      </div>
      <label className="field">Notizen<textarea rows={2} value={f.notes} onChange={set("notes")} /></label>
      <ErrorBox error={err} />
      <div className="row">
        <button className="primary" type="submit">Speichern</button>
        <button type="button" onClick={onCancel}>Abbrechen</button>
      </div>
    </form>
  );
}

function DueBadge({ it }: { it: HardwareItem }) {
  if (!it.due) return null;
  const { status, days_left, due_on } = it.due;
  if (status === "due") return <span className="badge err">Intervall seit {-days_left} Tagen erreicht</span>;
  if (status === "soon") return <span className="badge warn">Wechsel in {days_left} Tagen ({dateDe(due_on)})</span>;
  return <span className="badge ok">Wechsel am {dateDe(due_on)}</span>;
}

function ReadingsPanel({ it, kinds, onChanged }: { it: HardwareItem; kinds: Record<string, string>; onChanged: () => void }) {
  const { resolved } = useTheme();
  const [d, setD] = useState(today());
  const [v, setV] = useState("");
  const [kind, setKind] = useState("blower_hours");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const st = it.reading_stats.blower_hours ?? Object.values(it.reading_stats)[0];
  const option = useMemo(() => {
    const t = chartTheme();
    const byKind = new Map<string, [string, number][]>();
    for (const r of it.readings) byKind.set(r.kind, [...(byKind.get(r.kind) || []), [r.read_on, r.value]]);
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis", backgroundColor: t.tooltipBg, textStyle: { color: t.text } },
      legend: { textStyle: { color: t.muted }, top: 0 },
      grid: { left: 60, right: 16, top: 30, bottom: 28 },
      xAxis: { type: "time", axisLabel: { color: t.muted } },
      yAxis: { type: "value", name: "h", scale: true, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.grid } } },
      series: [...byKind.entries()].map(([k, pts]) => ({
        name: kinds[k] ?? k,
        type: "line",
        data: pts,
        symbolSize: 7,
        markLine: it.expected_hours && k === "blower_hours"
          ? { silent: true, symbol: "none", lineStyle: { color: "#dc2626", type: "dashed" }, data: [{ yAxis: it.expected_hours }] }
          : undefined,
      })),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [it, kinds, resolved]);

  async function add(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      await api.post(`/api/hardware/${it.id}/readings`, { read_on: d, value: Number(v), kind, note: note || null });
      setV("");
      setNote("");
      onChanged();
    } catch (x) {
      setErr(x);
    }
  }

  return (
    <div className="stack" style={{ gap: "0.75rem", marginTop: "0.75rem" }}>
      <h3 style={{ margin: 0 }}>Laufzeit / Zählerstände</h3>
      <p className="muted small" style={{ margin: 0 }}>
        Den Zählerstand (z. B. Gebläse-/Turbinenstunden oder Gerätestunden) zeigt das Gerät in seinem Info- bzw. Geräteinformationsmenü an –
        die Bezeichnung hängt vom Modell ab. Trage ihn ab und zu hier ein. Eine Lebensdauer-Angabe des Herstellers kannst du optional als
        „erwartete Laufzeit“ hinterlegen; Sleepy enthält dazu keine eigenen Werte.
      </p>
      {st && (
        <div className="kpis">
          <Kpi label="Letzter Stand" value={`${num(st.latest_value, 0)} h`} sub={`am ${dateDe(st.latest_on)}`} />
          <Kpi label="Ø pro Tag" value={st.per_day != null ? `${num(st.per_day, 1)} h` : "–"} sub={st.count > 1 ? `aus ${st.count} Ablesungen` : "ab 2 Ablesungen"} />
          {st.projection && <Kpi label="Anteil erwartete Laufzeit" value={`${num(st.projection.pct_used, 0)} %`} sub={`noch ${num(st.projection.remaining_hours, 0)} h`} />}
          {st.projection?.estimated_date && <Kpi label="Rechnerisch erreicht" value={dateDe(st.projection.estimated_date)} sub="lineare Fortschreibung" />}
          {it.therapy_usage && <Kpi label="Therapie laut Daten" value={`${num(it.therapy_usage.hours, 0)} h`} sub={`${it.therapy_usage.nights} Nächte seit Start`} />}
        </div>
      )}
      {st?.projection && <Progress value={Math.min(1, st.projection.pct_used / 100)} />}
      {st?.decreasing && <div className="alert warn small">Ein Zählerstand ist kleiner als der vorherige – Tippfehler oder Gerätetausch?</div>}
      {it.readings.length > 1 && <EChart option={option} height={220} notMerge />}
      <form className="row" onSubmit={add} style={{ alignItems: "flex-end" }}>
        <label className="field">Datum<input type="date" value={d} onChange={(e) => setD(e.target.value)} required /></label>
        <label className="field">Wert (h)<input type="number" step="0.1" min={0} value={v} onChange={(e) => setV(e.target.value)} required style={{ width: 110 }} /></label>
        <label className="field">Art
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.entries(kinds).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
        <label className="field grow">Notiz<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <button className="primary" type="submit">Ablesung speichern</button>
      </form>
      <ErrorBox error={err} />
      {it.readings.length > 0 && (
        <table className="table small">
          <thead><tr><th>Datum</th><th>Art</th><th className="num">Wert</th><th>Notiz</th><th /></tr></thead>
          <tbody>
            {[...it.readings].reverse().map((r) => (
              <tr key={r.id}>
                <td>{dateDe(r.read_on)}</td>
                <td>{kinds[r.kind] ?? r.kind}</td>
                <td className="num">{num(r.value, 1)} h</td>
                <td>{r.note}</td>
                <td>
                  <button className="small ghost" onClick={async () => { if (confirm("Ablesung löschen?")) { await api.del(`/api/hardware/${it.id}/readings/${r.id}`); onChanged(); } }}>✕</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

interface Impact {
  days: number;
  before: { from: string; to: string };
  after: { from: string; to: string };
  metrics: { key: string; label: string; unit: string; decimals: number; before: { n: number; median: number; mean: number } | null; after: { n: number; median: number; mean: number } | null; diff_median: number | null }[];
  note: string;
}

function ImpactModal({ it, onClose }: { it: HardwareItem; onClose: () => void }) {
  const [days, setDays] = useState(30);
  const q = useQuery({ queryKey: ["hw-impact", it.id, days], queryFn: () => api.get<Impact>(`/api/hardware/${it.id}/impact`, { days }) });
  return (
    <Modal title={`Vorher / nachher: ${it.name}`} onClose={onClose}>
      <div className="row">
        <span className="small">Zeitraum je</span>
        <div className="btn-group">
          {[14, 30, 60, 90].map((d) => <button key={d} className={`small ${days === d ? "active" : ""}`} onClick={() => setDays(d)}>{d} Tage</button>)}
        </div>
      </div>
      <ErrorBox error={q.error} />
      {q.data && (
        <>
          <table className="table small" style={{ marginTop: "0.75rem" }}>
            <thead>
              <tr><th>Kennzahl (Median)</th><th className="num">vorher</th><th className="num">nachher</th><th className="num">Differenz</th></tr>
            </thead>
            <tbody>
              {q.data.metrics.map((m) => (
                <tr key={m.key}>
                  <td>{m.label}</td>
                  <td className="num">{m.before ? `${num(m.before.median, m.decimals)} (n=${m.before.n})` : "–"}</td>
                  <td className="num">{m.after ? `${num(m.after.median, m.decimals)} (n=${m.after.n})` : "–"}</td>
                  <td className="num">{m.diff_median != null ? (m.diff_median > 0 ? "+" : "") + num(m.diff_median, m.decimals) : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            Vorher: {dateDe(q.data.before.from)} – {dateDe(q.data.before.to)} · Nachher: {dateDe(q.data.after.from)} – {dateDe(q.data.after.to)}. {q.data.note}
          </p>
        </>
      )}
    </Modal>
  );
}

function ItemCard({ it, list, devices, onChanged }: { it: HardwareItem; list: HardwareList; devices: Device[]; onChanged: () => void }) {
  const [edit, setEdit] = useState(false);
  const [replace, setReplace] = useState(false);
  const [impact, setImpact] = useState(false);
  const [rep, setRep] = useState({ started_on: today(), name: it.name, size: it.size ?? "" });
  const [err, setErr] = useState<unknown>(null);
  const progress = it.due && it.replace_after_days ? Math.min(1, (it.age_days ?? 0) / it.replace_after_days) : null;
  return (
    <Card
      title={
        <div className="stack" style={{ gap: 2 }}>
          <span className="muted small">{it.category_label}</span>
          <h2 style={{ margin: 0 }}>{it.name}</h2>
        </div>
      }
      actions={<DueBadge it={it} />}
    >
      <div className="kpis">
        <Kpi label="In Gebrauch seit" value={dateDe(it.started_on)} sub={age(it.age_days)} />
        {it.replace_after_days && <Kpi label="Intervall" value={`${it.replace_after_days} Tage`} sub={it.due ? `bis ${dateDe(it.due.due_on)}` : undefined} />}
        {it.therapy_usage && <Kpi label="Therapie seither" value={`${num(it.therapy_usage.hours, 0)} h`} sub={`${it.therapy_usage.nights} Nächte (importierte Daten)`} />}
      </div>
      {progress != null && <div style={{ marginTop: "0.5rem" }}><Progress value={progress} /></div>}
      <div className="small muted" style={{ marginTop: "0.5rem" }}>
        {[it.manufacturer, it.model, it.size && `Größe ${it.size}`, it.serial && `SN ${it.serial}`].filter(Boolean).join(" · ")}
        {it.notes && <div>{it.notes}</div>}
      </div>
      <div className="row" style={{ marginTop: "0.75rem" }}>
        <button className="small primary" onClick={() => setReplace(true)}>Ersetzen / neue starten</button>
        <button className="small" onClick={() => setEdit(true)}>Bearbeiten</button>
        <button className="small" onClick={() => setImpact(true)} disabled={!it.started_on}>Vorher/Nachher</button>
        <button className="small danger" onClick={async () => { if (confirm(`„${it.name}“ löschen?`)) { await api.del(`/api/hardware/${it.id}`); onChanged(); } }}>Löschen</button>
      </div>
      {it.category === "device" && <ReadingsPanel it={it} kinds={list.reading_kinds} onChanged={onChanged} />}
      {edit && (
        <Modal title="Eintrag bearbeiten" onClose={() => setEdit(false)}>
          <ItemForm
            categories={list.categories}
            devices={devices}
            initial={{
              category: it.category, name: it.name, manufacturer: it.manufacturer ?? "", model: it.model ?? "", size: it.size ?? "",
              serial: it.serial ?? "", device_id: it.device_id ? String(it.device_id) : "", started_on: it.started_on ?? "",
              ended_on: it.ended_on ?? "", replace_after_days: it.replace_after_days ? String(it.replace_after_days) : "",
              expected_hours: it.expected_hours ? String(it.expected_hours) : "", notes: it.notes ?? "",
            }}
            onSave={async (f) => { await api.patch(`/api/hardware/${it.id}`, toBody(f)); setEdit(false); onChanged(); }}
            onCancel={() => setEdit(false)}
          />
        </Modal>
      )}
      {replace && (
        <Modal title={`${it.category_label} ersetzen`} onClose={() => setReplace(false)}>
          <p className="small muted">„{it.name}“ wird zum Vortag als „außer Gebrauch“ markiert und ein neuer Eintrag mit denselben Angaben angelegt.</p>
          <div className="form">
            <label className="field">Neu in Gebrauch seit<input type="date" value={rep.started_on} onChange={(e) => setRep({ ...rep, started_on: e.target.value })} /></label>
            <label className="field">Bezeichnung<input value={rep.name} onChange={(e) => setRep({ ...rep, name: e.target.value })} /></label>
            <label className="field">Größe<input value={rep.size} onChange={(e) => setRep({ ...rep, size: e.target.value })} /></label>
            <ErrorBox error={err} />
            <button className="primary" onClick={async () => {
              try {
                await api.post(`/api/hardware/${it.id}/replace`, { started_on: rep.started_on, name: rep.name, size: rep.size || null });
                setReplace(false);
                onChanged();
              } catch (x) { setErr(x); }
            }}>Ersetzen</button>
          </div>
        </Modal>
      )}
      {impact && <ImpactModal it={it} onClose={() => setImpact(false)} />}
    </Card>
  );
}

export default function Hardware() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["hardware"], queryFn: () => api.get<HardwareList>("/api/hardware") });
  const devs = useQuery({ queryKey: ["devices"], queryFn: () => api.get<Device[]>("/api/devices") });
  const [adding, setAdding] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["hardware"] });

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const list = q.data!;
  const active = list.items.filter((i) => i.active);
  const inactive = list.items.filter((i) => !i.active);
  return (
    <div className="stack">
      <Card
        title="Hardware"
        actions={<button className="primary" onClick={() => setAdding(true)}>+ Neuer Eintrag</button>}
      >
        <p className="muted" style={{ margin: 0 }}>
          Erfasse Gerät, Masken, Polster, Schläuche, Filter und Wasserkammer mit dem Datum, ab dem du sie verwendest. Sleepy zeigt das Alter,
          dein eigenes Austauschintervall, die Therapiestunden seit Beginn (aus den importierten Daten), beim Gerät den Verlauf der
          Turbinen-/Laufzeitstunden, und vergleicht Kennzahlen vor und nach einem Wechsel. Wechsel erscheinen als Markierung in den Trend-Diagrammen.
        </p>
      </Card>
      {active.length === 0 && <Empty>Noch keine Hardware erfasst.</Empty>}
      <div className="grid cols-2">
        {active.map((it) => <ItemCard key={it.id} it={it} list={list} devices={devs.data || []} onChanged={refresh} />)}
      </div>
      {inactive.length > 0 && (
        <Card title="Verlauf (nicht mehr in Gebrauch)">
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Kategorie</th><th>Bezeichnung</th><th>von</th><th>bis</th><th className="num">Dauer</th><th className="num">Therapie</th><th /></tr></thead>
              <tbody>
                {inactive.map((it) => (
                  <tr key={it.id}>
                    <td>{it.category_label}</td>
                    <td>{it.name}{it.size && <span className="muted"> ({it.size})</span>}</td>
                    <td>{dateDe(it.started_on)}</td>
                    <td>{dateDe(it.ended_on)}</td>
                    <td className="num">{age(it.age_days)}</td>
                    <td className="num">{it.therapy_usage ? `${num(it.therapy_usage.hours, 0)} h` : "–"}</td>
                    <td>
                      <button className="small ghost" onClick={async () => { if (confirm(`„${it.name}“ löschen?`)) { await api.del(`/api/hardware/${it.id}`); refresh(); } }}>✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {adding && (
        <Modal title="Neue Hardware" onClose={() => setAdding(false)}>
          <ItemForm
            initial={EMPTY}
            categories={list.categories}
            devices={devs.data || []}
            onSave={async (f) => { await api.post("/api/hardware", toBody(f)); setAdding(false); refresh(); }}
            onCancel={() => setAdding(false)}
          />
        </Modal>
      )}
    </div>
  );
}
