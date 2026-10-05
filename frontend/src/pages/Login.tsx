import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { User } from "../api/types";
import { useAuth } from "../hooks/useAuth";
import { Disclaimer, ErrorBox } from "../components/ui";

export default function Login() {
  const { mfaRequired, needsSetup, setUser, setMfaRequired, refresh } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (needsSetup) {
        if (password !== password2) throw new Error("Passwörter stimmen nicht überein.");
        const r = await api.post<{ user: User }>("/api/auth/setup", { username, password });
        setUser(r.user);
        await refresh();
      } else if (mfaRequired) {
        const r = await api.post<{ user: User }>("/api/auth/totp/verify", { code });
        setMfaRequired(false);
        setUser(r.user);
      } else {
        const r = await api.post<{ mfa_required: boolean; user: User | null }>("/api/auth/login", { username, password });
        if (r.mfa_required) setMfaRequired(true);
        else setUser(r.user);
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="card login-card">
        <div className="brand">
          <img src="/favicon.svg" alt="" /> Sleepy
        </div>
        <form className="form" onSubmit={submit} style={{ maxWidth: "none" }}>
          {needsSetup && (
            <div className="alert info small">
              Ersteinrichtung: Lege das Administrator-Konto an. Das Passwort muss mindestens 10 Zeichen haben.
            </div>
          )}
          {mfaRequired ? (
            <label className="field">
              Code aus der Authenticator-App
              <input
                autoFocus
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                maxLength={8}
              />
            </label>
          ) : (
            <>
              <label className="field">
                Benutzername
                <input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
              </label>
              <label className="field">
                Passwort
                <input
                  type="password"
                  autoComplete={needsSetup ? "new-password" : "current-password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </label>
              {needsSetup && (
                <label className="field">
                  Passwort wiederholen
                  <input type="password" autoComplete="new-password" value={password2} onChange={(e) => setPassword2(e.target.value)} required />
                </label>
              )}
            </>
          )}
          <ErrorBox error={error} />
          <button className="primary" type="submit" disabled={busy}>
            {needsSetup ? "Konto anlegen" : mfaRequired ? "Bestätigen" : "Anmelden"}
          </button>
          {mfaRequired && (
            <button type="button" className="ghost" onClick={() => api.post("/api/auth/logout").finally(() => setMfaRequired(false))}>
              Abbrechen
            </button>
          )}
        </form>
        <div style={{ marginTop: "1rem" }}>
          <Disclaimer />
        </div>
      </div>
    </div>
  );
}
