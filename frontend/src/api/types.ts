export type Status = "green" | "yellow" | "red" | "none";

export interface User {
  id: number;
  username: string;
  role: "admin" | "user";
  totp_enabled: boolean;
  preferences: Preferences;
  created_at?: string;
  last_login_at?: string;
  csrf_token?: string;
}

export interface Thresholds {
  ahi_yellow: number;
  ahi_red: number;
  usage_min_h: number;
  leak_p95_max: number;
}

export interface Preferences {
  theme?: "light" | "dark" | "system";
  thresholds?: Partial<Thresholds>;
  default_device_id?: number | null;
  chart_channels?: string[];
}

export interface NightRow {
  id: number;
  date: string;
  device_id: number;
  start_ms: number | null;
  end_ms: number | null;
  usage_h: number | null;
  session_count: number;
  has_detail: boolean;
  has_summary: boolean;
  status: Status;
  metrics: Record<string, number>;
  notes: boolean;
}

export interface MetricDetail {
  key: string;
  label: string;
  unit: string;
  decimals: number;
  value: number | null;
  source: "device" | "computed" | null;
  device: number | null;
  computed: number | null;
}

export interface ChannelInfo {
  code: string;
  name: string;
  label: string;
  unit: string;
  group: string;
  sample_rate: number;
  min: number | null;
  max: number | null;
  conversion: string | null;
}

export interface Device {
  id: number;
  manufacturer: string;
  model: string | null;
  product_code?: string | null;
  serial: string;
  firmware?: string | null;
  series?: string | null;
  device_type: string | null;
  data_format?: string | null;
  parser?: string;
  display_name: string | null;
  identification?: Record<string, unknown>;
  first_seen_at?: string;
  last_seen_at?: string;
  nights?: number;
  first_night?: string | null;
  last_night?: string | null;
  files?: number;
  channels?: string[];
  current_settings?: Record<string, unknown>;
}

export interface NightDetail {
  night: NightRow & {
    device: Device;
    parser: string;
    parser_version: string;
    notes_text: string | null;
    warnings: string[];
    updated_at: string;
    mask_intervals: [number, number][];
  };
  metrics: MetricDetail[];
  sessions: { id: number; start_ms: number; end_ms: number; duration_s: number; source: string; files: string[] }[];
  channels: ChannelInfo[];
  event_counts: Record<string, number>;
  settings: { key: string; label: string; value: unknown }[];
  summary_raw: Record<string, unknown>;
  source_files: { rel_path: string; sha256: string | null; size: number | null; import_id: string | null; imported_at: string | null }[];
  prev_id: number | null;
  next_id: number | null;
  leak_threshold: number;
  disclaimer: string;
}

export interface EventType {
  name: string;
  short: string;
  color: string;
  span: boolean;
  ahi?: boolean;
}

export interface NightEvent {
  id: number;
  code: string;
  label: string;
  start_ms: number;
  end_ms: number;
  onset_ms: number;
  duration_s: number | null;
  session_id: number | null;
  source_file: string;
  context: Record<string, number>;
}

export interface EventsResponse {
  items: NightEvent[];
  context_channels: string[];
  types: Record<string, EventType>;
}

export interface SeriesData {
  unit: string;
  name: string;
  t: number[];
  v: (number | null)[];
  downsampled: boolean;
  rate: number;
}

export interface TimeseriesResponse {
  start: number | null;
  end: number | null;
  channels: Record<string, SeriesData>;
}

export interface Observation {
  kind: string;
  text: string;
  start_ms?: number;
  end_ms?: number;
}

export interface Anomaly {
  key: string;
  value: number;
  baseline_median: number;
  z: number;
  direction: "high" | "low";
  text: string;
}

export interface Insights {
  summary: string;
  observations: Observation[];
  clusters: { start_ms: number; end_ms: number; count: number; by_code: Record<string, number>; rate_per_hour: number }[];
  hourly: { start_ms: number; counts: Record<string, number> }[];
  anomalies: Anomaly[];
  peri_event: Record<string, { offsets_s: number[]; mean: (number | null)[]; n_events: number; night_median: number }>;
  baseline: { nights: number; ahi_mean: number | null; usage_mean: number | null; leak_p95_mean: number | null };
  n_ahi_events: number;
  disclaimer: string;
}

export interface StatEntry {
  key: string;
  label: string;
  unit: string;
  decimals: number;
  n: number;
  mean: number;
  median: number;
  min: number;
  max: number;
  std: number;
  p5: number;
  p25: number;
  p75: number;
  p95: number;
}

export interface TrendInfo {
  key: string;
  label: string;
  unit: string;
  slope_per_30d: number;
  change_over_period: number;
  r2: number;
  direction: "steigend" | "fallend" | "stabil";
}

export interface PeriodSummary {
  from: string;
  to: string;
  compliance: {
    days: number;
    nights_with_data: number;
    nights_ge_4h: number;
    pct_nights_used: number;
    pct_ge_4h: number;
    total_hours: number;
  };
  stats: Record<string, StatEntry>;
  best: { id: number; date: string; ahi: number; usage_h: number } | null;
  worst: { id: number; date: string; ahi: number; usage_h: number } | null;
  trends: Record<string, TrendInfo>;
  event_totals: Record<string, number>;
  events_by_clock_hour: Record<string, number>;
  status_counts: Record<string, number>;
  previous?: { from: string; to: string; nights: number; means: Record<string, number>; medians: Record<string, number> };
}

export interface TrendSeries {
  key: string;
  label: string;
  unit: string;
  decimals: number;
  x: string[];
  y: (number | null)[];
  rolling7?: (number | null)[];
  night_ids?: (number | null)[];
  min?: (number | null)[];
  max?: (number | null)[];
  n?: number[];
  trend?: { slope_per_30d: number; direction: string; r2: number } | null;
}

export interface ImportInfo {
  id: string;
  source: string;
  original_name: string | null;
  status: string;
  stage: string | null;
  progress: number;
  message: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  stats: Record<string, number | string>;
  uploaded_bytes: number;
  can_retry: boolean;
  log?: { t: string; level: string; text: string; file?: string }[];
  file_counts?: Record<string, number>;
  devices?: { id: number; manufacturer: string; model: string | null; serial: string }[];
}

export interface Dashboard {
  empty: boolean;
  last_night?: NightRow & { all_metrics: Record<string, number>; summary: string; anomalies: Anomaly[] };
  agg7?: Agg;
  agg30?: Agg;
  recent?: NightRow[];
  series30?: { date: string; id: number; ahi: number | null; usage_h: number | null; leak_p95: number | null; status: Status }[];
  thresholds?: Thresholds;
  disclaimer: string;
}

export interface Agg {
  days: number;
  nights: number;
  ahi_mean: number | null;
  ahi_median: number | null;
  usage_mean: number | null;
  leak_p95_mean: number | null;
  compliance_pct: number;
}
