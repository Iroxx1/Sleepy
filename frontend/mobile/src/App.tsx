import { Suspense, lazy, useEffect } from "react";
import { NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useMobileAuth } from "./auth";
import Connect from "./pages/Connect";
import { Spinner } from "./components/ui";
import { isNative } from "./api";

const Home = lazy(() => import("./pages/Home"));
const Nights = lazy(() => import("./pages/Nights"));
const NightView = lazy(() => import("./pages/NightView"));
const Calendar = lazy(() => import("./pages/Calendar"));
const Trends = lazy(() => import("./pages/Trends"));
const More = lazy(() => import("./pages/More"));

const TABS = [
  { to: "/", label: "Übersicht", icon: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z", end: true },
  { to: "/nights", label: "Nächte", icon: "M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36A5.39 5.39 0 0 1 12.26 4.1 9.06 9.06 0 0 0 12 3z" },
  { to: "/calendar", label: "Kalender", icon: "M7 2v2H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2V2h-2v2H9V2H7zm-2 7h14v10H5V9z" },
  { to: "/trends", label: "Trends", icon: "M3 17l6-6 4 4 8-8v4h2V3h-8v2h4l-6 6-4-4-7.5 7.5L3 17z" },
  { to: "/more", label: "Mehr", icon: "M6 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm6 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm6 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4z" },
];

const TITLES: [RegExp, string][] = [
  [/^\/night\//, "Nacht"],
  [/^\/nights/, "Nächte"],
  [/^\/calendar/, "Kalender"],
  [/^\/trends/, "Trends"],
  [/^\/more/, "Mehr"],
  [/^\//, "Sleepy"],
];

function useAndroidBackButton() {
  const nav = useNavigate();
  const loc = useLocation();
  useEffect(() => {
    if (!isNative()) return;
    let remove: (() => void) | undefined;
    import("@capacitor/app").then(({ App }) => {
      App.addListener("backButton", () => {
        if (window.location.hash && window.location.hash !== "#/") nav(-1);
        else App.exitApp();
      }).then((h) => (remove = () => h.remove()));
    });
    return () => remove?.();
  }, [nav, loc]);
}

export default function App() {
  const { loading, user } = useMobileAuth();
  const loc = useLocation();
  const qc = useQueryClient();
  useAndroidBackButton();
  if (loading) return <Spinner />;
  if (!user) return <Connect />;
  const title = TITLES.find(([r]) => r.test(loc.pathname))?.[1] ?? "Sleepy";
  return (
    <div className="m-app">
      <header className="m-top">
        <img src="./favicon.svg" alt="" />
        <span className="grow">{title}</span>
        <button className="m-icon" onClick={() => qc.invalidateQueries()} aria-label="Aktualisieren">⟳</button>
      </header>
      <main className="m-main">
        <Suspense fallback={<Spinner />}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/nights" element={<Nights />} />
            <Route path="/night/:id" element={<NightView />} />
            <Route path="/calendar" element={<Calendar />} />
            <Route path="/trends" element={<Trends />} />
            <Route path="/more" element={<More />} />
            <Route path="*" element={<Home />} />
          </Routes>
        </Suspense>
      </main>
      <nav className="m-tabs">
        {TABS.map((t) => (
          <NavLink key={t.to} to={t.to} end={t.end}>
            <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true"><path d={t.icon} /></svg>
            <span>{t.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
