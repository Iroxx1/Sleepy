import { useEffect, useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, uploadWithProgress } from "../api/client";
import type { ImportInfo } from "../api/types";
import { Card, ErrorBox, Loading, Modal, Progress } from "../components/ui";
import { bytes, dateTimeDe } from "../lib/format";

const STEPS: [string, string][] = [
  ["upload", "Upload"],
  ["check", "Prüfung"],
  ["detect", "Erkennung"],
  ["archive", "Archivierung"],
  ["parse", "Parsing & Speicherung"],
  ["analyze", "Analyse"],
  ["done", "Fertig"],
];

const STATUS: Record<string, [string, string]> = {
  created: ["Angelegt", ""],
  uploading: ["Upload", "info"],
  queued: ["Wartet", "info"],
  running: ["Läuft", "info"],
  completed: ["Erfolgreich", "ok"],
  completed_with_errors: ["Mit Fehlern", "warn"],
  failed: ["Fehlgeschlagen", "err"],
};

const FILE_STATUS: Record<string, string> = {
  new: "neu",
  updated: "neue Version",
  duplicate: "bereits vorhanden",
  ignored: "ignoriert",
  error: "Fehler",
};

function StatusBadge({ s }: { s: string }) {
  const [l, c] = STATUS[s] ?? [s, ""];
  return <span className={`badge ${c}`}>{l}</span>;
}

function Steps({ stage, uploading }: { stage: string | null; uploading: boolean }) {
  const cur = uploading ? "upload" : stage || "check";
  const idx = STEPS.findIndex(([k]) => k === cur);
  return (
    <div className="steps">
      {STEPS.map(([k, l], i) => (
        <span key={k} className={`step ${i < idx || cur === "done" ? "done" : i === idx ? "current" : ""}`}>
          {i + 1}. {l}
        </span>
      ))}
    </div>
  );
}

