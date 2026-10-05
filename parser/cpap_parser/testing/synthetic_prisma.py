"""Generator for *synthetic* Löwenstein prisma SMART SD card data.

!!! These files are artificial.  They reproduce the file layout, file names,
!!! WMEDF header structure (8/16 bit channels), signal labels and event XML
!!! structure of a prisma SMART card so the parser can be tested without
!!! personal health data.  Values are random and medically meaningless.

Usage::

    python -m cpap_parser.testing.synthetic_prisma /tmp/prisma --nights 7
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np

#: (label, dimension, physical min/max, digital min/max, samples per 1 s record, width)
SIGNALS = [
    ("RespFlow", "l/min", -32768.0, 32767.0, -32768, 32767, 5, 2),
    ("LeakFlowBreath", "l/min", 0.0, 255.0, 0, 255, 1, 1),
    ("ObstructLevel", "%", 0.0, 255.0, 0, 255, 1, 1),
    ("Pressure", "hPa", 0.0, 25.5, 0, 255, 2, 1),
    ("CPAPPressure", "hPa", 0.0, 25.5, 0, 255, 1, 1),
    ("PressureMeasured", "hPa", 0.0, 25.5, 0, 255, 2, 1),
    ("FlowFull", "l/min", -32768.0, 32767.0, -32768, 32767, 5, 2),
    ("rRMV", "%", 0.0, 255.0, 0, 255, 1, 1),
    ("SPRStatus", "-", 0.0, 255.0, 0, 255, 1, 1),
    ("IPAP", "hPa", 0.0, 25.5, 0, 255, 1, 1),
    ("EPAP", "hPa", 0.0, 25.5, 0, 255, 1, 1),
]

#: parameters written to every event file (ParameterID, value)
PARAMETERS = [(6, 2), (9, 400), (10, 1400), (11, 400), (12, 400), (13, 1), (14, 0), (15, 1),
              (16, 3), (17, 0), (18, 20), (19, 20), (21, 22), (38, 1300)]


@dataclass
class SynthPrismaEvent:
    event_id: int
    end_ds: int  # 1/10 s after session start
    duration_ds: int


@dataclass
class SynthPrismaSession:
    sid: int
    day: date
    start: datetime
    seconds: int
    events: list[SynthPrismaEvent] = field(default_factory=list)


def _field(value, width: int) -> bytes:
    s = str(value).encode("latin-1")[:width]
    return s + b" " * (width - len(s))


def write_wmedf(path: Path, start: datetime, columns: dict[str, np.ndarray], n_records: int) -> None:
    ns = len(SIGNALS)
    head = b"".join([
        _field("1", 8),
        _field("Patient Name", 80),
        _field(f"Recording start at {start:%d.%m.%Y %H:%M:%S}", 80),
        _field(f"{start:%d.%m.%y}", 8),
        _field(f"{start:%H.%M.%S}", 8),
        _field(256 + ns * 256, 8),
        _field("#s", 44),
        _field(n_records, 8),
        _field(1, 8),
        _field(ns, 4),
    ])
    cols = [
        [_field(s[0], 16) for s in SIGNALS],
        [_field(f"Transducer {s[0]}", 80) for s in SIGNALS],
        [_field(s[1], 8) for s in SIGNALS],
        [_field(s[2], 8) for s in SIGNALS],
        [_field(s[3], 8) for s in SIGNALS],
        [_field(s[4], 8) for s in SIGNALS],
        [_field(s[5], 8) for s in SIGNALS],
        [_field("None", 80) for _ in SIGNALS],
        [_field(s[6], 8) for s in SIGNALS],
        [_field(f"#{s[7]}", 32) for s in SIGNALS],
    ]
    dt = np.dtype([(s[0], ("<i2" if s[7] == 2 else ("u1" if s[4] >= 0 else "i1")), (s[6],)) for s in SIGNALS])
    rec = np.zeros(n_records, dtype=dt)
    for s in SIGNALS:
        rec[s[0]] = columns[s[0]].reshape(n_records, s[6])
    path.write_bytes(head + b"".join(b"".join(c) for c in cols) + rec.tobytes())


def write_event_xml(path: Path, start_unix: int, events: list[SynthPrismaEvent]) -> None:
    lines = ['<?xml version="1.0" encoding="utf-8"?>', f"<!-- started {start_unix} -->", "<desc>"]
    lines += [f'<DeviceEvent  DeviceEventID="0" Time="0" ParameterID="{p}" NewValue="{v}"/>' for p, v in PARAMETERS]
    lines.append('<DeviceEvent  DeviceEventID="1" Time="0" ParameterID="255" NewValue="3"/>')
    for e in events:
        lines.append(
            f'<RespEvent RespEventID = "{e.event_id}" EndTime = "{e.end_ds}" Duration = "{e.duration_ds}" '
            f'Pressure = "400" Strength = "0"/>'
        )
    lines.append("</desc>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_card(root: str | Path, first_day: date, nights: int = 3, seed: int = 1, serial: int = 12345678,
               hours: tuple[float, float] = (0.5, 1.0), devid: str = "0x92") -> list[SynthPrismaSession]:
    """Write a synthetic card and return the ground truth sessions."""
    root = Path(root)
    rng = np.random.default_rng(seed)
    root.mkdir(parents=True, exist_ok=True)
    dev = {"setversion": "1.10.0", "fwversion": "9.9.0001", "fwname": "synthetic", "sn": hex(serial),
           "devid": devid, "hwversion": "128"}
    (root / "config.pscfg").write_text(json.dumps({"version": "1.10.0", "devid": devid, "dev": dev, "cfg": {"1": 146}}))
    (root / "statistic.psstat").write_text(json.dumps({"version": "1.2.0", "dev": dev, "days": []}))
    base = root / f"{serial:010d}"
    (base / "log").mkdir(parents=True, exist_ok=True)
    (base / "log" / "service.log").write_text("synthetic\n")
    sessions: list[SynthPrismaSession] = []
    sid = 100
    for i in range(nights):
        day = first_day + timedelta(days=i)
        start = datetime.combine(day, time(23, 0)) + timedelta(minutes=int(rng.integers(0, 90)))
        seconds = int(rng.uniform(*hours) * 3600)
        sid += 1
        s = SynthPrismaSession(sid, day, start, seconds)
        t = rng.normal(0, 1, seconds * 5)
        flow = (25 * np.sin(np.arange(seconds * 5) / 5 * 2 * np.pi / 4) + t).astype(np.int16)
        events = [SynthPrismaEvent(eid, int(rng.integers(600, seconds * 10 - 10)), dur)
                  for eid, dur in ((101, 120), (111, 180), (111, 140), (121, 90), (131, 40), (2, 1200), (1101, 30))]
        for e in events:
            if e.event_id in (101, 111):
                a, b = (e.end_ds - e.duration_ds) // 2, e.end_ds // 2
                flow[a:b] = (flow[a:b] * (0.05 if e.event_id == 101 else 0.4)).astype(np.int16)
        s.events = sorted(events, key=lambda e: e.end_ds)
        pressure = np.clip(np.linspace(40, 120, seconds), 0, 255).astype(np.int16)
        cols = {
            "RespFlow": flow,
            "LeakFlowBreath": rng.integers(0, 10, seconds).astype(np.int16),
            "ObstructLevel": rng.integers(0, 30, seconds).astype(np.int16),
            "Pressure": np.repeat(pressure, 2),
            "CPAPPressure": pressure,
            "PressureMeasured": np.repeat(pressure, 2),
            "FlowFull": flow + 20,
            "rRMV": np.full(seconds, 100, dtype=np.int16),
            "SPRStatus": np.ones(seconds, dtype=np.int16),
            "IPAP": pressure,
            "EPAP": pressure,
        }
        day_dir = base / f"{day:%Y%m%d}"
        day_dir.mkdir(parents=True, exist_ok=True)
        write_wmedf(day_dir / f"signal_{sid}.wmedf", start, cols, seconds)
        write_event_xml(day_dir / f"event_{sid}.xml", int(start.timestamp()), s.events)
        (day_dir / "trendCurves.tc").write_bytes(bytes(16))
        sessions.append(s)
    return sessions


def main() -> None:
    ap = argparse.ArgumentParser(description="Synthetische Löwenstein-prisma-Daten erzeugen")
    ap.add_argument("target")
    ap.add_argument("--nights", type=int, default=7)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    write_card(a.target, date.today() - timedelta(days=a.nights), a.nights, a.seed)


if __name__ == "__main__":
    main()
