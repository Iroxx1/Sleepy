"""Period statistics and trends over nights."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def describe_values(values: Sequence[float]) -> dict[str, float] | None:
    v = np.asarray([x for x in values if x is not None and np.isfinite(x)], dtype=float)
    if v.size == 0:
        return None
    p5, p25, med, p75, p95 = np.percentile(v, [5, 25, 50, 75, 95])
    return {
        "n": int(v.size),
        "mean": float(v.mean()),
        "median": float(med),
        "min": float(v.min()),
        "max": float(v.max()),
        "std": float(v.std(ddof=1)) if v.size > 1 else 0.0,
        "p5": float(p5),
        "p25": float(p25),
        "p75": float(p75),
        "p95": float(p95),
    }


def linear_trend(days: Sequence[float], values: Sequence[float]) -> dict | None:
    """Least squares slope; returns slope per 30 days and a qualitative label.

    The label is purely statistical ("steigend"/"fallend"/"stabil") and is only
    given when the fit explains a meaningful part of the variance.
    """
    pairs = [(d, v) for d, v in zip(days, values, strict=False) if v is not None and np.isfinite(v)]
    if len(pairs) < 5:
        return None
    x = np.array([p[0] for p in pairs], dtype=float)
    y = np.array([p[1] for p in pairs], dtype=float)
    if np.ptp(x) == 0:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    yhat = slope * x + intercept
    ss_res = float(((y - yhat) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    span = float(np.ptp(x))
    change = slope * span
    scale = max(abs(float(np.median(y))), float(np.std(y)), 1e-9)
    if r2 >= 0.1 and abs(change) >= 0.15 * scale:
        direction = "steigend" if slope > 0 else "fallend"
    else:
        direction = "stabil"
    return {
        "slope_per_30d": float(slope * 30),
        "change_over_period": float(change),
        "r2": float(r2),
        "direction": direction,
    }


def rolling_mean(values: Sequence[float | None], window: int = 7) -> list[float | None]:
    out: list[float | None] = []
    buf: list[float] = []
    vals = list(values)
    for i in range(len(vals)):
        lo = max(0, i - window + 1)
        buf = [v for v in vals[lo: i + 1] if v is not None]
        out.append(float(np.mean(buf)) if buf else None)
    return out


def robust_z(value: float, history: Sequence[float]) -> tuple[float, float, float] | None:
    """Robust z-score of *value* relative to *history* (median / MAD)."""
    h = np.asarray([x for x in history if x is not None and np.isfinite(x)], dtype=float)
    if h.size < 7:
        return None
    med = float(np.median(h))
    mad = float(np.median(np.abs(h - med))) * 1.4826
    spread = max(mad, float(np.std(h)) * 0.5, 1e-6)
    return (value - med) / spread, med, spread
