import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Thresholds } from "../api/types";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";
import { reloadCustomCss } from "../components/CustomStyles";
import { Card, ErrorBox, Loading } from "../components/ui";
import { bytes, dateTimeDe } from "../lib/format";

function PasswordForm() {
  const [cur, setCur] = useState("");
  const [n1, setN1] = useState("");
  const [n2, setN2] = useState("");
  const m = useMutation({
    mutationFn: () => {
      if (n1 !== n2) throw new Error("Neue Passwörter stimmen nicht überein.");
      return api.post("/api/auth/password", { current_password: cur, new_password: n1 });
    },
    onSuccess: () => {
      setCur("");
      setN1("");
      setN2("");
    },
  });
  return (
    <form
      className="form"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        m.mutate();
      }}
    >
      <label className="field">
        Aktuelles Passwort
        <input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required />
      </label>
      <label className="field">
        Neues Passwort (mind. 10 Zeichen)
        <input type="password" autoComplete="new-password" value={n1} onChange={(e) => setN1(e.target.value)} required />
      </label>
      <label className="field">
        Neues Passwort wiederholen
        <input type="password" autoComplete="new-password" value={n2} onChange={(e) => setN2(e.target.value)} required />
      </label>
      <ErrorBox error={m.error} />
      {m.isSuccess && <div className="alert ok">Passwort geändert. Andere Sitzungen wurden abgemeldet.</div>}
      <button className="primary" type="submit" disabled={m.isPending}>
        Passwort ändern
      </button>
    </form>
  );
}

function TotpSection() {
  const { user, refresh } = useAuth();
  const [setup, setSetup] = useState<{ secret: string; uri: string; qr_svg: string } | null>(null);
  const [code, setCode] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [msg, setMsg] = useState("");
  async function run(fn: () => Promise<unknown>, ok: string) {
    setErr(null);
    setMsg("");
    try {
      await fn();
      setMsg(ok);
      await refresh();
    } catch (e) {
      setErr(e);
    }
  }
  if (user?.totp_enabled)
    return (
      <div className="form">
        <div className="alert ok">Zwei-Faktor-Authentifizierung ist aktiv.</div>
        <label className="field">
          Passwort
          <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} />
        </label>
        <label className="field">
          Aktueller Code
          <input inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />
        </label>
        <ErrorBox error={err} />
        <button className="danger" onClick={() => run(() => api.post("/api/auth/totp/disable", { password: pw, code }), "2FA deaktiviert.")}>
          2FA deaktivieren
        </button>
      </div>
    );
  return (
    <div className="form">
      <p className="muted small">Optional: Schütze dein Konto zusätzlich mit einer Authenticator-App (TOTP, z. B. Aegis, Google Authenticator).</p>
      {!setup ? (
        <button onClick={async () => setSetup(await api.post("/api/auth/totp/setup"))}>2FA einrichten</button>
      ) : (
        <>
          <img alt="QR-Code für die Authenticator-App" style={{ width: 200, background: "#fff", padding: 8, borderRadius: 8 }} src={`data:image/svg+xml;base64,${btoa(setup.qr_svg)}`} />
          <div className="small">
            Schlüssel manuell: <code>{setup.secret}</code>
          </div>
          <label className="field">
            Code aus der App
            <input inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />
          </label>
          <button className="primary" onClick={() => run(() => api.post("/api/auth/totp/enable", { code }), "2FA aktiviert.")}>
            Aktivieren
          </button>
        </>
      )}
      <ErrorBox error={err} />
      {msg && <div className="alert ok">{msg}</div>}
    </div>
  );
}

