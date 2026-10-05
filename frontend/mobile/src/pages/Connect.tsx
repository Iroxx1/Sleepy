import { useState, type FormEvent } from "react";
import { api, getConnection, isNative, normalizeUrl, request, saveConnection } from "../api";
import { useMobileAuth } from "../auth";
import type { User } from "../../../src/api/types";
import { Disclaimer, ErrorMsg } from "../components/ui";

export default function Connect() {
  const native = isNative();
  const { setUser, mfaPending, setMfaPending } = useMobileAuth();
  const conn = getConnection();
  const [url, setUrl] = useState(conn.baseUrl || "");
  const [username, setUsername] = useState(conn.username || "");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needCode, setNeedCode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [test, setTest] = useState<string | null>(null);

  async function testConnection() {
    setError(null);
    setTest(null);
    try {
      const base = normalizeUrl(url);
      const h = await request<{ status: string; version: string }>("GET", "/api/health", undefined, undefined, { baseUrl: base, token: null, timeoutMs: 8000 });
      setTest(`Verbunden: Sleepy ${h.version} (${h.status === "ok" ? "OK" : h.status})`);
    } catch (e) {
      setError(e);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (native) {
        const base = normalizeUrl(url);
        if (!base) throw new Error("Bitte die Server-Adresse eingeben.");
        const r = await request<{ mfa_required: boolean; token: string | null; user: User | null }>(
          "POST",
          "/api/auth/app-login",
          { username, password, code: needCode ? code : null, device_name: "Android-App" },
          undefined,
          { baseUrl: base, token: null },
        );
        if (r.mfa_required) {
          setNeedCode(true);
          return;
        }
        saveConnection({ baseUrl: base, token: r.token, username });
        setUser(r.user);
      } else if (mfaPending) {
        const r = await api.post<{ user: User }>("/api/auth/totp/verify", { code });
        setMfaPending(false);
        setUser(r.user);
      } else {
        const r = await api.post<{ mfa_required: boolean; user: User | null }>("/api/auth/login", { username, password });
        if (r.mfa_required) setMfaPending(true);
        else setUser(r.user);
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const showCode = needCode || mfaPending;
  return (
    <div className="m-connect">
      <div className="m-brand">
        <img src="./favicon.svg" alt="" /> Sleepy
      </div>
      <form onSubmit={submit} className="m-form">
        {native && (
          <>
            <label>
              Server-Adresse
              <input
                inputMode="url"
                autoCapitalize="off"
                autoCorrect="off"
                placeholder="z. B. 192.168.1.50:8000 oder https://sleepy.home.lan"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                required
              />
            </label>
            <button type="button" className="m-btn" onClick={testConnection} disabled={!url}>
              Verbindung testen
            </button>
            {test && <div className="alert ok">{test}</div>}
          </>
        )}
        {!(mfaPending && !native) && (
          <>
            <label>
              Benutzername
              <input autoCapitalize="off" autoCorrect="off" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
            </label>
            <label>
              Passwort
              <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </label>
          </>
        )}
        {showCode && (
          <label>
            Code aus der Authenticator-App
            <input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} autoFocus />
          </label>
        )}
        <ErrorMsg error={error} />
        <button className="m-btn primary" type="submit" disabled={busy}>
          {busy ? "Verbinde …" : showCode ? "Bestätigen" : native ? "Verbinden & anmelden" : "Anmelden"}
        </button>
      </form>
      {native && (
        <p className="m-hint">
          Das Handy muss den Server erreichen können (gleiches WLAN oder VPN). Die Anmeldung bleibt gespeichert, bis du dich abmeldest oder sie in
          Sleepy unter Einstellungen → Verbundene Apps widerrufst.
        </p>
      )}
      <Disclaimer />
    </div>
  );
}
