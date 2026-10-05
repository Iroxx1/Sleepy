import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Device } from "../api/types";

interface DeviceCtx {
  devices: Device[];
  deviceId: number | null; // null = all devices
  setDeviceId: (id: number | null) => void;
}

const Ctx = createContext<DeviceCtx>({ devices: [], deviceId: null, setDeviceId: () => {} });

export function DeviceProvider({ children }: { children: ReactNode }) {
  const { data } = useQuery({ queryKey: ["devices"], queryFn: () => api.get<Device[]>("/api/devices") });
  const [deviceId, setDeviceIdState] = useState<number | null>(() => {
    try {
      const v = localStorage.getItem("sleepy-device");
      return v ? Number(v) : null;
    } catch {
      return null;
    }
  });
  const devices = data || [];
  useEffect(() => {
    if (deviceId !== null && devices.length && !devices.some((d) => d.id === deviceId)) setDeviceIdState(null);
  }, [devices, deviceId]);
  const value = useMemo(
    () => ({
      devices,
      deviceId,
      setDeviceId: (id: number | null) => {
        setDeviceIdState(id);
        try {
          if (id === null) localStorage.removeItem("sleepy-device");
          else localStorage.setItem("sleepy-device", String(id));
        } catch {
          /* ignore */
        }
      },
    }),
    [devices, deviceId],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useDevice() {
  return useContext(Ctx);
}

export function deviceLabel(d: Device): string {
  return d.display_name || `${d.manufacturer} ${d.model ?? ""}`.trim() + ` (${d.serial})`;
}
