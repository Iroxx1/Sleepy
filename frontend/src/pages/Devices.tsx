import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Device } from "../api/types";
import { Card, Empty, ErrorBox, Kpi, Loading } from "../components/ui";
import { dateDe, dateTimeDe } from "../lib/format";

interface History {
  labels: Record<string, string>;
  periods: { from: string; to: string; nights: number; settings: Record<string, unknown>; changes: { key: string; label: string; from: unknown; to: unknown }[] }[];
}

function DeviceCard({ d }: { d: Device }) {
  const qc = useQueryClient();
  const [name, setName] = useState(d.display_name || "");
  const h = useQuery({ queryKey: ["settings-history", d.id], queryFn: () => api.get<History>(`/api/devices/${d.id}/settings-history`) });
  const save = useMutation({
    mutationFn: () => api.patch(`/api/devices/${d.id}`, { display_name: name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["devices"] }),
  });
  const reprocess = useMutation({ mutationFn: () => api.post<{ import_id: string }>("/api/system/reprocess", undefined, { device_id: d.id }) });
  const ident = (d.identification as { data?: Record<string, unknown> } | undefined)?.data;
  return (
    <Card title={`${d.manufacturer} ${d.model ?? ""}`}>
      <div className="kpis">
        <Kpi label="Seriennummer" value={<span className="mono">{d.serial}</span>} />
        <Kpi label="Gerätetyp" value={d.device_type ?? "unbekannt"} sub={d.series ?? undefined} />
        <Kpi label="Nächte" value={d.nights ?? 0} sub={`${dateDe(d.first_night)} – ${dateDe(d.last_night)}`} />
        <Kpi label="Rohdateien" value={d.files ?? 0} />
      </div>
      <table className="table" style={{ marginTop: "0.75rem" }}>
        <tbody>
          <tr>
            <td>Hersteller / Modell</td>
            <td>
              {d.manufacturer} {d.model} {d.product_code && <span className="muted">(Produktcode {d.product_code})</span>}
            </td>
          </tr>
          <tr>
            <td>Firmware</td>
            <td>{d.firmware ?? <span className="muted">nicht aus den Daten ermittelbar</span>}</td>
          </tr>
          <tr>
            <td>Datenformat / Parser</td>
            <td>
              {d.data_format} · {d.parser}
            </td>
          </tr>
          <tr>
            <td>Zuletzt importiert</td>
            <td>{dateTimeDe(d.last_seen_at)}</td>
          </tr>
          <tr>
            <td>Vorhandene Kanäle</td>
            <td className="small">{(d.channels || []).join(", ") || "–"}</td>
          </tr>
        </tbody>
      </table>
      <div className="row" style={{ marginTop: "0.75rem" }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Anzeigename" aria-label="Anzeigename" />
        <button className="small" onClick={() => save.mutate()} disabled={save.isPending}>
          Speichern
        </button>
        <button className="small" onClick={() => reprocess.mutate()} disabled={reprocess.isPending} title="Alle Nächte aus den archivierten Originaldaten neu berechnen (z. B. nach einem Update)">
          Neu berechnen
        </button>
        <a className="btn small" href={`/api/export/raw.zip?device_id=${d.id}`}>
          Originaldaten (ZIP)
        </a>
        <button
          className="small danger"
          onClick={async () => {
            const s = prompt(`Gerät mit allen ${d.nights ?? 0} Nächten löschen?\nZur Bestätigung die Seriennummer eingeben: ${d.serial}`);
            if (s === null) return;
            const raw = confirm("Auch die archivierten Originaldateien dieses Geräts löschen?\n(OK = ja, Abbrechen = Originaldateien behalten)");
            try {
              await api.del(`/api/devices/${d.id}?confirm=${encodeURIComponent(s)}&delete_raw=${raw}`);
              qc.invalidateQueries();
            } catch (e) {
              alert(e instanceof Error ? e.message : String(e));
            }
          }}
        >
          Gerät löschen
        </button>
        {reprocess.isSuccess && <span className="small muted">Neuberechnung gestartet (siehe Import-Verlauf)</span>}
      </div>
      {ident && (
        <details style={{ marginTop: "0.75rem" }}>
          <summary className="small">Identifikationsdaten (roh)</summary>
          <pre className="log">{JSON.stringify(ident, null, 2)}</pre>
        </details>
      )}
      <h3 style={{ marginTop: "1rem" }}>Einstellungsverlauf</h3>
      {h.isLoading && <Loading />}
      {h.data && h.data.periods.length === 0 && <p className="muted">Keine Einstellungsdaten vorhanden.</p>}
      {h.data && h.data.periods.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Zeitraum</th>
                <th className="num">Nächte</th>
                <th>Änderungen gegenüber vorher</th>
              </tr>
            </thead>
            <tbody>
              {[...h.data.periods].reverse().map((p) => (
                <tr key={p.from}>
                  <td className="nowrap">
                    {dateDe(p.from)} – {dateDe(p.to)}
                  </td>
                  <td className="num">{p.nights}</td>
                  <td className="small" style={{ whiteSpace: "normal" }}>
                    {p.changes.length
                      ? p.changes.map((c) => `${c.label}: ${c.from ?? "–"} → ${c.to ?? "–"}`).join(" · ")
                      : Object.entries(p.settings)
                          .filter(([k]) => ["mode_name", "S.AS.MinPress", "S.AS.MaxPress", "S.C.Press", "S.EPR.Level", "S.HumLevel"].includes(k))
                          .map(([k, v]) => `${h.data!.labels[k] ?? (k === "mode_name" ? "Modus" : k)}: ${v}`)
                          .join(" · ") || "Erste Einstellungen"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ErrorBox error={save.error || reprocess.error} />
    </Card>
  );
}

export default function Devices() {
  const q = useQuery({ queryKey: ["devices"], queryFn: () => api.get<Device[]>("/api/devices") });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  if (!q.data?.length) return <Empty>Noch keine Geräte – Geräte werden beim ersten Import automatisch erkannt.</Empty>;
  return (
    <div className="stack">
      {q.data.map((d) => (
        <DeviceCard key={d.id} d={d} />
      ))}
    </div>
  );
}
