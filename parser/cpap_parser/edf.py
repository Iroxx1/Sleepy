"""Minimal, dependency-light EDF / EDF+ reader.

Implements the European Data Format as specified at https://www.edfplus.info/
(EDF: Kemp et al. 1992, EDF+: Kemp & Olivan 2003).  Only reading is needed for
CPAP data; a small writer lives in :mod:`cpap_parser.edf_writer` for tests.

Design notes
------------
* Samples are kept as the original 16-bit *digital* values together with the
  linear scaling (gain/offset) to physical units.  This is loss-free and halves
  the storage footprint compared to float32.
* EDF start date/time has no time zone.  CPAP devices write the device's local
  wall-clock time.  We therefore return a *naive* :class:`datetime`.
* ``.edf.gz`` files are transparently decompressed.
"""

from __future__ import annotations

import gzip
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np

HEADER_SIZE = 256
SIGNAL_HEADER_SIZE = 256

TAL_SEP = 0x14  # separates TAL fields
TAL_DUR = 0x15  # precedes duration
TAL_END = 0x00  # terminates a TAL


class EDFError(Exception):
    """Raised for files that are not (valid) EDF files."""


@dataclass
class EDFSignal:
    index: int
    label: str
    transducer: str
    dimension: str
    physical_min: float
    physical_max: float
    digital_min: int
    digital_max: int
    prefilter: str
    samples_per_record: int
    reserved: str
    #: digital (raw int16) samples, all records concatenated
    digital: np.ndarray | None = None

    @property
    def is_annotation(self) -> bool:
        return self.label.strip() in ("EDF Annotations", "BDF Annotations")

    @property
    def gain(self) -> float:
        dd = self.digital_max - self.digital_min
        if dd == 0:
            return 1.0
        return (self.physical_max - self.physical_min) / dd

    @property
    def offset(self) -> float:
        return self.physical_max - self.gain * self.digital_max

    def physical(self) -> np.ndarray:
        if self.digital is None:
            raise EDFError(f"signal {self.label!r} has no data loaded")
        return self.digital.astype(np.float64) * self.gain + self.offset


@dataclass
class EDFAnnotation:
    onset: float  # seconds relative to file start
    duration: float | None  # seconds, None if not given
    text: str
    record: int


@dataclass
class EDFFile:
    path: str
    version: str
    patient: str
    recording: str
    start: datetime  # naive, device local time
    header_bytes: int
    reserved: str
    n_records: int
    record_duration: float
    signals: list[EDFSignal]
    annotations: list[EDFAnnotation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: True if the file contained fewer data bytes than announced in the header
    truncated: bool = False

    @property
    def is_edfplus(self) -> bool:
        return self.reserved.startswith("EDF+")

    @property
    def is_discontinuous(self) -> bool:
        return self.reserved.startswith("EDF+D")

    @property
    def duration_seconds(self) -> float:
        return self.n_records * self.record_duration

    @property
    def end(self) -> datetime:
        return self.start + timedelta(seconds=self.duration_seconds)

    def signal(self, label: str) -> EDFSignal | None:
        for s in self.signals:
            if s.label == label:
                return s
        return None

    def data_signals(self) -> list[EDFSignal]:
        return [s for s in self.signals if not s.is_annotation]

    def sample_rate(self, sig: EDFSignal) -> float:
        if self.record_duration <= 0:
            return 0.0
        return sig.samples_per_record / self.record_duration


def _ascii(b: bytes) -> str:
    return b.decode("latin-1").strip()


def _num(b: bytes, what: str, cast=float):
    s = _ascii(b)
    try:
        return cast(s)
    except ValueError:
        # EDF allows e.g. "1.0" for integer fields in the wild; be lenient.
        try:
            return cast(float(s))
        except ValueError as exc:
            raise EDFError(f"invalid number for {what}: {s!r}") from exc


_DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2})$")
_TIME_RE = re.compile(r"^(\d{2})[.:](\d{2})[.:](\d{2})$")


