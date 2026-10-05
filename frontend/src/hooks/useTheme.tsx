import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

type Mode = "light" | "dark" | "system";
interface ThemeCtx {
  mode: Mode;
  resolved: "light" | "dark";
  setMode: (m: Mode) => void;
}

const Ctx = createContext<ThemeCtx>({ mode: "system", resolved: "light", setMode: () => {} });

function systemDark() {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<Mode>(() => {
    try {
      return (localStorage.getItem("sleepy-theme") as Mode) || "system";
    } catch {
      return "system";
    }
  });
  const [sys, setSys] = useState(systemDark());
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const fn = () => setSys(mq.matches);
    mq?.addEventListener("change", fn);
    return () => mq?.removeEventListener("change", fn);
  }, []);
  const resolved: "light" | "dark" = mode === "system" ? (sys ? "dark" : "light") : mode;
  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);
  const value = useMemo(
    () => ({
      mode,
      resolved,
      setMode: (m: Mode) => {
        setModeState(m);
        try {
          localStorage.setItem("sleepy-theme", m);
        } catch {
          /* ignore */
        }
      },
    }),
    [mode, resolved],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme() {
  return useContext(Ctx);
}
