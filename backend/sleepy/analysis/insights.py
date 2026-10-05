"""Statistical observations for a night (clusters, context, anomalies, text).

IMPORTANT: Output is limited to *statistical, technical* statements about the
recorded data.  No diagnoses, no therapy recommendations.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from cpap_parser.channels import AHI_EVENTS, EVENTS

from .stats import robust_z
from .timeseries import ChannelCache

DISCLAIMER = (
    "Die dargestellten Informationen dienen ausschließlich der technischen Analyse der "
    "PAP-Therapiedaten und ersetzen keine ärztliche Beratung."
)


@dataclass
class Ev:
    code: str
    start_ms: int
    end_ms: int
    duration_s: float | None


def fmt(v: float | None, dec: int = 1) -> str:
    if v is None:
        return "–"
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def hhmm(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%H:%M")


def duration_hm(hours: float) -> str:
    total_min = int(round(hours * 60))
    return f"{total_min // 60}:{total_min % 60:02d} h"


# ------------------------------------------------------------------ clusters
def find_clusters(events: Sequence[Ev], codes: Sequence[str] | None = None, gap_s: float = 300, min_events: int = 3):
    """Groups of >= min_events events whose consecutive gaps are <= gap_s."""
    codes = list(codes or (list(AHI_EVENTS) + ["RERA"]))
    evs = sorted((e for e in events if e.code in codes), key=lambda e: e.start_ms)
    clusters = []
    cur: list[Ev] = []
    for e in evs:
        if cur and (e.start_ms - cur[-1].end_ms) / 1000.0 > gap_s:
            if len(cur) >= min_events:
                clusters.append(cur)
            cur = []
        cur.append(e)
    if len(cur) >= min_events:
        clusters.append(cur)
    out = []
    for c in clusters:
        start = c[0].start_ms
        end = max(e.end_ms for e in c)
        dur_h = max((end - start) / 3600000.0, 1 / 60)
        out.append(
            {
                "start_ms": start,
                "end_ms": end,
                "count": len(c),
                "by_code": dict(Counter(e.code for e in c)),
                "rate_per_hour": len(c) / dur_h,
            }
        )
    out.sort(key=lambda x: -x["count"])
    return out


def hourly_counts(events: Sequence[Ev], start_ms: int | None, end_ms: int | None):
    if start_ms is None or end_ms is None:
        return []
    h0 = start_ms - start_ms % 3600000
    buckets = []
    t = h0
    while t < end_ms:
        buckets.append({"start_ms": t, "counts": {}})
        t += 3600000
    for e in events:
        i = int((e.start_ms - h0) // 3600000)
        if 0 <= i < len(buckets):
            c = buckets[i]["counts"]
            c[e.code] = c.get(e.code, 0) + 1
    return buckets


# ------------------------------------------------------------- peri-event
PERI_CHANNELS = ["pressure", "epap", "leak", "flow_limit", "snore", "resp_rate", "tidal_volume", "spo2", "pulse"]


def peri_event(cache: ChannelCache, events: Sequence[Ev], before_s: int = 180, after_s: int = 180, step_s: int = 2):
    """Event-triggered average of low-rate channels aligned at event start."""
    evs = [e for e in events if e.code in AHI_EVENTS]
    if len(evs) < 3:
        return {}
    offsets = np.arange(-before_s, after_s + step_s, step_s)
    out = {}
    for ch in PERI_CHANNELS:
        if not cache.has(ch):
            continue
        t, v = cache.arrays(ch)
        if t.size < 10:
            continue
        rows = []
        for e in evs:
            grid = e.start_ms + offsets * 1000.0
            if grid[0] < t[0] or grid[-1] > t[-1]:
                continue
            rows.append(np.interp(grid, t, v, left=np.nan, right=np.nan))
        if len(rows) < 3:
            continue
        mat = np.vstack(rows)
        mean = np.nanmean(mat, axis=0)
        out[ch] = {
            "offsets_s": offsets.tolist(),
            "mean": [None if not np.isfinite(x) else round(float(x), 3) for x in mean],
            "n_events": len(rows),
            "night_median": float(np.nanmedian(v)),
        }
    return out


# ------------------------------------------------------------ observations
def observations(
    events: Sequence[Ev],
    cache: ChannelCache,
    leak_threshold: float,
    start_ms: int | None,
    end_ms: int | None,
) -> list[dict]:
    obs: list[dict] = []
    ahi_evs = [e for e in events if e.code in AHI_EVENTS]
    clusters = find_clusters(events)
    for c in clusters[:3]:
        parts = ", ".join(f"{n}× {EVENTS[k].short if k in EVENTS else k}" for k, n in sorted(c["by_code"].items()))
        obs.append(
            {
                "kind": "cluster",
                "start_ms": c["start_ms"],
                "end_ms": c["end_ms"],
                "text": f"Zwischen {hhmm(c['start_ms'])} und {hhmm(c['end_ms'])} traten {c['count']} Ereignisse "
                f"gehäuft auf ({parts}).",
            }
        )
    hours = hourly_counts(ahi_evs, start_ms, end_ms)
    if hours and len(ahi_evs) >= 3:
        best = max(hours, key=lambda b: sum(b["counts"].values()))
        n = sum(best["counts"].values())
        if n >= 2:
            obs.append(
                {
                    "kind": "peak_hour",
                    "start_ms": best["start_ms"],
                    "end_ms": best["start_ms"] + 3600000,
                    "text": f"Die meisten Apnoen/Hypopnoen ({n}) fielen in den Zeitraum "
                    f"{hhmm(best['start_ms'])}–{hhmm(best['start_ms'] + 3600000)} Uhr.",
                }
            )
    if len(ahi_evs) >= 3 and cache.has("leak"):
        t, v = cache.arrays("leak")
        finite = v[np.isfinite(v)]
        if finite.size:
            time_share = float((finite > leak_threshold).mean()) * 100
            during = []
            for e in ahi_evs:
                m = cache.mean_between("leak", e.start_ms - 60000, e.end_ms)
                if m is not None:
                    during.append(m > leak_threshold)
            if during:
                ev_share = 100.0 * sum(during) / len(during)
                if ev_share >= 20 and ev_share > 2 * time_share:
                    obs.append(
                        {
                            "kind": "leak_relation",
                            "text": f"{fmt(ev_share, 0)} % der Ereignisse traten bei Leckage über "
                            f"{fmt(leak_threshold, 0)} L/min auf, obwohl dieser Leckagebereich nur "
                            f"{fmt(time_share, 1)} % der Nacht ausmachte (statistische Beobachtung).",
                        }
                    )
    if len(ahi_evs) >= 3 and cache.has("pressure"):
        rises = []
        for e in ahi_evs:
            if e.code not in ("OA", "H"):
                continue
            before = cache.mean_between("pressure", e.start_ms - 60000, e.start_ms)
            after = cache.mean_between("pressure", e.end_ms + 120000, e.end_ms + 300000)
            if before is not None and after is not None:
                rises.append(after - before)
        if len(rises) >= 3:
            r = float(np.mean(rises))
            if abs(r) >= 0.2:
                obs.append(
                    {
                        "kind": "pressure_response",
                        "text": f"Nach obstruktiven Apnoen/Hypopnoen lag der Druck 2–5 Minuten später im Mittel "
                        f"{fmt(abs(r), 1)} cmH2O {'höher' if r > 0 else 'niedriger'} als in der Minute davor.",
                    }
                )
    if len(ahi_evs) >= 3 and cache.has("flow_limit"):
        t, v = cache.arrays("flow_limit")
        night = float(np.nanmean(v)) if v.size else None
        pre = [cache.mean_between("flow_limit", e.start_ms - 120000, e.start_ms) for e in ahi_evs]
        pre = [x for x in pre if x is not None]
        if night is not None and pre:
            p = float(np.mean(pre))
            if p > night * 1.5 and p - night >= 0.05:
                obs.append(
                    {
                        "kind": "flow_limit_relation",
                        "text": f"In den 2 Minuten vor Ereignissen war die Flusslimitierung im Mittel höher "
                        f"({fmt(p, 2)}) als im Nachtdurchschnitt ({fmt(night, 2)}).",
                    }
                )
    if start_ms is not None and end_ms is not None and len(ahi_evs) >= 6:
        mid = (start_ms + end_ms) / 2
        first = sum(1 for e in ahi_evs if e.start_ms < mid)
        share = 100.0 * first / len(ahi_evs)
        if share >= 70 or share <= 30:
            half = "ersten" if share >= 70 else "zweiten"
            obs.append(
                {
                    "kind": "half",
                    "text": f"{fmt(max(share, 100 - share), 0)} % der Apnoen/Hypopnoen lagen in der {half} "
                    f"Hälfte der Aufzeichnung.",
                }
            )
    return obs


# --------------------------------------------------------------- anomalies
ANOMALY_RULES = [
    # key, direction, minimal absolute difference, label
    ("ahi", "high", 2.0, "AHI"),
    ("cai", "high", 1.0, "Zentrale Apnoen (CAI)"),
    ("oai", "high", 1.0, "Obstruktive Apnoen (OAI)"),
    ("hi", "high", 1.0, "Hypopnoen (HI)"),
    ("leak.p95", "high", 5.0, "Leckage (95 %)"),
    ("leak.median", "high", 3.0, "Leckage (Median)"),
    ("pressure.p95", "both", 1.0, "Druck (95 %)"),
    ("pressure.median", "both", 1.0, "Druck (Median)"),
    ("flow_limit.p95", "high", 0.1, "Flusslimitierung (95 %)"),
    ("usage_h", "low", 1.0, "Nutzungsdauer"),
    ("resp_rate.median", "both", 2.0, "Atemfrequenz (Median)"),
    ("tidal_volume.median", "both", 60.0, "Atemzugvolumen (Median)"),
    ("minute_vent.median", "both", 1.0, "Atemminutenvolumen (Median)"),
    ("spo2.median", "low", 1.0, "SpO2 (Median)"),
    ("odi", "high", 2.0, "ODI"),
]


def anomalies(current: dict[str, float], history: dict[str, list[float]], units: dict[str, str]) -> list[dict]:
    out = []
    for key, direction, min_diff, label in ANOMALY_RULES:
        v = current.get(key)
        if v is None:
            continue
        r = robust_z(v, history.get(key, []))
        if r is None:
            continue
        z, med, _spread = r
        diff = v - med
        if abs(diff) < min_diff or abs(z) < 3:
            continue
        if direction == "high" and diff < 0:
            continue
        if direction == "low" and diff > 0:
            continue
        unit = units.get(key, "")
        word = "über" if diff > 0 else "unter"
        dec = 2 if abs(v) < 10 else 1
        if key == "usage_h":
            vs, ms = duration_hm(v), duration_hm(med)
        else:
            vs, ms = f"{fmt(v, dec)} {unit}".strip(), f"{fmt(med, dec)} {unit}".strip()
        out.append(
            {
                "key": key,
                "value": v,
                "baseline_median": med,
                "z": round(float(z), 2),
                "direction": "high" if diff > 0 else "low",
                "text": f"{label}: {vs} liegt deutlich {word} deinem persönlichen Median der letzten "
                f"{len(history.get(key, []))} Nächte ({ms}) – statistisch auffällig.",
            }
        )
    return out


# ----------------------------------------------------------- summary text
def summary_text(
    m: dict[str, float],
    baseline: dict[str, float],
    baseline_n: int,
    session_count: int,
    events: Sequence[Ev],
    leak_threshold: float,
    start_ms: int | None,
    end_ms: int | None,
) -> str:
    parts: list[str] = []
    usage = m.get("usage_h")
    if usage is not None:
        s = f"Therapiedauer {duration_hm(usage)}"
        if session_count > 1:
            s += f" in {session_count} Sitzungen"
        parts.append(s + ".")
    ahi = m.get("ahi")
    if ahi is not None:
        s = f"AHI {fmt(ahi, 1)}"
        b = baseline.get("ahi")
        if b is not None and baseline_n >= 7:
            if abs(ahi - b) < 0.3:
                s += f" und damit etwa auf dem Niveau des {baseline_n}-Nächte-Mittelwerts von {fmt(b, 1)}"
            elif ahi < b:
                s += f" und damit niedriger als der {baseline_n}-Nächte-Mittelwert von {fmt(b, 1)}"
            else:
                s += f" und damit höher als der {baseline_n}-Nächte-Mittelwert von {fmt(b, 1)}"
        parts.append(s + ".")
    lp95 = m.get("leak.p95")
    if lp95 is not None:
        if lp95 <= leak_threshold:
            parts.append(
                f"Leckage im unauffälligen Bereich (95 %-Perzentil {fmt(lp95, 1)} L/min, unter der Schwelle von "
                f"{fmt(leak_threshold, 0)} L/min)."
            )
        else:
            above = m.get("leak.time_above_pct")
            extra = f", {fmt(above, 1)} % der Zeit über der Schwelle" if above is not None else ""
            parts.append(
                f"Leckage erhöht (95 %-Perzentil {fmt(lp95, 1)} L/min über der Schwelle von "
                f"{fmt(leak_threshold, 0)} L/min{extra})."
            )
    p95 = m.get("pressure.p95")
    if p95 is not None:
        parts.append(f"Druck: Median {fmt(m.get('pressure.median'), 1)}, 95 % {fmt(p95, 1)} cmH2O.")
    ahi_evs = [e for e in events if e.code in AHI_EVENTS]
    hrs = hourly_counts(ahi_evs, start_ms, end_ms)
    if hrs and len(ahi_evs) >= 3:
        best = max(hrs, key=lambda b: sum(b["counts"].values()))
        parts.append(
            f"Die meisten Ereignisse traten zwischen {hhmm(best['start_ms'])} und "
            f"{hhmm(best['start_ms'] + 3600000)} Uhr auf."
        )
    elif not ahi_evs and ahi is not None and ahi == 0 and m.get("count.OA") is not None:
        parts.append("Es wurden keine Apnoen oder Hypopnoen aufgezeichnet.")
    if "spo2.median" in m:
        parts.append(f"SpO2 Median {fmt(m['spo2.median'], 0)} %.")
    return " ".join(parts)


# ----------------------------------------------------------------- status
DEFAULT_THRESHOLDS = {
    "ahi_yellow": 5.0,
    "ahi_red": 10.0,
    "usage_min_h": 4.0,
    "leak_p95_max": 24.0,
}


def night_status(m: dict[str, float], has_data: bool, thresholds: dict | None = None) -> str:
    """Traffic light based on user configurable thresholds (no medical rating)."""
    if not has_data:
        return "none"
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    ahi = m.get("ahi")
    if ahi is not None and ahi >= th["ahi_red"]:
        return "red"
    yellow = False
    if ahi is not None and ahi >= th["ahi_yellow"]:
        yellow = True
    usage = m.get("usage_h")
    if usage is not None and usage < th["usage_min_h"]:
        yellow = True
    leak = m.get("leak.p95")
    if leak is not None and leak > th["leak_p95_max"]:
        yellow = True
    return "yellow" if yellow else "green"