def parse_edf_datetime(date_s: str, time_s: str) -> datetime:
    """Parse the EDF ``dd.mm.yy`` / ``hh.mm.ss`` fields.

    EDF spec: years 85-99 are 1985-1999, 00-84 are 2000-2084.
    """
    dm = _DATE_RE.match(date_s.strip())
    tm = _TIME_RE.match(time_s.strip())
    if not dm or not tm:
        raise EDFError(f"invalid EDF start date/time: {date_s!r} {time_s!r}")
    dd, mm, yy = (int(x) for x in dm.groups())
    year = 1900 + yy if yy >= 85 else 2000 + yy
    hh, mi, ss = (int(x) for x in tm.groups())
    try:
        return datetime.combine(date(year, mm, dd), time(hh, mi, ss))
    except ValueError as exc:
        raise EDFError(f"invalid EDF start date/time: {date_s!r} {time_s!r}") from exc


def _read_bytes(path: str | Path) -> bytes:
    p = Path(path)
    with open(p, "rb") as fh:
        head = fh.read(2)
        fh.seek(0)
        if head == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=fh) as gz:
                return gz.read()
        return fh.read()


def read_header_bytes(path: str | Path, limit: int = 256 * 512) -> bytes:
    """Read only the beginning of a file (header), handling gzip."""
    p = Path(path)
    with open(p, "rb") as fh:
        head = fh.read(2)
        fh.seek(0)
        if head == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=fh) as gz:
                return gz.read(limit)
        return fh.read(limit)


def _parse_header(raw: bytes, path: str, versions: tuple[str, ...] = ("0",)) -> tuple[EDFFile, int]:
    if len(raw) < HEADER_SIZE:
        raise EDFError("file too short for an EDF header")
    h = raw[:HEADER_SIZE]
    version = _ascii(h[0:8])
    if version not in versions:
        raise EDFError(f"unsupported EDF version field {version!r}")
    patient = _ascii(h[8:88])
    recording = _ascii(h[88:168])
    start = parse_edf_datetime(_ascii(h[168:176]), _ascii(h[176:184]))
    header_bytes = _num(h[184:192], "header bytes", int)
    reserved = _ascii(h[192:236])
    n_records = _num(h[236:244], "number of records", int)
    record_duration = _num(h[244:252], "record duration", float)
    ns = _num(h[252:256], "number of signals", int)
    if ns <= 0 or ns > 4096:
        raise EDFError(f"implausible number of signals: {ns}")
    expected_header = HEADER_SIZE + ns * SIGNAL_HEADER_SIZE
    if len(raw) < expected_header:
        raise EDFError("file too short for the announced signal headers")
    if header_bytes != expected_header:
        # Some writers get this wrong; the signal count is authoritative.
        header_bytes = expected_header

    sh = raw[HEADER_SIZE:expected_header]

    # Signal header fields are stored column-wise: all labels, then all
    # transducers, ... Each column is ns * width bytes.
    widths = [16, 80, 8, 8, 8, 8, 8, 80, 8, 32]
    starts = []
    acc = 0
    for w in widths:
        starts.append(acc)
        acc += w * ns

    def col(idx: int) -> list[bytes]:
        w = widths[idx]
        base = starts[idx]
        return [sh[base + i * w: base + (i + 1) * w] for i in range(ns)]

    labels = col(0)
    transducers = col(1)
    dims = col(2)
    pmins = col(3)
    pmaxs = col(4)
    dmins = col(5)
    dmaxs = col(6)
    prefilters = col(7)
    spr = col(8)
    reserveds = col(9)

    signals: list[EDFSignal] = []
    for i in range(ns):
        signals.append(
            EDFSignal(
                index=i,
                label=_ascii(labels[i]),
                transducer=_ascii(transducers[i]),
                dimension=_ascii(dims[i]),
                physical_min=_num(pmins[i], "physical min"),
                physical_max=_num(pmaxs[i], "physical max"),
                digital_min=_num(dmins[i], "digital min", int),
                digital_max=_num(dmaxs[i], "digital max", int),
                prefilter=_ascii(prefilters[i]),
                samples_per_record=_num(spr[i], "samples per record", int),
                reserved=_ascii(reserveds[i]),
            )
        )
    edf = EDFFile(
        path=str(path),
        version=version,
        patient=patient,
        recording=recording,
        start=start,
        header_bytes=header_bytes,
        reserved=reserved,
        n_records=n_records,
        record_duration=record_duration,
        signals=signals,
    )
    return edf, header_bytes