function ImportDetails({ id, onClose }: { id: string; onClose: () => void }) {
  const [status, setStatus] = useState("");
  const d = useQuery({ queryKey: ["import", id], queryFn: () => api.get<ImportInfo>(`/api/imports/${id}`) });
  const f = useQuery({
    queryKey: ["import-files", id, status],
    queryFn: () => api.get<{ total: number; items: { path: string; sd_path: string; status: string; kind: string; size: number; sha256: string; message: string }[] }>(
      `/api/imports/${id}/files`,
      { status, limit: 500 },
    ),
  });
  return (
    <Modal title="Importdetails" onClose={onClose}>
      {d.data && (
        <div className="stack">
          <div className="row">
            <StatusBadge s={d.data.status} />
            <span className="small muted">{d.data.original_name}</span>
          </div>
          <div className="small">{d.data.message}</div>
          {d.data.error && <div className="alert err small">{d.data.error}</div>}
          <div className="row small">
            {Object.entries(d.data.file_counts || {}).map(([k, n]) => (
              <button key={k} className={`small ${status === k ? "active" : ""}`} onClick={() => setStatus(status === k ? "" : k)}>
                {FILE_STATUS[k] ?? k}: {n}
              </button>
            ))}
          </div>
          <div className="table-wrap" style={{ maxHeight: 260 }}>
            <table className="table small">
              <thead>
                <tr>
                  <th>Datei</th>
                  <th>Status</th>
                  <th className="num">Größe</th>
                </tr>
              </thead>
              <tbody>
                {f.data?.items.map((x) => (
                  <tr key={x.path} title={`${x.message ?? ""}\nSHA-256: ${x.sha256 ?? "–"}`}>
                    <td className="mono">{x.sd_path || x.path}</td>
                    <td>{FILE_STATUS[x.status] ?? x.status}</td>
                    <td className="num">{bytes(x.size)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {d.data.log && d.data.log.length > 0 && (
            <details open={d.data.status !== "completed"}>
              <summary className="small">Protokoll ({d.data.log.length})</summary>
              <div className="log">
                {d.data.log.map((l, i) => (
                  <div key={i} className={l.level}>
                    {l.t?.slice(11)} {l.text} {l.file ? `(${l.file})` : ""}
                  </div>
                ))}
              </div>
            </details>
          )}
          <a className="btn small" href={`/api/export/raw.zip?import_id=${id}`}>
            Originaldateien dieses Imports herunterladen
          </a>
        </div>
      )}
    </Modal>
  );
}

export default function Import() {
  const qc = useQueryClient();
  const [current, setCurrent] = useState<ImportInfo | null>(null);
  const [upload, setUpload] = useState<{ loaded: number; total: number; label: string } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [over, setOver] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const zipInput = useRef<HTMLInputElement>(null);
  const dirInput = useRef<HTMLInputElement>(null);

  const list = useQuery({ queryKey: ["imports"], queryFn: () => api.get<{ items: ImportInfo[] }>("/api/imports", { limit: 50 }) });
  const server = useQuery({
    queryKey: ["server-info"],
    queryFn: () => api.get<{ configured: boolean; path: string | null; exists: boolean; auto_scan_minutes: number; max_upload_mb: number }>("/api/imports/server-info"),
  });

  // poll the running import
  useEffect(() => {
    if (!current || ["completed", "completed_with_errors", "failed"].includes(current.status) || upload) return;
    const t = setInterval(async () => {
      try {
        const r = await api.get<ImportInfo>(`/api/imports/${current.id}`);
        setCurrent(r);
        if (["completed", "completed_with_errors", "failed"].includes(r.status)) {
          qc.invalidateQueries();
        }
      } catch (e) {
        setError(e);
      }
    }, 1000);
    return () => clearInterval(t);
  }, [current, upload, qc]);

  useEffect(() => {
    if (dirInput.current) {
      dirInput.current.setAttribute("webkitdirectory", "");
      dirInput.current.setAttribute("directory", "");
    }
  }, []);

  async function startZip(file: File) {
    setError(null);
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setError(new Error("Bitte eine ZIP-Datei auswählen."));
      return;
    }
    try {
      const imp = await api.post<ImportInfo>("/api/imports", { source: "zip", name: file.name });
      setCurrent(imp);
      setUpload({ loaded: 0, total: file.size, label: file.name });
      const up = uploadWithProgress("PUT", `/api/imports/${imp.id}/upload?filename=${encodeURIComponent(file.name)}`, file, (l, t) =>
        setUpload({ loaded: l, total: t, label: file.name }),
      );
      abortRef.current = up.abort;
      await up.promise;
      setUpload(null);
      setCurrent(await api.post<ImportInfo>(`/api/imports/${imp.id}/start`));
    } catch (e) {
      setUpload(null);
      setError(e);
    }
  }

  async function startFolder(files: FileList) {
    setError(null);
    const arr = Array.from(files);
    if (!arr.length) return;
    const total = arr.reduce((s, f) => s + f.size, 0);
    const name = (arr[0] as File & { webkitRelativePath?: string }).webkitRelativePath?.split("/")[0] || "Ordner";
    try {
      const imp = await api.post<ImportInfo>("/api/imports", { source: "folder", name });
      setCurrent(imp);
      let done = 0;
      setUpload({ loaded: 0, total, label: `${arr.length} Dateien` });
      const BATCH = 150;
      for (let i = 0; i < arr.length; i += BATCH) {
        const fd = new FormData();
        const part = arr.slice(i, i + BATCH);
        for (const f of part) {
          fd.append("files", f, f.name);
          fd.append("paths", (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name);
        }
        const base = done;
        const up = uploadWithProgress("POST", `/api/imports/${imp.id}/files`, fd, (l) => setUpload({ loaded: base + l, total, label: `${arr.length} Dateien` }));
        abortRef.current = up.abort;
        await up.promise;
        done += part.reduce((s, f) => s + f.size, 0);
      }
      setUpload(null);
      setCurrent(await api.post<ImportInfo>(`/api/imports/${imp.id}/start`));
    } catch (e) {
      setUpload(null);
      setError(e);
    }
  }

  async function serverScan() {
    setError(null);
    try {
      setCurrent(await api.post<ImportInfo>("/api/imports/server-scan"));
    } catch (e) {
      setError(e);
    }
  }

  async function demo() {
    setError(null);
    if (!confirm("60 Nächte synthetische Beispieldaten erzeugen? Sie erscheinen als eigenes „Demo-Gerät“ und lassen sich unter Geräte wieder vollständig löschen.")) return;
    try {
      setCurrent(await api.post<ImportInfo>("/api/imports/demo", { nights: 60 }));
    } catch (e) {
      setError(e);
    }
  }

  async function retry(id: string) {
    setError(null);
    try {
      setCurrent(await api.post<ImportInfo>(`/api/imports/${id}/retry`));
    } catch (e) {
      setError(e);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) startZip(f);
  }

  const running = !!upload || (current && !["completed", "completed_with_errors", "failed"].includes(current.status));
  const st = current?.stats || {};
  return (
    <div className="stack">
      <Card title="CPAP-Daten importieren">
        <div
          className={`dropzone ${over ? "over" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={onDrop}
        >
          <p style={{ marginTop: 0 }}>
            Kopiere den <strong>kompletten Inhalt der SD-Karte</strong> (z. B. STR.edf, Identification.*, DATALOG/) als ZIP-Datei oder wähle den
            Ordner direkt aus. Bereits importierte Dateien werden automatisch erkannt.
          </p>
          <div className="row" style={{ justifyContent: "center" }}>
            <button className="primary" disabled={!!running} onClick={() => zipInput.current?.click()}>
              ZIP-Datei auswählen
            </button>
            <button disabled={!!running} onClick={() => dirInput.current?.click()}>
              Ordner auswählen
            </button>
            {server.data?.configured && (
              <button disabled={!!running || !server.data.exists} onClick={serverScan} title={server.data.path ?? ""}>
                Server-Verzeichnis importieren
              </button>
            )}
          </div>
          <p className="muted small" style={{ marginBottom: 0 }}>
            oder ZIP-Datei hierher ziehen · max. {server.data ? `${(server.data.max_upload_mb / 1024).toFixed(0)} GB` : "…"}
            {server.data?.configured && (
              <>
                {" "}
                · Server-Verzeichnis: <code>{server.data.path}</code>
                {server.data.auto_scan_minutes > 0 && ` (automatische Prüfung alle ${server.data.auto_scan_minutes} min)`}
              </>
            )}
          </p>
          <p className="small" style={{ marginBottom: 0 }}>
            Noch keine eigenen Daten zur Hand?{" "}
            <button className="small" disabled={!!running} onClick={demo}>
              Beispieldaten laden (synthetisch)
            </button>
          </p>
          <input ref={zipInput} type="file" accept=".zip,application/zip" hidden onChange={(e) => e.target.files?.[0] && startZip(e.target.files[0])} />
          <input ref={dirInput} type="file" multiple hidden onChange={(e) => e.target.files && startFolder(e.target.files)} />
        </div>
        <ErrorBox error={error} />
      </Card>

      {current && (
        <Card title={current.original_name ? `Import: ${current.original_name}` : "Import"} actions={<StatusBadge s={upload ? "uploading" : current.status} />}>
          <div className="stack" style={{ gap: "0.75rem" }}>
            <Steps stage={current.stage} uploading={!!upload} />
            {upload ? (
              <>
                <div className="row between small">
                  <span>Lade hoch: {upload.label}</span>
                  <span>
                    {bytes(upload.loaded)} / {bytes(upload.total)} ({Math.round((upload.loaded / Math.max(upload.total, 1)) * 100)} %)
                  </span>
                </div>
                <Progress value={upload.loaded / Math.max(upload.total, 1)} />
                <button className="small" onClick={() => abortRef.current?.()}>
                  Abbrechen
                </button>
              </>
            ) : (
              <>
                <div className="row between small">
                  <span>{current.message}</span>
                  <span>{Math.round(current.progress * 100)} %</span>
                </div>
                <Progress value={current.progress} />
              </>
            )}
            {["completed", "completed_with_errors"].includes(current.status) && (
              <div className={`alert ${current.status === "completed" ? "ok" : "warn"}`}>
                <strong>{current.message}</strong>
                <div className="small">
                  Dateien: {st.files_new ?? 0} neu · {st.files_updated ?? 0} aktualisiert · {st.files_duplicate ?? 0} bereits vorhanden ·{" "}
                  {st.files_ignored ?? 0} ignoriert · {st.files_error ?? 0} Fehler. Nächte: {st.nights_created ?? 0} neu ·{" "}
                  {st.nights_updated ?? 0} aktualisiert · {st.nights_unchanged ?? 0} unverändert · {st.nights_failed ?? 0} fehlgeschlagen.
                </div>
                <div className="row" style={{ marginTop: 6 }}>
                  <Link to="/">Zum Dashboard</Link>
                  <Link to="/nights">Zu den Nächten</Link>
                  <button className="small" onClick={() => setDetail(current.id)}>
                    Details & Protokoll
                  </button>
                </div>
              </div>
            )}
            {current.status === "failed" && (
              <div className="alert err">
                <strong>{current.message}</strong>
                {current.error && <div className="small">{current.error}</div>}
                <div className="small">Es wurden keine bestehenden Daten verändert.</div>
                <div className="row" style={{ marginTop: 6 }}>
                  <button className="small" onClick={() => retry(current.id)}>
                    Erneut versuchen
                  </button>
                  <button className="small" onClick={() => setDetail(current.id)}>
                    Protokoll
                  </button>
                </div>
              </div>
            )}
          </div>
        </Card>
      )}

      <Card title="Import-Verlauf">
        {list.isLoading && <Loading />}
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Datum</th>
                <th>Quelle</th>
                <th>Status</th>
                <th>Ergebnis</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data?.items.map((i) => (
                <tr key={i.id}>
                  <td className="nowrap">{dateTimeDe(i.created_at)}</td>
                  <td className="small">
                    {{ zip: "ZIP", folder: "Ordner", server_dir: "Server", reprocess: "Neuberechnung", demo: "Beispieldaten" }[i.source] ?? i.source}
                    {i.original_name && <span className="muted"> · {i.original_name}</span>}
                  </td>
                  <td>
                    <StatusBadge s={i.status} />
                  </td>
                  <td className="small" style={{ whiteSpace: "normal" }}>
                    {i.message}
                  </td>
                  <td className="nowrap">
                    <button className="small" onClick={() => setDetail(i.id)}>
                      Details
                    </button>{" "}
                    {i.can_retry && (
                      <button className="small" onClick={() => retry(i.id)}>
                        Wiederholen
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {detail && <ImportDetails id={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}
