import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, getConnection, isNative, saveConnection } from "./api";
import type { User } from "../../src/api/types";

interface Ctx {
  loading: boolean;
  user: User | null;
  mfaPending: boolean;
  setUser: (u: User | null) => void;
  setMfaPending: (b: boolean) => void;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthCtx = createContext<Ctx | null>(null);

export function MobileAuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState<User | null>(null);
  const [mfaPending, setMfaPending] = useState(false);

  const refresh = useCallback(async () => {
    if (isNative() && !getConnection().token) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const r = await api.get<{ mfa_required: boolean; user: User | null }>("/api/auth/me");
      setUser(r.user);
      setMfaPending(r.mfa_required);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const onUnauth = () => setUser(null);
    window.addEventListener("sleepy-unauthorized", onUnauth);
    return () => window.removeEventListener("sleepy-unauthorized", onUnauth);
  }, [refresh]);

  const logout = useCallback(async () => {
    try {
      if (isNative()) await api.post("/api/auth/app-logout");
      else await api.post("/api/auth/logout");
    } catch {
      /* ignore – token is discarded anyway */
    }
    const c = getConnection();
    saveConnection({ ...c, token: null });
    setUser(null);
  }, []);

  const value = useMemo(() => ({ loading, user, mfaPending, setUser, setMfaPending, logout, refresh }), [loading, user, mfaPending, logout, refresh]);
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useMobileAuth() {
  const c = useContext(AuthCtx);
  if (!c) throw new Error("MobileAuthProvider missing");
  return c;
}
