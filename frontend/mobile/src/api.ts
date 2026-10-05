// API access for the mobile UI.
//  * Android app (Capacitor): absolute server URL + "Authorization: Bearer" token.
//    Requests go through Capacitor's native HTTP layer (no CORS, http:// in the LAN works).
//  * Browser (served by the backend under /m/): same-origin cookie session + CSRF header.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export interface Connection {
  baseUrl: string;
  token: string | null;
  username: string | null;
}

const KEY = "sleepy-mobile-connection";

export function isNative(): boolean {
  const cap = (window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor;
  return !!cap?.isNativePlatform?.();
}

export function getConnection(): Connection {
  try {
    const c = JSON.parse(localStorage.getItem(KEY) || "null");
    if (c) return c;
  } catch {
    /* ignore */
  }
  return { baseUrl: "", token: null, username: null };
}

export function saveConnection(c: Connection) {
  try {
    localStorage.setItem(KEY, JSON.stringify(c));
  } catch {
    /* ignore */
  }
}

export function normalizeUrl(input: string): string {
  let u = input.trim().replace(/\/+$/, "");
  if (!u) return u;
  if (!/^https?:\/\//i.test(u)) u = `http://${u}`;
  return u.replace(/\/(m|api)$/i, "");
}

function csrf(): string {
  const m = document.cookie.match(/(?:^|; )sleepy_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

type Params = Record<string, string | number | boolean | null | undefined>;

function qs(params?: Params): string {
  if (!params) return "";
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}

export async function request<T>(method: string, path: string, body?: unknown, params?: Params, opts?: { baseUrl?: string; token?: string | null; timeoutMs?: number }): Promise<T> {
  const conn = getConnection();
  const native = isNative();
  const base = opts?.baseUrl ?? (native ? conn.baseUrl : "");
  const token = opts?.token !== undefined ? opts.token : conn.token;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (native && token) headers.Authorization = `Bearer ${token}`;
  if (!native && method !== "GET") headers["X-CSRF-Token"] = csrf();
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts?.timeoutMs ?? 25000);
  let r: Response;
  try {
    r = await fetch(base + path + qs(params), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: native ? "omit" : "same-origin",
      signal: ctrl.signal,
    });
  } catch {
    throw new ApiError(0, native ? `Server ${base || "(nicht eingestellt)"} nicht erreichbar.` : "Server nicht erreichbar.");
  } finally {
    clearTimeout(timer);
  }
  if (!r.ok) {
    let msg = `Fehler ${r.status}`;
    try {
      const j = await r.json();
      if (typeof j.detail === "string") msg = j.detail;
    } catch {
      /* ignore */
    }
    if (r.status === 401 && !path.startsWith("/api/auth/")) window.dispatchEvent(new Event("sleepy-unauthorized"));
    throw new ApiError(r.status, msg);
  }
  return (await r.json()) as T;
}

export const api = {
  get: <T>(path: string, params?: Params) => request<T>("GET", path, undefined, params),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
};