function ThresholdForm() {
  const { user, refresh } = useAuth();
  const qc = useQueryClient();
  const defaults: Thresholds = { ahi_yellow: 5, ahi_red: 10, usage_min_h: 4, leak_p95_max: 24 };
  const [th, setTh] = useState<Thresholds>({ ...defaults, ...(user?.preferences.thresholds || {}) } as Thresholds);
  const m = useMutation({
    mutationFn: () => api.put("/api/auth/preferences", { thresholds: th }),
    onSuccess: async () => {
      await refresh();
      qc.invalidateQueries();
    },
  });
  const f = (k: keyof Thresholds, label: string, step = "0.5") => (
    <label className="field">
      {label}
      <input type="number" step={step} value={th[k]} onChange={(e) => setTh({ ...th, [k]: Number(e.target.value) })} />
    </label>
  );
  return (
    <div className="form">
      <p className="muted small">
        Diese Schwellen steuern nur die farbliche Markierung (Kalender, Status) und sind keine medizinischen Grenzwerte. Lege sie z. B. in
        Absprache mit deiner Ärztin/deinem Arzt fest.
      </p>
      {f("ahi_yellow", "AHI ab dem „auffällig“ (gelb)")}
      {f("ahi_red", "AHI ab dem „viele Ereignisse“ (rot)")}
      {f("usage_min_h", "Mindestnutzung in Stunden (darunter gelb)")}
      {f("leak_p95_max", "Leckage 95 % in L/min (darüber gelb)", "1")}
      <ErrorBox error={m.error} />
      {m.isSuccess && <div className="alert ok">Gespeichert.</div>}
      <div className="row">
        <button className="primary" onClick={() => m.mutate()}>
          Speichern
        </button>
        <button onClick={() => setTh(defaults)}>Standardwerte</button>
      </div>
    </div>
  );
}

interface AdminUser {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
  totp_enabled: boolean;
  last_login_at: string | null;
}

