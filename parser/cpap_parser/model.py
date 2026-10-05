"""Manufacturer independent data model produced by all parsers.

All timestamps are integer milliseconds of the *device local wall clock*
interpreted as if it were UTC ("wall-clock milliseconds").  CPAP devices do not
record a time zone, so this keeps times exactly as the device shows them and
avoids any implicit conversion.  Use :func:`wall_ms` / :func:`from_wall_ms`.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import numpy as np


def wall_ms(dt: datetime) -> int:
    """Naive local datetime -> wall-clock milliseconds."""
    return calendar.timegm(dt.timetuple()) * 1000 + dt.microsecond // 1000


def from_wall_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)


@dataclass
class DeviceInfo:
    manufacturer: str
    model: str | None = None
    product_code: str | None = None
    serial: str | None = None
    firmware: str | None = None
    series: str | None = None
    device_type: str | None = None  # CPAP, APAP, BiLevel, ASV, ...
    data_format: str | None = None
    #: raw identification key/values exactly as found on the card
    identification: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.manufacturer}:{self.serial or 'unknown'}"


@dataclass
class ParsedSignal:
    """One continuous block of samples of one channel from one source file."""

    channel: str  # canonical channel code (see channels.py) or x_<slug>
    label: str  # original label in the file
    unit: str  # unit after conversion
    sample_rate: float  # Hz
    start_ms: int
    digital: np.ndarray  # int16 digital values
    gain: float  # physical = digital * gain + offset (after unit conversion)
    offset: float
    physical_min: float
    physical_max: float
    source_file: str  # relative path of the raw file
    invalid_digital: int | None = None  # sentinel meaning "no data"
    conversion: str | None = None  # human readable note of unit conversion

    @property
    def n_samples(self) -> int:
        return int(len(self.digital))

    @property
    def end_ms(self) -> int:
        if self.sample_rate <= 0:
            return self.start_ms
        return self.start_ms + int(round(self.n_samples / self.sample_rate * 1000))

    def physical(self) -> np.ndarray:
        v = self.digital.astype(np.float64) * self.gain + self.offset
        if self.invalid_digital is not None:
            v[self.digital == self.invalid_digital] = np.nan
        return v


@dataclass
class ParsedEvent:
    code: str  # canonical event code (OA, CA, H, ...)
    label: str  # original annotation text
    onset_ms: int  # raw onset as stored in the file
    start_ms: int  # interpreted start of the event
    end_ms: int  # interpreted end of the event
    duration_s: float | None
    source_file: str


@dataclass
class ParsedSession:
    start_ms: int
    end_ms: int
    signals: list[ParsedSignal] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    source: str = "detail"  # "detail" (waveform files) or "summary" (only summary data)

    @property
    def duration_s(self) -> float:
        return max(0.0, (self.end_ms - self.start_ms) / 1000.0)


@dataclass
class ParsedNight:
    """All data belonging to one therapy day (ResMed: noon to noon)."""

    date: date
    sessions: list[ParsedSession] = field(default_factory=list)
    events: list[ParsedEvent] = field(default_factory=list)
    #: device computed summary values, canonical metric key -> value
    device_metrics: dict[str, float] = field(default_factory=dict)
    #: device settings for this day (raw label -> value) plus a few derived keys
    settings: dict[str, Any] = field(default_factory=dict)
    #: raw values of the device's daily summary record (label -> value/list)
    summary_raw: dict[str, Any] = field(default_factory=dict)
    #: mask on/off intervals from the summary file [(start_ms, end_ms), ...]
    mask_intervals: list[tuple[int, int]] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_detail(self) -> bool:
        return any(s.source == "detail" for s in self.sessions)


@dataclass
class NightPlan:
    """A night that can be parsed and the files it depends on."""

    date: date
    files: list[str]  # relative paths of detail files (waveforms/events)
    summary_files: list[str] = field(default_factory=list)  # e.g. STR.edf


@dataclass
class FileClassification:
    rel_path: str
    kind: str  # e.g. "identification", "summary", "waveform", "events", "other"
    description: str = ""
