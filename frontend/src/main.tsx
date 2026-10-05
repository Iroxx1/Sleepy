import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./styles.css";
import { ThemeProvider } from "./hooks/useTheme";
import { AuthProvider, useAuth } from "./hooks/useAuth";
import { DeviceProvider } from "./hooks/useDevice";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import { Loading } from "./components/ui";
import CustomStyles from "./components/CustomStyles";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const Nights = lazy(() => import("./pages/Nights"));
const NightDetail = lazy(() => import("./pages/NightDetail"));
const Calendar = lazy(() => import("./pages/Calendar"));
const Trends = lazy(() => import("./pages/Trends"));
const Compare = lazy(() => import("./pages/Compare"));
const Import = lazy(() => import("./pages/Import"));
const Devices = lazy(() => import("./pages/Devices"));
const Reports = lazy(() => import("./pages/Reports"));
const Settings = lazy(() => import("./pages/Settings"));
const NotFound = lazy(() => import("./pages/NotFound"));
const Hardware = lazy(() => import("./pages/Hardware"));
const Help = lazy(() => import("./pages/Help"));

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false } },
});

function Gate() {
  const { loading, user } = useAuth();
  if (loading) return <Loading />;
  if (!user)
    return (
      <>
        <CustomStyles loggedIn={false} />
        <Login />
      </>
    );
  return (
    <DeviceProvider>
      <CustomStyles loggedIn />
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="nights" element={<Nights />} />
            <Route path="nights/:id" element={<NightDetail />} />
            <Route path="calendar" element={<Calendar />} />
            <Route path="trends" element={<Trends />} />
            <Route path="compare" element={<Compare />} />
            <Route path="import" element={<Import />} />
            <Route path="devices" element={<Devices />} />
            <Route path="hardware" element={<Hardware />} />
            <Route path="help" element={<Help />} />
            <Route path="reports" element={<Reports />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </DeviceProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <BrowserRouter>
            <Gate />
          </BrowserRouter>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);
