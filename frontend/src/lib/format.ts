// Formatting helpers.  Timestamps from the API are "wall-clock milliseconds":
// the device's local time encoded as if it were UTC.  Always format them in
// UTC so the time shown equals the time recorded by the device.

const nf = new Map<number, Intl.NumberFormat>();

export function num(v: number | null | undefined, decimals = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  let f = nf.get(decimals);
  if (!f) {
    f = new Intl.NumberFormat("de-DE", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    nf.set(decimals, f);
  }
  return f.format(v);
}

export function hm(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || Number.isNaN(hours)) return "–";
  const total = Math.round(hours * 60);
  return `${Math.floor(total / 60)}h ${String(total % 60).padStart(2, "0")}m`;
}

export function clock(ms: number | null | undefined, seconds = false): string {
  if (ms === null || ms === undefined) return "–";
  const d = new Date(ms);
  const h = String(d.getUTCHours()).padStart(2, "0");
  const m = String(d.getUTCMinutes()).padStart(2, "0");
  if (!seconds) return `${h}:${m}`;
  return `${h}:${m}:${String(d.getUTCSeconds()).padStart(2, "0")}`;
}

export function dateDe(iso: string | null | undefined): string {
  if (!iso) return "–";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

const WD = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];
export function weekday(iso: string): string {
  const d = new Date(iso + "T00:00:00Z");
  return WD[d.getUTCDay()];
}

export function dateTimeDe(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
}

export function bytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${num(v, i === 0 ? 0 : 1)} ${u[i]}`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "–";
  if (seconds < 60) return `${num(seconds, 0)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return `${m}:${String(s).padStart(2, "0")} min`;
  return hm(seconds / 3600);
}

export function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function addDays(iso: string, days: number): string {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  return isoDate(d);
}

export function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export const STATUS_LABEL: Record<string, string> = {
  green: "unauffällig",
  yellow: "auffällig",
  red: "viele Ereignisse",
  none: "keine Daten",
};

export function fmtMetric(v: number | null | undefined, unit: string, decimals: number): string {
  if (unit === "h") return hm(v);
  const s = num(v, decimals);
  return unit && s !== "–" ? `${s} ${unit}` : s;
}
