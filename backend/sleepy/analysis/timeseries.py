"""Chart data retrieval with min/max downsampling.

For a requested time window the stored digital samples are memory mapped and,
if there are more samples than requested points, reduced with a min/max
envelope per bucket.  Peaks (e.g. leak spikes, flow extremes) are therefore
never lost, regardless of zoom level.  Zooming in returns the raw samples.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from .. import storage
from ..models import SignalSegment


def _round(v: np.ndarray, decimals: int = 3) -> list:
    out = np.round(v.astype(np.float64), decimals)
    lst = out.tolist()
    if np.isnan(out).any():
        lst = [None if (x is None or (isinstance(x, float) and math.isnan(x))) else x for x in lst]
    return lst


def segment_physical(seg: SignalSegment, i0: int = 0, i1: int | None = None) -> np.ndarray:
    arr = storage.load_signal(seg.path)
    if i1 is None:
        i1 = arr.shape[0]
    d = np.asarray(arr[i0:i1])
    v = d.astype(np.float64) * seg.gain + seg.offset
    if seg.invalid_digital is not None:
        v[d == seg.invalid_digital] = np.nan
    return v


def series(
    segments: Sequence[SignalSegment],
    start_ms: int | None,
    end_ms: int | None,
    points: int = 2000,
) -> dict:
    segs = sorted(segments, key=lambda s: s.start_ms)
    if not segs:
        return {"t": [], "v": [], "downsampled": False}
    lo = start_ms if start_ms is not None else segs[0].start_ms
    hi = end_ms if end_ms is not None else max(s.end_ms for s in segs)
    points = max(50, min(points, 20000))

    ranges = []
    total = 0
    for s in segs:
        if s.end_ms <= lo or s.start_ms >= hi or s.sample_rate <= 0:
            continue
        i0 = max(0, int(math.floor((lo - s.start_ms) * s.sample_rate / 1000.0)))
        i1 = min(s.n_samples, int(math.ceil((hi - s.start_ms) * s.sample_rate / 1000.0)) + 1)
        if i1 <= i0:
            continue
        ranges.append((s, i0, i1))
        total += i1 - i0

    t_out: list = []
    v_out: list = []
    downsampled = False
    rate = segs[0].sample_rate
    for idx, (s, i0, i1) in enumerate(ranges):
        n = i1 - i0
        budget = max(10, int(points * n / max(total, 1)))
        vals = segment_physical(s, i0, i1)
        step_ms = 1000.0 / s.sample_rate
        if n <= budget:
            t = s.start_ms + (np.arange(i0, i1) * step_ms)
            t_out.extend(np.round(t).astype(np.int64).tolist())
            v_out.extend(_round(vals))
        else:
            downsampled = True
            buckets = max(1, budget // 2)
            size = int(math.ceil(n / buckets))
            pad = size * buckets - n
            if pad:
                vals = np.concatenate([vals, np.full(pad, np.nan)])
            m = vals.reshape(buckets, size)
            all_nan = np.all(np.isnan(m), axis=1)
            safe = np.where(np.isnan(m), np.inf, m)
            amin = np.argmin(safe, axis=1)
            safe2 = np.where(np.isnan(m), -np.inf, m)
            amax = np.argmax(safe2, axis=1)
            base = i0 + np.arange(buckets) * size
            first = np.minimum(amin, amax)
            second = np.maximum(amin, amax)
            rows = np.arange(buckets)
            v1 = m[rows, first]
            v2 = m[rows, second]
            v1[all_nan] = np.nan
            v2[all_nan] = np.nan
            t1 = s.start_ms + (base + first) * step_ms
            t2 = s.start_ms + (base + second) * step_ms
            tt = np.empty(buckets * 2)
            vv = np.empty(buckets * 2)
            tt[0::2], tt[1::2] = t1, t2
            vv[0::2], vv[1::2] = v1, v2
            t_out.extend(np.round(tt).astype(np.int64).tolist())
            v_out.extend(_round(vv))
        if idx < len(ranges) - 1:
            # explicit gap between segments
            t_out.append(int(s.end_ms))
            v_out.append(None)
    return {"t": t_out, "v": v_out, "downsampled": downsampled, "rate": rate}


def value_at(segments: Sequence[SignalSegment], start_ms: int, end_ms: int) -> float | None:
    """Mean physical value within [start, end] (or nearest sample if empty)."""
    for s in segments:
        if s.end_ms < start_ms or s.start_ms > end_ms or s.sample_rate <= 0:
            continue
        i0 = max(0, int((start_ms - s.start_ms) * s.sample_rate / 1000.0))
        i1 = min(s.n_samples, max(i0 + 1, int((end_ms - s.start_ms) * s.sample_rate / 1000.0) + 1))
        v = segment_physical(s, i0, i1)
        v = v[np.isfinite(v)]
        if v.size:
            return float(v.mean())
    return None


class ChannelCache:
    """Loads complete low-rate channels of one night into memory once."""

    def __init__(self, segments: Sequence[SignalSegment]):
        self.by_channel: dict[str, list[SignalSegment]] = {}
        for s in segments:
            self.by_channel.setdefault(s.channel, []).append(s)
        self._arr: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    def has(self, ch: str) -> bool:
        return ch in self.by_channel

    def arrays(self, ch: str) -> tuple[np.ndarray, np.ndarray]:
        """(t_ms, values) concatenated over all segments of the channel."""
        if ch not in self._arr:
            ts, vs = [], []
            for s in sorted(self.by_channel.get(ch, []), key=lambda x: x.start_ms):
                v = segment_physical(s)
                t = s.start_ms + np.arange(v.size) * (1000.0 / s.sample_rate)
                ts.append(t)
                vs.append(v)
            if ts:
                self._arr[ch] = (np.concatenate(ts), np.concatenate(vs))
            else:
                self._arr[ch] = (np.zeros(0), np.zeros(0))
        return self._arr[ch]

    def mean_between(self, ch: str, a: float, b: float) -> float | None:
        t, v = self.arrays(ch)
        if t.size == 0:
            return None
        i0, i1 = np.searchsorted(t, [a, b])
        seg = v[i0: max(i1, i0 + 1)]
        seg = seg[np.isfinite(seg)]
        if seg.size == 0:
            return None
        return float(seg.mean())