def read_edf_header(path: str | Path) -> EDFFile:
    """Read only the header (fast; no sample data)."""
    raw = read_header_bytes(path)
    edf, _ = _parse_header(raw, str(path))
    if edf.n_records < 0:
        # unknown record count -> need the file size
        full = _read_bytes(path)
        rec_bytes = sum(s.samples_per_record for s in edf.signals) * 2
        edf.n_records = (len(full) - edf.header_bytes) // rec_bytes if rec_bytes else 0
    return edf


def read_edf(path: str | Path, read_annotations: bool = True) -> EDFFile:
    """Read a complete EDF/EDF+ file including sample data and annotations."""
    raw = _read_bytes(path)
    edf, hb = _parse_header(raw, str(path))
    spr = [s.samples_per_record for s in edf.signals]
    rec_samples = sum(spr)
    if rec_samples <= 0:
        raise EDFError("record without samples")
    rec_bytes = rec_samples * 2
    data = raw[hb:]
    available = len(data) // rec_bytes
    n = edf.n_records
    if n < 0:
        n = available
    if available < n:
        edf.warnings.append(
            f"file truncated: header announces {n} records, only {available} present"
        )
        edf.truncated = True
        n = available
    elif len(data) > n * rec_bytes and len(data) - n * rec_bytes >= rec_bytes:
        edf.warnings.append(
            f"file contains {available - n} more records than announced; extra data ignored"
        )
    edf.n_records = n
    if n == 0:
        for s in edf.signals:
            s.digital = np.zeros(0, dtype=np.int16)
        return edf

    arr = np.frombuffer(data, dtype="<i2", count=n * rec_samples).reshape(n, rec_samples)
    pos = 0
    for s in edf.signals:
        block = arr[:, pos: pos + s.samples_per_record]
        pos += s.samples_per_record
        if s.is_annotation:
            if read_annotations:
                raw_bytes = np.ascontiguousarray(block).tobytes()
                per = s.samples_per_record * 2
                for r in range(n):
                    edf.annotations.extend(
                        parse_tal(raw_bytes[r * per: (r + 1) * per], record=r)
                    )
            s.digital = None
        else:
            s.digital = np.ascontiguousarray(block).reshape(-1).copy()
    return edf


def parse_tal(buf: bytes, record: int = 0) -> list[EDFAnnotation]:
    """Parse the Time-stamped Annotation Lists (TALs) of one data record.

    Format: ``+Onset[\\x15Duration]\\x14Text\\x14[Text\\x14...]\\x00``.
    TALs with only empty text are time-keeping annotations and are skipped.
    """
    out: list[EDFAnnotation] = []
    for tal in buf.split(bytes([TAL_END])):
        if not tal:
            continue
        parts = tal.split(bytes([TAL_SEP]))
        if len(parts) < 2:
            continue
        head = parts[0]
        if not head or head[0:1] not in (b"+", b"-"):
            continue
        if bytes([TAL_DUR]) in head:
            on_b, dur_b = head.split(bytes([TAL_DUR]), 1)
        else:
            on_b, dur_b = head, b""
        try:
            onset = float(on_b.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            continue
        duration: float | None = None
        if dur_b:
            try:
                duration = float(dur_b.decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                duration = None
        for txt in parts[1:]:
            if not txt:
                continue
            text = txt.decode("utf-8", errors="replace").strip()
            if text:
                out.append(EDFAnnotation(onset=onset, duration=duration, text=text, record=record))
    return out
