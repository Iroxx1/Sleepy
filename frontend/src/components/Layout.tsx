import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { deviceLabel, useDevice } from "../hooks/useDevice";
import { useTheme } from "../hooks/useTheme";
import { DISCLAIMER, Icon } from "./ui";

const NAV = [
  { to: "/", label: "Dashboard", icon: "dashboard", end: true },
  { to: "/nights", label: "Nächte", icon: "nights" },
  { to: "/calendar", label: "Kalender", icon: "calendar" },
  { to: "/trends", label: "Trends", icon: "trends" },
  { to: "/compare", label: "Vergleich", icon: "compare" },
  { to: "/import", label: "Import", icon: "import" },
  { to: "/devices", label: "Geräte", icon: "devices" },
  { to: "/hardware", label: "Hardware", icon: "hardware" },
  { to: "/reports", label: "Reports & Export", icon: "reports" },
  { to: "/settings", label: "Einstellungen", icon: "settings" },
  { to: "/help", label: "Hilfe & Legende", icon: "help" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const { devices, deviceId, setDeviceId } = useDevice();
  const { mode, resolved, setMode } = useTheme();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const current = NAV.find((n) => (n.end ? loc.pathname === n.to : loc.pathname.startsWith(n.to)));

  return (
    <div className="app">
      {open && <div className="backdrop" onClick={() => setOpen(false)} />}
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="brand">
          <img src="/favicon.svg" alt="" /> Sleepy
        </div>
        <nav className="nav" onClick={() => setOpen(false)}>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}>
              <Icon name={n.icon} /> {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div>
            Angemeldet als <strong>{user?.username}</strong>
          </div>
          <button className="small ghost" style={{ paddingLeft: 0 }} onClick={() => logout()}>
            Abmelden
          </button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button className="menu-btn ghost" onClick={() => setOpen(true)} aria-label="Menü">
            <Icon name="menu" />
          </button>
          <span className="title">{current?.label ?? "Sleepy"}</span>
          <span className="grow" />
          {devices.length > 1 && (
            <select
              aria-label="Gerät"
              value={deviceId ?? ""}
              onChange={(e) => setDeviceId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">Alle Geräte</option>
              {devices.map((d) => (
                <option key={d.id} value={d.id}>
                  {deviceLabel(d)}
                </option>
              ))}
            </select>
          )}
          <button
            className="ghost theme-toggle"
            onClick={() => setMode(resolved === "dark" ? "light" : "dark")}
            title={resolved === "dark" ? "Hellen Modus aktivieren" : "Dunkelmodus aktivieren"}
            aria-label="Hell/Dunkel umschalten"
          >
            <Icon name={resolved === "dark" ? "sun" : "moon"} />
          </button>
          <select aria-label="Darstellung" value={mode} onChange={(e) => setMode(e.target.value as "light" | "dark" | "system")}>
            <option value="system">System</option>
            <option value="light">Hell</option>
            <option value="dark">Dunkel</option>
          </select>
        </header>
        <main className="content">
          <Outlet />
        </main>
        <footer className="footer-disclaimer">{DISCLAIMER}</footer>
      </div>
    </div>
  );
}
