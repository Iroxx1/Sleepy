"""Night level metrics computed from normalised data.

Everything here is a *technical* statistic of the recorded data.  No value is
invented: a metric is only produced if its input data exists.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable

import numpy as np

from cpap_parser.channels import AHI_EVENTS, CHANNELS, EVENTS
from cpap_parser.model import ParsedNight, ParsedSignal

PERCENTILES = {"p5": 5, "p25": 25, "median": 50, "p75": 75, "p95": 95}

#: index metrics for which the device's own value is shown by default
DEVICE_PREFERRED = {"ahi", "ai", "hi", "oai", "cai", "uai", "rera_index"}

METRIC_INFO: dict[str, tuple[str, str, int]] = {
    # key: (German label, unit, decimals)
    "usage_h": ("Nutzungsdauer", "h", 2),
    "ahi": ("AHI", "/h", 2),
    "ai": ("AI (Apnoe-Index)", "/h", 2),
    "hi": ("HI (Hypopnoe-Index)", "/h", 2),
    "oai": ("OAI (obstruktiv)", "/h", 2),
    "cai": ("CAI (zentral)", "/h", 2),
    "uai": ("UAI (nicht klassifiziert)", "/h", 2),
    "rera_index": ("RERA-Index", "/h", 2),
    "rdi": ("RDI", "/h", 2),
    "odi": ("ODI (≥3 %, berechnet)", "/h", 2),
    "csr_pct": ("Cheyne-Stokes-Anteil", "%", 1),
    "csr_device": ("CSR (Gerätewert, Rohwert)", "", 1),
    "leak.time_above_pct": ("Zeit über Leckage-Schwelle", "%", 1),
    "leak.time_above_s": ("Zeit über Leckage-Schwelle", "s", 0),
    "spo2.time_below_90_pct": ("Zeit mit SpO2 < 90 %", "%", 1),
    "desat_count": ("Entsättigungen (≥3 %, berechnet)", "", 0),
    "session_count": ("Sitzungen", "", 0),
}

STAT_LABELS = {
    "min": "Minimum",
    "max": "Maximum",
    "mean": "Mittelwert",
    "median": "Median",
    "p5": "5 %-Perzentil",
    "p25": "25 %-Perzentil",
    "p70": "70 %-Perzentil",
    "p75": "75 %-Perzentil",
    "p95": "95 %-Perzentil",
}


def metric_info(key: str) -> dict:
    if key in METRIC_INFO:
        label, unit, dec = METRIC_INFO[key]
        return {"key": key, "label": label, "unit": unit, "decimals": dec}
    if key.startswith("count."):
        code = key.split(".", 1)[1]
        ev = EVENTS.get(code)
        return {"key": key, "label": f"Anzahl {ev.name if ev else code}", "unit": "", "decimals": 0}
    if "." in key:
        ch, stat = key.rsplit(".", 1)
        base = {"target_ipap": ("Ziel-Druck/IPAP (Gerät)", "cmH2O"), "target_epap": ("Ziel-EPAP (Gerät)", "cmH2O")}
        if ch in CHANNELS:
            name, unit = CHANNELS[ch].name, CHANNELS[ch].unit
        elif ch in base:
            name, unit = base[ch]
        else:
            name, unit = ch, ""
        dec = 0 if unit in ("mL",) else 2 if unit in ("", "cmH2O") else 1
        return {"key": key, "label": f"{name} – {STAT_LABELS.get(stat, stat)}", "unit": unit, "decimals": dec}
    return {"key": key, "label": key, "unit": "", "decimals": 2}


def union_seconds(intervals: Iterable[tuple[int, int]]) -> float:
    iv = sorted((a, b) for a, b in intervals if b > a)
    total = 0
    cur_a = cur_b = None
    for a, b in iv:
        if cur_b is None or a > cur_b:
            if cur_b is not None:
                total += cur_b - cur_a
            cur_a, cur_b = a, b
        else:
            cur_b = max(cur_b, b)
    if cur_b is not None:
        total += cur_b - cur_a
    return total / 1000.0


def describe(values: np.ndarray) -> dict[str, float]:
    v = values[np.isfinite(values)]
    if v.size == 0:
        return {}
    out = {
        "min": float(v.min()),
        "max": float(v.max()),
        "mean": float(v.mean()),
    }
    pct = np.percentile(v, list(PERCENTILES.values()))
    for (k, _), p in zip(PERCENTILES.items(), pct, strict=False):
        out[k] = float(p)
    return out


def detect_desaturations(spo2: np.ndarray, rate: float, drop: float = 3.0, baseline_s: float = 120.0) -> list[int]:
    """Simple desaturation detector (indices of nadirs).

    Baseline = median of the preceding *baseline_s* seconds of valid samples.
    A desaturation starts when SpO2 falls >= *drop* below baseline and ends when
    it recovers to within 1 % of the baseline.  This is a simplified technical
    algorithm, not a clinically validated scoring.
    """
    if rate <= 0 or spo2.size == 0:
        return []
    win = max(1, int(baseline_s * rate))
    nadirs: list[int] = []
    i = win
    n = spo2.size
    in_desat = False
    nadir_i = -1
    base = np.nan
    while i < n:
        v = spo2[i]
        if not np.isfinite(v):
            i += 1
            in_desat = False
            continue
        if not in_desat:
            hist = spo2[i - win: i]
            hist = hist[np.isfinite(hist)]
            if hist.size < win * 0.5:
                i += 1
                continue
            base = float(np.median(hist))
            if v <= base - drop:
                in_desat = True
                nadir_i = i
        else:
            if v < spo2[nadir_i]:
                nadir_i = i
            if v >= base - 1.0:
                nadirs.append(nadir_i)
                in_desat = False
        i += 1
    if in_desat and nadir_i >= 0:
        nadirs.append(nadir_i)
    return nadirs


def channel_arrays(signals: Iterable[ParsedSignal]) -> dict[str, list[ParsedSignal]]:
    by: dict[str, list[ParsedSignal]] = defaultdict(list)
    for s in signals:
        by[s.channel].append(s)
    for v in by.values():
        v.sort(key=lambda s: s.start_ms)
    return by


def compute_night_metrics(
    parsed: ParsedNight, events_available: bool, leak_threshold: float = 24.0
) -> dict[str, float]:
    m: dict[str, float] = {}
    detail = [s for s in parsed.sessions if s.source == "detail"]
    sessions = detail or parsed.sessions
    usage_s = union_seconds((s.start_ms, s.end_ms) for s in sessions)
    if usage_s > 0:
        m["usage_h"] = usage_s / 3600.0
    m["session_count"] = float(len(sessions))
    hours = usage_s / 3600.0

    if events_available and hours > 0:
        counts = Counter(e.code for e in parsed.events)
        for code in set(AHI_EVENTS) | {"RERA"} | set(counts):
            m[f"count.{code}"] = float(counts.get(code, 0))
        ah = sum(counts.get(c, 0) for c in AHI_EVENTS)
        m["ahi"] = ah / hours
        m["ai"] = (counts.get("OA", 0) + counts.get("CA", 0) + counts.get("UA", 0)) / hours
        m["hi"] = counts.get("H", 0) / hours
        m["oai"] = counts.get("OA", 0) / hours
        m["cai"] = counts.get("CA", 0) / hours
        m["uai"] = counts.get("UA", 0) / hours
        m["rera_index"] = counts.get("RERA", 0) / hours
        m["rdi"] = (ah + counts.get("RERA", 0)) / hours
        csr = sum((e.end_ms - e.start_ms) for e in parsed.events if e.code == "CSR") / 1000.0
        m["csr_pct"] = 100.0 * csr / usage_s

    all_signals = [s for sess in parsed.sessions for s in sess.signals]
    for ch, sigs in channel_arrays(all_signals).items():
        cdef = CHANNELS.get(ch) or CHANNELS.get(re.sub(r"_\d+$", "", ch))
        if cdef is not None and not cdef.summarise:
            continue
        vals = np.concatenate([s.physical() for s in sigs]) if sigs else np.zeros(0)
        stats = describe(vals)
        for k, v in stats.items():
            m[f"{ch}.{k}"] = v
        rate = sigs[0].sample_rate if sigs else 0
        if ch == "leak" and stats and rate > 0:
            finite = vals[np.isfinite(vals)]
            above = float((finite > leak_threshold).sum()) / rate
            m["leak.time_above_s"] = above
            m["leak.time_above_pct"] = 100.0 * above / (finite.size / rate) if finite.size else 0.0
        if ch == "spo2" and stats and rate > 0:
            finite = vals[np.isfinite(vals)]
            m["spo2.time_below_90_pct"] = 100.0 * float((finite < 90).sum()) / finite.size
            desat = 0
            for s in sigs:
                desat += len(detect_desaturations(s.physical(), s.sample_rate))
            m["desat_count"] = float(desat)
            spo2_hours = finite.size / rate / 3600.0
            if spo2_hours > 0:
                m["odi"] = desat / spo2_hours
    return {k: float(v) for k, v in m.items() if v is not None and np.isfinite(v)}


def pick(metrics: dict[str, dict[str, float]], key: str) -> tuple[float | None, str | None]:
    """Choose the value to display for *key* from {'device': {...}, 'computed': {...}}."""
    dev = metrics.get("device", {})
    comp = metrics.get("computed", {})
    if key in DEVICE_PREFERRED and key in dev:
        return dev[key], "device"
    if key in comp:
        return comp[key], "computed"
    if key in dev:
        return dev[key], "device"
    return None, None
