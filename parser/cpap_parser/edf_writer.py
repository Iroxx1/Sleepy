"""Small EDF / EDF+ writer.

Only used to produce *synthetic* test fixtures and demo data.  It writes files
that follow the EDF specification closely so that the reader is exercised on
realistic byte layouts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from .edf import TAL_DUR, TAL_END, TAL_SEP


@dataclass
class WSignal:
    label: str
    dimension: str
    physical_min: float
    physical_max: float
    digital_min: int
    digital_max: int
    samples_per_record: int
    #: physical values (will be quantised) OR digital values if ``is_digital``
    values: np.ndarray | None = None
    is_digital: bool = False
    transducer: str = ""
    prefilter: str = ""


@dataclass
class WAnnotation:
    onset: float
    duration: float | None
    text: str


@dataclass
class EDFSpec:
    start: datetime
    record_duration: float
    n_records: int
    signals: list[WSignal]
    patient: str = "X X X X"
    recording: str = "Startdate X X X X"
    edfplus: str = ""  # "", "EDF+C" or "EDF+D"
    annotations: list[WAnnotation] = field(default_factory=list)
    annotation_bytes_per_record: int = 0


def _f(s: str | float | int, width: int) -> bytes:
    if isinstance(s, float):
        txt = f"{s:g}"
        if len(txt) > width:
            txt = f"{s:.{max(width - 6, 1)}g}"
    else:
        txt = str(s)
    b = txt.encode("latin-1")[:width]
    return b + b" " * (width - len(b))


def _tal(onset: float, duration: float | None, texts: list[str]) -> bytes:
    sign = "+" if onset >= 0 else "-"
    head = f"{sign}{abs(onset):g}".encode()
    if duration is not None:
        head += bytes([TAL_DUR]) + f"{duration:g}".encode()
    body = head + bytes([TAL_SEP])
    for t in texts:
        body += t.encode("utf-8") + bytes([TAL_SEP])
    return body + bytes([TAL_END])


def write_edf(path: str | Path, spec: EDFSpec) -> None:
    sigs = list(spec.signals)
    ann_spr = 0
    if spec.edfplus:
        # one annotation signal at the end; size per record
        if spec.annotation_bytes_per_record:
            ann_bytes = spec.annotation_bytes_per_record
        else:
            ann_bytes = 60 + sum(len(a.text) + 30 for a in spec.annotations)
        ann_bytes += ann_bytes % 2
        ann_spr = ann_bytes // 2
    ns = len(sigs) + (1 if spec.edfplus else 0)
    header_bytes = 256 + 256 * ns

    h = b""
    h += _f("0", 8)
    h += _f(spec.patient, 80)
    h += _f(spec.recording, 80)
    h += _f(spec.start.strftime("%d.%m.%y"), 8)
    h += _f(spec.start.strftime("%H.%M.%S"), 8)
    h += _f(header_bytes, 8)
    h += _f(spec.edfplus, 44)
    h += _f(spec.n_records, 8)
    h += _f(spec.record_duration if spec.record_duration % 1 else int(spec.record_duration), 8)
    h += _f(ns, 4)

    labels = [s.label for s in sigs]
    dims = [s.dimension for s in sigs]
    pmin = [s.physical_min for s in sigs]
    pmax = [s.physical_max for s in sigs]
    dmin = [s.digital_min for s in sigs]
    dmax = [s.digital_max for s in sigs]
    spr = [s.samples_per_record for s in sigs]
    trans = [s.transducer for s in sigs]
    pref = [s.prefilter for s in sigs]
    if spec.edfplus:
        labels.append("EDF Annotations")
        dims.append("")
        pmin.append(-1)
        pmax.append(1)
        dmin.append(-32768)
        dmax.append(32767)
        spr.append(ann_spr)
        trans.append("")
        pref.append("")

    def num(v):
        if isinstance(v, float) and v.is_integer():
            return int(v)
        return v

    h += b"".join(_f(x, 16) for x in labels)
    h += b"".join(_f(x, 80) for x in trans)
    h += b"".join(_f(x, 8) for x in dims)
    h += b"".join(_f(num(x), 8) for x in pmin)
    h += b"".join(_f(num(x), 8) for x in pmax)
    h += b"".join(_f(int(x), 8) for x in dmin)
    h += b"".join(_f(int(x), 8) for x in dmax)
    h += b"".join(_f(x, 80) for x in pref)
    h += b"".join(_f(int(x), 8) for x in spr)
    h += b"".join(_f("", 32) for _ in range(ns))
    assert len(h) == header_bytes

    # digital data
    digital_cols = []
    for s in sigs:
        total = s.samples_per_record * spec.n_records
        if s.values is None:
            d = np.zeros(total, dtype=np.int16)
        elif s.is_digital:
            d = np.asarray(s.values, dtype=np.int64)
        else:
            g = (s.physical_max - s.physical_min) / (s.digital_max - s.digital_min)
            off = s.physical_max - g * s.digital_max
            d = np.round((np.asarray(s.values, dtype=np.float64) - off) / g).astype(np.int64)
        if len(d) < total:
            d = np.concatenate([d, np.full(total - len(d), d[-1] if len(d) else 0)])
        d = np.clip(d[:total], s.digital_min, s.digital_max).astype("<i2")
        digital_cols.append(d.reshape(spec.n_records, s.samples_per_record))

    # annotations: put time-keeping TAL in each record, events into the record
    # that contains their onset (first record if out of range)
    ann_records: list[bytes] = []
    if spec.edfplus:
        per_rec: list[list[WAnnotation]] = [[] for _ in range(spec.n_records)]
        for a in spec.annotations:
            idx = int(a.onset // spec.record_duration) if spec.record_duration > 0 else 0
            idx = min(max(idx, 0), spec.n_records - 1)
            per_rec[idx].append(a)
        for r in range(spec.n_records):
            # time keeping TAL: "+<onset>\x14\x14\x00"
            b = f"+{r * spec.record_duration:g}".encode() + bytes([TAL_SEP, TAL_SEP, TAL_END])
            for a in per_rec[r]:
                b += _tal(a.onset, a.duration, [a.text])
            if len(b) > ann_spr * 2:
                raise ValueError("annotation record too small; increase annotation_bytes_per_record")
            b += bytes(ann_spr * 2 - len(b))
            ann_records.append(b)

    body = bytearray()
    for r in range(spec.n_records):
        for col in digital_cols:
            body += col[r].tobytes()
        if spec.edfplus:
            body += ann_records[r]

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(h)
        fh.write(bytes(body))