function UsersAdmin() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["users"], queryFn: () => api.get<AdminUser[]>("/api/users") });
  const [u, setU] = useState({ username: "", password: "", role: "user" });
  const [err, setErr] = useState<unknown>(null);
  async function act(fn: () => Promise<unknown>) {
    setErr(null);
    try {
      await fn();
      qc.invalidateQueries({ queryKey: ["users"] });
    } catch (e) {
      setErr(e);
    }
  }
  return (
    <div className="stack">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Benutzer</th>
              <th>Rolle</th>
              <th>Status</th>
              <th>2FA</th>
              <th>Letzter Login</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {q.data?.map((x) => (
              <tr key={x.id}>
                <td>{x.username}</td>
                <td>
                  <select value={x.role} onChange={(e) => act(() => api.patch(`/api/users/${x.id}`, { role: e.target.value }))}>
                    <option value="user">Benutzer</option>
                    <option value="admin">Administrator</option>
                  </select>
                </td>
                <td>{x.is_active ? "aktiv" : "deaktiviert"}</td>
                <td>{x.totp_enabled ? "ja" : "nein"}</td>
                <td className="small">{dateTimeDe(x.last_login_at)}</td>
                <td className="nowrap">
                  <button className="small" onClick={() => act(() => api.patch(`/api/users/${x.id}`, { is_active: !x.is_active }))}>
                    {x.is_active ? "Deaktivieren" : "Aktivieren"}
                  </button>{" "}
                  <button
                    className="small"
                    onClick={() => {
                      const pw = prompt("Neues Passwort (mind. 10 Zeichen):");
                      if (pw) act(() => api.patch(`/api/users/${x.id}`, { password: pw }));
                    }}
                  >
                    Passwort
                  </button>{" "}
                  {x.totp_enabled && (
                    <button className="small" onClick={() => act(() => api.patch(`/api/users/${x.id}`, { reset_totp: true }))}>
                      2FA zurücksetzen
                    </button>
                  )}{" "}
                  <button className="small danger" onClick={() => confirm(`Benutzer ${x.username} löschen?`) && act(() => api.del(`/api/users/${x.id}`))}>
                    Löschen
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Neuer Benutzer</h3>
      <div className="row">
        <input placeholder="Benutzername" value={u.username} onChange={(e) => setU({ ...u, username: e.target.value })} />
        <input placeholder="Passwort" type="password" value={u.password} onChange={(e) => setU({ ...u, password: e.target.value })} />
        <select value={u.role} onChange={(e) => setU({ ...u, role: e.target.value })}>
          <option value="user">Benutzer</option>
          <option value="admin">Administrator</option>
        </select>
        <button
          className="primary"
          onClick={() =>
            act(async () => {
              await api.post("/api/users", u);
              setU({ username: "", password: "", role: "user" });
            })
          }
        >
          Anlegen
        </button>
      </div>
      <p className="muted small">Jeder Benutzer sieht ausschließlich seine eigenen Geräte und Daten.</p>
      <ErrorBox error={err} />
    </div>
  );
}

interface Diag {
  version: string;
  python: string;
  platform: string;
  database: string;
  libraries: Record<string, string>;
  parsers: { name: string; manufacturer: string; version: string }[];
  paths: Record<string, string | null>;
  storage: Record<string, number>;
  counts: Record<string, number>;
  worker: { current: string | null; queued: number };
  log_tail: string[];
}

function SystemAdmin() {
  const qc = useQueryClient();
  const d = useQuery({ queryKey: ["diag"], queryFn: () => api.get<Diag>("/api/system/diagnostics") });
  const b = useQuery({ queryKey: ["backups"], queryFn: () => api.get<{ name: string; size: number; created: string }[]>("/api/system/backups") });
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.get<{ id: number; created_at: string; username: string; action: string; ip: string; detail: Record<string, unknown> }[]>("/api/system/audit", { limit: 100 }) });
  const mk = useMutation({ mutationFn: (raw: boolean) => api.post("/api/system/backups", undefined, { include_raw: raw }), onSuccess: () => qc.invalidateQueries({ queryKey: ["backups"] }) });
  const re = useMutation({ mutationFn: () => api.post<{ import_id: string }>("/api/system/reprocess") });
  if (d.isLoading) return <Loading />;
  const x = d.data;
  return (
    <div className="stack">
      <ErrorBox error={d.error} />
      {x && (
        <div className="grid cols-2">
          <div>
            <h3>System</h3>
            <table className="table small">
              <tbody>
                <tr><td>Version</td><td>{x.version}</td></tr>
                <tr><td>Python</td><td>{x.python}</td></tr>
                <tr><td>Plattform</td><td>{x.platform}</td></tr>
                <tr><td>Datenbank</td><td className="mono">{x.database}</td></tr>
                {Object.entries(x.libraries).map(([k, v]) => (<tr key={k}><td>{k}</td><td>{v}</td></tr>))}
                <tr><td>Parser</td><td>{x.parsers.map((p) => `${p.manufacturer} ${p.version}`).join(", ")}</td></tr>
                <tr><td>Import-Worker</td><td>{x.worker.current ? `aktiv (${x.worker.current.slice(0, 8)})` : "bereit"} · Warteschlange {x.worker.queued}</td></tr>
              </tbody>
            </table>
          </div>
          <div>
            <h3>Speicher</h3>
            <table className="table small">
              <tbody>
                <tr><td>Originaldaten (Archiv)</td><td className="num">{bytes(x.storage.raw_bytes)}</td></tr>
                <tr><td>Signaldaten</td><td className="num">{bytes(x.storage.signals_bytes)}</td></tr>
                <tr><td>Staging</td><td className="num">{bytes(x.storage.staging_bytes)}</td></tr>
                <tr><td>Freier Speicher</td><td className="num">{bytes(x.storage.disk_free_bytes)}</td></tr>
                {Object.entries(x.counts).map(([k, v]) => (<tr key={k}><td>{k}</td><td className="num">{v}</td></tr>))}
                {Object.entries(x.paths).map(([k, v]) => (<tr key={k}><td>{k}</td><td className="mono">{v ?? "–"}</td></tr>))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <div>
        <h3>Backups</h3>
        <div className="row">
          <button className="primary" onClick={() => mk.mutate(true)} disabled={mk.isPending}>
            {mk.isPending ? "Erstelle …" : "Backup erstellen (vollständig)"}
          </button>
          <button onClick={() => mk.mutate(false)} disabled={mk.isPending}>
            Backup ohne Originaldaten
          </button>
        </div>
        <ErrorBox error={mk.error} />
        <table className="table small" style={{ marginTop: "0.5rem" }}>
          <tbody>
            {b.data?.map((f) => (
              <tr key={f.name}>
                <td className="mono">{f.name}</td>
                <td className="num">{bytes(f.size)}</td>
                <td>{dateTimeDe(f.created)}</td>
                <td>
                  <a href={`/api/system/backups/${encodeURIComponent(f.name)}`}>Download</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted small">Wiederherstellung per Kommandozeile: <code>sudo /opt/sleepy/scripts/restore.sh &lt;Backupdatei&gt;</code></p>
      </div>
      <div>
        <h3>Neuberechnung</h3>
        <p className="muted small">Berechnet alle Nächte aus den archivierten Originaldateien neu (z. B. nach einem Parser-Update). Originaldaten bleiben unverändert.</p>
        <button onClick={() => re.mutate()} disabled={re.isPending}>
          Alle Nächte neu berechnen
        </button>
        {re.isSuccess && <span className="small muted"> gestartet – Fortschritt im Import-Verlauf</span>}
      </div>
      <details>
        <summary>Protokoll (letzte Zeilen)</summary>
        <div className="log">{x?.log_tail.map((l, i) => <div key={i} className={l.includes("ERROR") ? "error" : l.includes("WARNING") ? "warning" : ""}>{l}</div>)}</div>
      </details>
      <details>
        <summary>Audit-Log</summary>
        <table className="table small">
          <tbody>
            {audit.data?.map((a) => (
              <tr key={a.id}>
                <td>{dateTimeDe(a.created_at)}</td>
                <td>{a.username}</td>
                <td>{a.action}</td>
                <td className="mono">{a.ip}</td>
                <td className="mono">{JSON.stringify(a.detail)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
      <p className="small">
        <a href="/api/docs" target="_blank" rel="noreferrer">API-Dokumentation (OpenAPI/Swagger)</a>
      </p>
    </div>
  );
}


const CSS_VARS: [string, string][] = [
  ["--bg", "Seitenhintergrund"],
  ["--surface", "Karten/Flächen"],
  ["--surface-2", "Kennzahl-Kacheln, Tabellen-Hover"],
  ["--border", "Rahmenlinien"],
  ["--text", "Schriftfarbe"],
  ["--muted", "Gedämpfte Schrift"],
  ["--primary", "Akzentfarbe (Buttons, Links)"],
  ["--primary-soft", "heller Akzent (aktive Navigation)"],
  ["--st-green / --st-yellow / --st-red", "Ampelfarben"],
  ["--radius", "Eckenradius"],
  ["--sidebar", "Breite der Navigation"],
];

const EXAMPLES: [string, string][] = [
  ["Akzent Grün", ":root, :root[data-theme=\"dark\"] {\n  --primary: #16a34a;\n  --primary-soft: rgba(22, 163, 74, 0.15);\n}\n"],
  ["Dunkel: echtes Schwarz (OLED)", ":root[data-theme=\"dark\"] {\n  --bg: #000;\n  --surface: #0a0a0a;\n  --surface-2: #141414;\n  --border: #262626;\n}\n"],
  ["Größere Schrift", ":root {\n  font-size: 17px;\n}\n"],
  ["Kompakter, eckiger", ":root {\n  --radius: 4px;\n}\n.card { padding: 0.75rem; }\n.content { max-width: none; }\n"],
];

function CssEditor({ value, onSave, label }: { value: string; onSave: (css: string) => Promise<unknown>; label: string }) {
  const [css, setCss] = useState(value);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => setCss(value), [value]);
  async function save(next = css) {
    setErr(null);
    setMsg("");
    try {
      await onSave(next);
      reloadCustomCss();
      setMsg("Gespeichert und angewendet.");
    } catch (e) {
      setErr(e);
    }
  }
  return (
    <div className="stack" style={{ gap: "0.5rem" }}>
      <textarea className="code" rows={12} spellCheck={false} value={css} onChange={(e) => setCss(e.target.value)} aria-label={label}
        placeholder={":root {\n  --primary: #16a34a;\n}"} />
      <div className="row">
        <button className="primary" onClick={() => save()}>Speichern & anwenden</button>
        <label className="btn">
          CSS-Datei laden…
          <input type="file" accept=".css,text/css" hidden onChange={async (e) => { const f = e.target.files?.[0]; if (f) setCss(await f.text()); }} />
        </label>
        <button onClick={() => { const b = new Blob([css], { type: "text/css" }); const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = "sleepy-custom.css"; a.click(); }}>
          Herunterladen
        </button>
        <button className="danger" onClick={() => { setCss(""); save(""); }}>Zurücksetzen</button>
        {msg && <span className="small muted">{msg}</span>}
      </div>
      <ErrorBox error={err} />
      <div className="row small">
        <span className="muted">Beispiele einfügen:</span>
        {EXAMPLES.map(([n, c]) => <button key={n} className="small" onClick={() => setCss((css ? css + "\n" : "") + c)}>{n}</button>)}
      </div>
    </div>
  );
}

function AppearanceTab() {
  const { user } = useAuth();
  const { mode, setMode } = useTheme();
  const q = useQuery({ queryKey: ["appearance"], queryFn: () => api.get<{ user_css: string; global_css: string }>("/api/appearance") });
  return (
    <div className="stack">
      <Card title="Farbschema">
        <div className="btn-group">
          {([["system", "Wie System"], ["light", "Hell"], ["dark", "Dunkel"]] as const).map(([k, l]) => (
            <button key={k} className={mode === k ? "active" : ""} onClick={() => setMode(k)}>{l}</button>
          ))}
        </div>
        <p className="muted small">Umschalten geht auch jederzeit über das Mond-/Sonnen-Symbol oben rechts. Die Wahl wird in diesem Browser gespeichert.</p>
      </Card>
      <Card title="Eigenes CSS (nur für dich)">
        <p className="muted small" style={{ marginTop: 0 }}>
          Eigene Stylesheet-Regeln werden nach dem Standard-Design geladen und überschreiben es. Am einfachsten über die Farbvariablen.
          Externe Ressourcen (Schriften, Bilder von anderen Servern) werden aus Datenschutzgründen durch die Content-Security-Policy blockiert.
        </p>
        {q.data && <CssEditor label="Eigenes CSS" value={q.data.user_css} onSave={(css) => api.put("/api/appearance/user", { css })} />}
      </Card>
      {user?.role === "admin" && (
        <Card title="Globales CSS (alle Benutzer, auch Anmeldeseite)">
          {q.data && <CssEditor label="Globales CSS" value={q.data.global_css} onSave={(css) => api.put("/api/appearance/global", { css })} />}
        </Card>
      )}
      <Card title="Verfügbare Variablen">
        <table className="table small">
          <tbody>
            {CSS_VARS.map(([v, d]) => <tr key={v}><td className="mono">{v}</td><td>{d}</td></tr>)}
          </tbody>
        </table>
        <p className="muted small">Hell-/Dunkel-spezifische Regeln: <code>:root[data-theme="dark"] {"{ … }"}</code> bzw. <code>:root[data-theme="light"]</code>. Wichtige Klassen: <code>.card</code>, <code>.kpi</code>, <code>.sidebar</code>, <code>.topbar</code>, <code>.table</code>, <code>.chart-panel</code>.</p>
      </Card>
    </div>
  );
}

export default function Settings() {
  const { user } = useAuth();
  const [tab, setTab] = useState("profile");
  useEffect(() => {
    if (tab === "admin" && user?.role !== "admin") setTab("profile");
  }, [tab, user]);
  return (
    <div className="stack">
      <div className="tabs">
        <button className={tab === "profile" ? "active" : ""} onClick={() => setTab("profile")}>Profil & Sicherheit</button>
        <button className={tab === "appearance" ? "active" : ""} onClick={() => setTab("appearance")}>Darstellung</button>
        <button className={tab === "thresholds" ? "active" : ""} onClick={() => setTab("thresholds")}>Schwellenwerte</button>
        {user?.role === "admin" && <button className={tab === "users" ? "active" : ""} onClick={() => setTab("users")}>Benutzer</button>}
        {user?.role === "admin" && <button className={tab === "admin" ? "active" : ""} onClick={() => setTab("admin")}>System</button>}
      </div>
      {tab === "profile" && (
        <div className="grid cols-2">
          <Card title="Passwort ändern"><PasswordForm /></Card>
          <Card title="Zwei-Faktor-Authentifizierung"><TotpSection /></Card>
        </div>
      )}
      {tab === "appearance" && <AppearanceTab />}
      {tab === "thresholds" && <Card title="Schwellenwerte für die Statusanzeige"><ThresholdForm /></Card>}
      {tab === "users" && <Card title="Benutzerverwaltung"><UsersAdmin /></Card>}
      {tab === "admin" && <Card title="System, Backup & Diagnose"><SystemAdmin /></Card>}
    </div>
  );
}
