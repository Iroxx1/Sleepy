import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, setUnauthorizedHandler } from "../api/client";
import type { User } from "../api/types";

interface AuthState {
  loading: boolean;
  user: User | null;
  mfaRequired: boolean;
  needsSetup: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
  setUser: (u: User | null) => void;
  setMfaRequired: (b: boolean) => void;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState<User | null>(null);
  const [mfaRequired, setMfaRequired] = useState(false);
  const [needsSetup, setNeedsSetup] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await api.get<{ mfa_required: boolean; user: User | null }>("/api/auth/me");
      setUser(r.user);
      setMfaRequired(r.mfa_required);
      setNeedsSetup(false);
    } catch (e) {
      setUser(null);
      setMfaRequired(false);
      if (e instanceof ApiError && e.status === 401) {
        try {
          const s = await api.get<{ needs_setup: boolean }>("/api/auth/setup-status");
          setNeedsSetup(s.needs_setup);
        } catch {
          /* ignore */
        }
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    setUnauthorizedHandler(() => {
      setUser(null);
    });
  }, [refresh]);

  const logout = useCallback(async () => {
    try {
      await api.post("/api/auth/logout");
    } finally {
      setUser(null);
      setMfaRequired(false);
    }
  }, []);

  const value = useMemo(
    () => ({ loading, user, mfaRequired, needsSetup, refresh, logout, setUser, setMfaRequired }),
    [loading, user, mfaRequired, needsSetup, refresh, logout],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const c = useContext(Ctx);
  if (!c) throw new Error("AuthProvider missing");
  return c;
}
