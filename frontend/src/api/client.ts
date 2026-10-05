// Minimal fetch wrapper: same-origin cookies, CSRF header, German error texts.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function csrfToken(): string {
  const m = document.cookie.match(/(?:^|; )sleepy_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

type Params = Record<string, string | number | boolean | null | undefined>;

export function qs(params?: Params): string {
  if (!params) return "";
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

async function parseError(r: Response): Promise<string> {
  try {
    const j = await r.json();
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail)) return j.detail.map((d: { msg?: string }) => d.msg).join("; ");
  } catch {
    /* ignore */
  }
  if (r.status === 413) return "Datei zu groß.";
  if (r.status >= 500) return `Serverfehler (${r.status}).`;
  return `Fehler ${r.status}`;
}

export async function request<T>(method: string, url: string, body?: unknown, params?: Params): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  let payload: BodyInit | undefined;
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken();
  if (body instanceof FormData || body instanceof Blob) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let r: Response;
  try {
    r = await fetch(url + qs(params), { method, headers, body: payload, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "Server nicht erreichbar.");
  }
  if (r.status === 401 && onUnauthorized && !url.startsWith("/api/auth/")) onUnauthorized();
  if (!r.ok) throw new ApiError(r.status, await parseError(r));
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("application/json")) return (await r.json()) as T;
  return (await r.text()) as unknown as T;
}

export const api = {
  get: <T>(url: string, params?: Params) => request<T>("GET", url, undefined, params),
  post: <T>(url: string, body?: unknown, params?: Params) => request<T>("POST", url, body, params),
  put: <T>(url: string, body?: unknown, params?: Params) => request<T>("PUT", url, body, params),
  patch: <T>(url: string, body?: unknown) => request<T>("PATCH", url, body),
  del: <T>(url: string) => request<T>("DELETE", url),
};

/** Upload with progress (XMLHttpRequest, because fetch has no upload progress). */
export function uploadWithProgress(
  method: string,
  url: string,
  body: Blob | FormData,
  onProgress: (loaded: number, total: number) => void,
): { promise: Promise<unknown>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const promise = new Promise((resolve, reject) => {
    xhr.open(method, url);
    xhr.setRequestHeader("X-CSRF-Token", csrfToken());
    if (!(body instanceof FormData)) xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => onProgress(e.loaded, e.total);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          resolve(xhr.responseText);
        }
      } else {
        let msg = `Fehler ${xhr.status}`;
        try {
          msg = JSON.parse(xhr.responseText).detail || msg;
        } catch {
          /* ignore */
        }
        reject(new ApiError(xhr.status, msg));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "Verbindung abgebrochen."));
    xhr.onabort = () => reject(new ApiError(0, "Upload abgebrochen."));
    xhr.send(body);
  });
  return { promise, abort: () => xhr.abort() };
}
