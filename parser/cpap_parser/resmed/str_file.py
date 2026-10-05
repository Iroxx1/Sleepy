"""ResMed STR.edf – one EDF data record per therapy day.

Facts (from OSCAR's reverse engineering, verified in its loader):
  * The EDF start date is the first therapy day; record *i* is day start+i.
  * A therapy day runs from 12:00 to 12:00 the next day.
  * ``MaskOn``/``MaskOff`` (``Mask On``/``Mask Off`` on S9) hold up to N
    values per day: minutes since 12:00, -1 = unused.
  * ``Duration`` is the total therapy time of the day in minutes.
  * Leak values are stored in L/s, tidal volume in L.
  * Negative values denote "not available" (e.g. SpO2 without oximeter).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from ..edf import EDFFile, read_edf
from ..model import wall_ms
from .labels import (
    MODES_10,
    MODES_11,
    STR_DURATION_LABELS,
    STR_MASKEVENTS_LABELS,
    STR_MASKOFF_LABELS,
    STR_MASKON_LABELS,
    STR_METRICS,
    STR_MODE_LABELS,
    unit_conversion,
)


@dataclass
class STRRecord:
    date: date
    raw: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    mask_intervals: list[tuple[int, int]] = field(default_factory=list)
    mask_events: int | None = None
    usage_minutes: float | None = None

    @property
    def has_therapy(self) -> bool:
        return bool(self.mask_intervals) or (self.usage_minutes or 0) > 0


def _first(edf: EDFFile, labels) -> Any:
    for lab in labels:
        s = edf.signal(lab)
        if s is not None:
            return s
    return None


def _clean(v: float) -> float | int:
    if float(v).is_integer():
        return int(v)
    return round(float(v), 4)


def parse_str(path: Path, is_as11: bool = False) -> tuple[dict[date, STRRecord], list[str]]:
    edf = read_edf(path, read_annotations=False)
    warnings = list(edf.warnings)
    first_day = edf.start.date()
    records: dict[date, STRRecord] = {}
    n = edf.n_records
    if n <= 0:
        return records, warnings + ["STR.edf enthält keine Datensätze"]

    sig_values: dict[str, np.ndarray] = {}
    sig_spr: dict[str, int] = {}
    for s in edf.data_signals():
        if s.digital is None or s.label.lower() == "crc16":
            continue
        phys = s.physical().reshape(n, s.samples_per_record)
        sig_values[s.label] = phys
        sig_spr[s.label] = s.samples_per_record

    maskon = _first(edf, STR_MASKON_LABELS)
    maskoff = _first(edf, STR_MASKOFF_LABELS)
    maskev = _first(edf, STR_MASKEVENTS_LABELS)
    dur = _first(edf, STR_DURATION_LABELS)
    mode_sig = _first(edf, STR_MODE_LABELS)

    for rec in range(n):
        d = first_day + timedelta(days=rec)
        r = STRRecord(date=d)
        for label, arr in sig_values.items():
            vals = arr[rec]
            if len(vals) == 1:
                r.raw[label] = _clean(vals[0])
            else:
                r.raw[label] = [_clean(v) for v in vals]

        noon = wall_ms(datetime.combine(d, time(12, 0)))
        if maskon is not None and maskoff is not None:
            ons = sig_values[maskon.label][rec]
            offs = sig_values[maskoff.label][rec]
            for on, off in zip(ons, offs, strict=False):
                if on < 0 and off < 0:
                    continue
                if on > 24 * 60 or off > 24 * 60:
                    warnings.append(f"{d}: Maskenzeit außerhalb des Tages (on={on}, off={off}) ignoriert")
                    continue
                if on >= 0 and off >= 0:
                    if off > on:
                        r.mask_intervals.append((noon + int(on) * 60000, noon + int(off) * 60000))
                elif on >= 0 > off:
                    # still running at the end of the therapy day
                    r.mask_intervals.append((noon + int(on) * 60000, noon + 24 * 3600 * 1000))
        if maskev is not None:
            v = sig_values[maskev.label][rec][0]
            r.mask_events = int(v) if v >= 0 else None
        if dur is not None:
            v = float(sig_values[dur.label][rec][0])
            r.usage_minutes = v if v >= 0 else None
            if v >= 0:
                r.metrics["usage_h"] = round(v / 60.0, 4)

        for label, (key, kind) in STR_METRICS.items():
            if label not in sig_values:
                continue
            v = float(sig_values[label][rec][0])
            if v < 0:  # "not available"
                continue
            if kind == "leak":
                sig = edf.signal(label)
                factor, _, _ = unit_conversion("leak", sig.dimension if sig else "")
                v *= factor
            elif kind == "volume":
                sig = edf.signal(label)
                factor, _, _ = unit_conversion("tidal_volume", sig.dimension if sig else "")
                v *= factor
            r.metrics[key] = round(v, 4)

        for label in sig_values:
            if label.startswith("S.") or label in STR_MODE_LABELS or label in ("HeatedTube", "Humidifier"):
                v = sig_values[label][rec][0]
                if v < 0:
                    continue
                r.settings[label] = _clean(v)
        if mode_sig is not None:
            raw_mode = sig_values[mode_sig.label][rec][0]
            if raw_mode >= 0:
                m = int(round(raw_mode))
                table = MODES_11 if is_as11 else MODES_10
                kind, name = table.get(m, ("UNKNOWN", f"Unbekannt ({m})"))
                r.settings["mode_kind"] = kind
                r.settings["mode_name"] = name
        if r.has_therapy:
            records[d] = r
    return records, warnings


def merge_str_versions(paths: list[Path], is_as11: bool = False) -> tuple[dict[date, STRRecord], list[str]]:
    """Parse several versions (oldest first); later versions win per day."""
    merged: dict[date, STRRecord] = {}
    warnings: list[str] = []
    for p in paths:
        try:
            recs, w = parse_str(p, is_as11=is_as11)
        except Exception as exc:  # noqa: BLE001 - report and continue with others
            warnings.append(f"STR.edf ({p.name}) konnte nicht gelesen werden: {exc}")
            continue
        warnings.extend(w)
        merged.update(recs)
    return merged, warnings
