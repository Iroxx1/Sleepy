"""Generator for *synthetic* ResMed-like SD card data.

!!! These files are artificial.  They reproduce the documented file layout,
!!! file names, EDF/EDF+ structure and signal labels of ResMed AirSense 10/11
!!! cards so the importer can be tested without personal health data.  Signal
!!! scaling (physical/digital ranges) of real devices is NOT known here and is
!!! irrelevant to the parser, which always reads scaling from the EDF header.

Usage::

    python -m cpap_parser.testing.synthetic_resmed /tmp/sdcard --nights 30
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np

from ..edf_writer import EDFSpec, WAnnotation, WSignal, write_edf

BRP_HZ = 25
PLD_HZ = 0.5
SAD_HZ = 1
REC_S = 60  # data record duration of waveform files


@dataclass
class SynthEvent:
    code: str
    end_s: float  # seconds since session start (ResMed: annotation marks the end)
    duration: float


@dataclass
class SynthSession:
    start: datetime
    seconds: int
    events: list[SynthEvent] = field(default_factory=list)
    csr: list[tuple[float, float]] = field(default_factory=list)
    # generated arrays (physical units as stored by ResMed: L/s, L, cmH2O)
    flow: np.ndarray | None = None
    press_hi: np.ndarray | None = None
    pld: dict[str, np.ndarray] = field(default_factory=dict)
    spo2: np.ndarray | None = None
    pulse: np.ndarray | None = None


@dataclass
class SynthNight:
    day: date
    sessions: list[SynthSession]


EVENT_TEXT = {
    "OA": "Obstructive Apnea",
    "CA": "Central Apnea",
    "H": "Hypopnea",
    "UA": "Apnea",
    "RERA": "Arousal",
}


def _session_signals(rng: np.random.Generator, s: SynthSession, oximetry: bool, base_pressure: float):
    n_brp = s.seconds * BRP_HZ
    t = np.arange(n_brp) / BRP_HZ
    # breathing: frequency drifts around 14/min
    rr = 14 + 1.5 * np.sin(2 * np.pi * t / 1800.0) + rng.normal(0, 0.3, n_brp).cumsum() / np.sqrt(n_brp) * 3
    rr = np.clip(rr, 9, 22)
    phase = np.cumsum(rr / 60.0 / BRP_HZ)
    amp = np.full(n_brp, 0.42) * (1 + 0.15 * np.sin(2 * np.pi * t / 600.0))
    # events modify the amplitude (ResMed: annotation time = end of event)
    for ev in s.events:
        a = int(max(0, (ev.end_s - ev.duration) * BRP_HZ))
        b = int(min(n_brp, ev.end_s * BRP_HZ))
        if ev.code in ("OA", "CA", "UA"):
            amp[a:b] *= 0.06
        elif ev.code == "H":
            amp[a:b] *= 0.4
        elif ev.code == "RERA":
            amp[a:b] *= 0.75
        # recovery breaths
        c = min(n_brp, b + 6 * BRP_HZ)
        amp[b:c] *= 1.6
    for cs, ce in s.csr:
        a, b = int(cs * BRP_HZ), int(min(n_brp, ce * BRP_HZ))
        amp[a:b] *= 0.5 + 0.5 * np.abs(np.sin(2 * np.pi * t[a:b] / 60.0))
    wave = np.sin(2 * np.pi * phase)
    wave = np.where(wave > 0, wave, wave * 0.85)  # expiration slightly flatter
    flow = amp * wave + rng.normal(0, 0.01, n_brp)

    # pressure (APAP): rises after obstructive events, slowly decays
    n_pld = int(s.seconds * PLD_HZ)
    tp = np.arange(n_pld) / PLD_HZ
    pressure = np.full(n_pld, base_pressure)
    p = base_pressure
    ev_idx = sorted(int(e.end_s * PLD_HZ) for e in s.events if e.code in ("OA", "H", "RERA"))
    j = 0
    for i in range(n_pld):
        while j < len(ev_idx) and ev_idx[j] <= i:
            p = min(p + 0.6, 13.0)
            j += 1
        p = max(base_pressure, p - 0.004)
        pressure[i] = p
    pressure = np.round(pressure * 50) / 50
    epap = np.maximum(4.0, pressure - 2.0)

    leak = np.full(n_pld, 0.02) + np.abs(rng.normal(0, 0.008, n_pld))
    for _ in range(rng.integers(0, 3)):
        a = int(rng.integers(0, max(1, n_pld - 300)))
        ln = int(rng.integers(100, 600))
        leak[a:a + ln] += rng.uniform(0.15, 0.6) * np.hanning(len(leak[a:a + ln]))
    resp = np.interp(tp, t, rr) + rng.normal(0, 0.4, n_pld)
    tidvol = np.clip(0.45 + rng.normal(0, 0.04, n_pld), 0.1, 1.2)
    for ev in s.events:
        a = int(max(0, (ev.end_s - ev.duration) * PLD_HZ))
        b = int(min(n_pld, ev.end_s * PLD_HZ))
        tidvol[a:b] *= 0.2 if ev.code in ("OA", "CA", "UA") else 0.6
    minvent = resp * tidvol
    flowlim = np.clip(rng.gamma(0.4, 0.05, n_pld), 0, 1)
    snore = np.clip(rng.gamma(0.3, 0.08, n_pld), 0, 5)
    for ev in s.events:
        if ev.code in ("OA", "H", "RERA"):
            a = int(max(0, (ev.end_s - ev.duration - 60) * PLD_HZ))
            b = int(min(n_pld, ev.end_s * PLD_HZ))
            flowlim[a:b] = np.clip(flowlim[a:b] + rng.uniform(0.1, 0.4), 0, 1)
    flowlim = np.round(flowlim * 100) / 100
    snore = np.round(snore * 100) / 100

    # high-rate mask pressure: inspiration ~ pressure, expiration ~ epap
    p_hi = np.interp(t, tp, pressure)
    e_hi = np.interp(t, tp, epap)
    press_hi = np.where(flow > 0, p_hi, e_hi) + rng.normal(0, 0.05, n_brp)
    mask_press = np.round((pressure + epap) / 2 * 50) / 50

    s.flow = flow
    s.press_hi = press_hi
    s.pld = {
        "MaskPress.2s": mask_press,
        "Press.2s": pressure,
        "EprPress.2s": epap,
        "Leak.2s": np.round(leak * 50) / 50,
        "RespRate.2s": np.round(resp * 5) / 5,
        "TidVol.2s": np.round(tidvol * 50) / 50,
        "MinVent.2s": np.round(minvent * 8) / 8,
        "Snore.2s": snore,
        "FlowLim.2s": flowlim,
    }
    n_sad = s.seconds * SAD_HZ
    if oximetry:
        ts = np.arange(n_sad)
        spo2 = 95.5 + 0.8 * np.sin(2 * np.pi * ts / 2400) + rng.normal(0, 0.3, n_sad)
        for ev in s.events:
            if ev.code in ("OA", "CA", "UA", "H"):
                c = int(ev.end_s + 15)
                drop = rng.uniform(2.0, 5.0)
                w = np.arange(-15, 30)
                idx = c + w
                ok = (idx >= 0) & (idx < n_sad)
                spo2[idx[ok]] -= drop * np.exp(-((w[ok]) / 10.0) ** 2)
        s.spo2 = np.clip(np.round(spo2), 80, 100)
        s.pulse = np.round(62 + 4 * np.sin(2 * np.pi * ts / 1800) + rng.normal(0, 1.2, n_sad))
    else:
        s.spo2 = None
        s.pulse = None


def _make_events(rng, seconds: int, ahi: float, cluster: bool) -> list[SynthEvent]:
    hours = seconds / 3600
    n = rng.poisson(max(ahi, 0.05) * hours)
    mix = rng.choice(["OA", "CA", "H", "UA"], size=n, p=[0.35, 0.2, 0.4, 0.05])
    times = rng.uniform(300, max(301, seconds - 60), size=n)
    if cluster and n > 4:
        c = rng.uniform(1800, max(1801, seconds - 3600))
        k = n // 2
        times[:k] = c + np.sort(rng.uniform(0, 1500, size=k))
    out = []
    for code, tt in zip(mix, times, strict=False):
        dur = float(np.round(rng.uniform(10, 32), 0)) if code != "H" else float(np.round(rng.uniform(10, 25), 0))
        out.append(SynthEvent(str(code), float(np.round(tt, 0)), dur))
    for tt in rng.uniform(300, max(301, seconds - 60), size=rng.poisson(0.8 * hours)):
        out.append(SynthEvent("RERA", float(np.round(tt, 0)), float(np.round(rng.uniform(8, 15)))))
    out.sort(key=lambda e: e.end_s)
    # avoid overlapping events
    cleaned: list[SynthEvent] = []
    last_end = -1e9
    for e in out:
        if e.end_s - e.duration > last_end + 5:
            cleaned.append(e)
            last_end = e.end_s
    return cleaned


def generate_nights(
    first_day: date,
    nights: int,
    seed: int = 42,
    hours: tuple[float, float] = (6.0, 8.5),
    skip_probability: float = 0.06,
    oximetry: bool = False,
) -> list[SynthNight]:
    rng = np.random.default_rng(seed)
    out: list[SynthNight] = []
    for i in range(nights):
        day = first_day + timedelta(days=i)
        if i > 0 and rng.random() < skip_probability:
            continue
        bed = datetime.combine(day, time(22, 30)) + timedelta(minutes=float(rng.normal(0, 35)))
        total = float(rng.uniform(*hours)) * 3600
        bad = rng.random() < 0.12
        ahi = float(rng.uniform(6, 14)) if bad else float(rng.lognormal(np.log(2.0), 0.5))
        parts = [total]
        if rng.random() < 0.3 and total > 4 * 3600:
            cut = float(rng.uniform(0.3, 0.7))
            parts = [total * cut, total * (1 - cut)]
        sessions = []
        start = bed.replace(microsecond=0)
        for _k, sec in enumerate(parts):
            sec_i = int(sec // REC_S * REC_S)
            ss = SynthSession(start=start, seconds=sec_i)
            ss.events = _make_events(rng, sec_i, ahi, cluster=bad)
            if rng.random() < 0.08 and sec_i > 7200:
                a = float(rng.uniform(1800, sec_i - 3600))
                ss.csr.append((a, a + float(rng.uniform(300, 900))))
            sessions.append(ss)
            start = start + timedelta(seconds=sec_i + float(rng.uniform(300, 1200)))
            start = start.replace(microsecond=0)
        out.append(SynthNight(day=day, sessions=sessions))
    return out


def _wsig(label, dim, pmin, pmax, spr, values, dmin=-32768, dmax=32767):
    return WSignal(label, dim, pmin, pmax, dmin, dmax, spr, values=values)


def write_card(
    root: str | Path,
    first_day: date,
    nights: int,
    seed: int = 42,
    serial: str = "23000000001",
    model: str = "AirSense_10_AutoSet",
    product_code: str = "37028",
    as11: bool = False,
    oximetry: bool = False,
    hours: tuple[float, float] = (6.0, 8.5),
    skip_probability: float = 0.06,
) -> list[SynthNight]:
    """Write a synthetic SD card tree and return the generated ground truth."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed + 1)
    data = generate_nights(first_day, nights, seed, hours, skip_probability, oximetry)
    recording = f"Startdate X X X SRN={serial} SYNTHETIC-TESTDATA"

    if as11:
        ident = {
            "FlowGenerator": {
                "IdentificationProfiles": {
                    "Product": {
                        "SerialNumber": serial,
                        "ProductCode": product_code,
                        "ProductName": model.replace("_", " "),
                    }
                }
            }
        }
        (root / "Identification.json").write_text(json.dumps(ident, indent=2))
    else:
        (root / "Identification.tgt").write_text(
            f"#SRN {serial}\n#PNA {model}\n#PCD {product_code}\n", encoding="latin-1"
        )
    (root / "SETTINGS").mkdir(exist_ok=True)

    for night in data:
        ddir = root / "DATALOG" / night.day.strftime("%Y%m%d")
        ddir.mkdir(parents=True, exist_ok=True)
        eve_ann: list[WAnnotation] = []
        csl_ann: list[WAnnotation] = []
        first_start = night.sessions[0].start
        for s in night.sessions:
            _session_signals(rng, s, oximetry, base_pressure=float(rng.uniform(7.0, 9.0)))
            stamp = s.start.strftime("%Y%m%d_%H%M%S")
            nrec = s.seconds // REC_S
            write_edf(
                ddir / f"{stamp}_BRP.edf",
                EDFSpec(
                    start=s.start,
                    record_duration=REC_S,
                    n_records=nrec,
                    recording=recording,
                    signals=[
                        _wsig("Flow.40ms", "L/s", -2.0, 2.0, REC_S * BRP_HZ, s.flow),
                        _wsig("Press.40ms", "cmH2O", -5.0, 30.0, REC_S * BRP_HZ, s.press_hi),
                        WSignal("Crc16", "", -32768, 32767, -32768, 32767, 1, is_digital=True),
                    ],
                ),
            )
            pld_spr = int(REC_S * PLD_HZ)
            pld_sigs = []
            ranges = {
                "MaskPress.2s": ("cmH2O", -5, 30),
                "Press.2s": ("cmH2O", 0, 30),
                "EprPress.2s": ("cmH2O", 0, 30),
                "Leak.2s": ("L/s", 0, 2),
                "RespRate.2s": ("bpm", 0, 60),
                "TidVol.2s": ("L", 0, 4),
                "MinVent.2s": ("L/min", 0, 30),
                "Snore.2s": ("", 0, 5),
                "FlowLim.2s": ("", 0, 1),
            }
            for lab, (dim, lo, hi) in ranges.items():
                pld_sigs.append(_wsig(lab, dim, lo, hi, pld_spr, s.pld[lab]))
            pld_sigs.append(WSignal("Crc16", "", -32768, 32767, -32768, 32767, 1, is_digital=True))
            write_edf(
                ddir / f"{stamp}_PLD.edf",
                EDFSpec(start=s.start, record_duration=REC_S, n_records=nrec, recording=recording, signals=pld_sigs),
            )
            sad_spr = REC_S * SAD_HZ
            if oximetry:
                sad_sigs = [
                    WSignal("Pulse.1s", "bpm", -1, 300, -1, 300, sad_spr, values=s.pulse),
                    WSignal("SpO2.1s", "%", -1, 100, -1, 100, sad_spr, values=s.spo2),
                ]
            else:  # device without oximeter writes -1
                sad_sigs = [
                    WSignal("Pulse.1s", "bpm", -1, 300, -1, 300, sad_spr, values=np.full(s.seconds, -1), is_digital=True),
                    WSignal("SpO2.1s", "%", -1, 100, -1, 100, sad_spr, values=np.full(s.seconds, -1), is_digital=True),
                ]
            sad_sigs.append(WSignal("Crc16", "", -32768, 32767, -32768, 32767, 1, is_digital=True))
            write_edf(
                ddir / f"{stamp}_SAD.edf",
                EDFSpec(start=s.start, record_duration=REC_S, n_records=nrec, recording=recording, signals=sad_sigs),
            )
            off = (s.start - first_start).total_seconds()
            for ev in s.events:
                eve_ann.append(WAnnotation(off + ev.end_s, ev.duration, EVENT_TEXT[ev.code]))
            for a, b in s.csr:
                csl_ann.append(WAnnotation(off + a, None, "CSR Start"))
                csl_ann.append(WAnnotation(off + b, None, "CSR End"))
        stamp0 = first_start.strftime("%Y%m%d_%H%M%S")
        write_edf(
            ddir / f"{stamp0}_EVE.edf",
            EDFSpec(
                start=first_start,
                record_duration=0,
                n_records=1,
                recording=recording,
                edfplus="EDF+D",
                signals=[],
                annotations=[WAnnotation(0, None, "Recording starts")] + eve_ann,
            ),
        )
        write_edf(
            ddir / f"{stamp0}_CSL.edf",
            EDFSpec(
                start=first_start,
                record_duration=0,
                n_records=1,
                recording=recording,
                edfplus="EDF+D",
                signals=[],
                annotations=[WAnnotation(0, None, "Recording starts")] + csl_ann,
            ),
        )

    _write_str(root / "STR.edf", first_day, nights, data, recording, oximetry, as11)
    return data


def _write_str(path: Path, first_day: date, ndays: int, data: list[SynthNight], recording: str, oximetry: bool, as11: bool):
    by_day = {n.day: n for n in data}
    cols: dict[str, list] = {}
    maskon: list[list[int]] = []
    maskoff: list[list[int]] = []

    def put(label, value):
        cols.setdefault(label, []).append(value)

    for i in range(ndays):
        day = first_day + timedelta(days=i)
        noon = datetime.combine(day, time(12, 0))
        n = by_day.get(day)
        ons = [-1] * 10
        offs = [-1] * 10
        if n is None:
            maskon.append(ons)
            maskoff.append(offs)
            for lab in STR_SCALARS:
                put(lab, -1 if lab not in SETTINGS_VALUES else SETTINGS_VALUES[lab])
            put("Duration", 0)
            put("MaskEvents", 0)
            put("Mode", 3 if as11 else 1)
            continue
        secs = 0
        ev = {"OA": 0, "CA": 0, "H": 0, "UA": 0, "RERA": 0}
        leak, press, epap, mp, rr, tv, mv, spo2 = [], [], [], [], [], [], [], []
        for k, s in enumerate(n.sessions):
            a = int((s.start - noon).total_seconds() // 60)
            b = int((s.start + timedelta(seconds=s.seconds) - noon).total_seconds() // 60)
            ons[k], offs[k] = a, b
            secs += s.seconds
            for e in s.events:
                ev[e.code] += 1
            leak.append(s.pld["Leak.2s"])
            press.append(s.pld["Press.2s"])
            epap.append(s.pld["EprPress.2s"])
            mp.append(s.pld["MaskPress.2s"])
            rr.append(s.pld["RespRate.2s"])
            tv.append(s.pld["TidVol.2s"])
            mv.append(s.pld["MinVent.2s"])
            if s.spo2 is not None:
                spo2.append(s.spo2)
        maskon.append(ons)
        maskoff.append(offs)
        h = secs / 3600
        cat = {k: np.concatenate(v) for k, v in
               dict(leak=leak, press=press, epap=epap, mp=mp, rr=rr, tv=tv, mv=mv).items()}

        def pct(arr, q):
            return float(np.percentile(arr, q))

        put("Duration", round(secs / 60))
        put("MaskEvents", 2 * len(n.sessions))
        put("Mode", 1)
        put("AHI", (ev["OA"] + ev["CA"] + ev["H"] + ev["UA"]) / h)
        put("AI", (ev["OA"] + ev["CA"] + ev["UA"]) / h)
        put("HI", ev["H"] / h)
        put("OAI", ev["OA"] / h)
        put("CAI", ev["CA"] / h)
        put("UAI", ev["UA"] / h)
        put("RIN", ev["RERA"] / h)
        put("CSR", 0)
        put("Leak.50", pct(cat["leak"], 50))
        put("Leak.70", pct(cat["leak"], 70))
        put("Leak.95", pct(cat["leak"], 95))
        put("Leak.Max", float(cat["leak"].max()))
        put("MaskPress.50", pct(cat["mp"], 50))
        put("MaskPress.95", pct(cat["mp"], 95))
        put("MaskPress.Max", float(cat["mp"].max()))
        put("TgtIPAP.50", pct(cat["press"], 50))
        put("TgtIPAP.95", pct(cat["press"], 95))
        put("TgtIPAP.Max", float(cat["press"].max()))
        put("TgtEPAP.50", pct(cat["epap"], 50))
        put("TgtEPAP.95", pct(cat["epap"], 95))
        put("TgtEPAP.Max", float(cat["epap"].max()))
        put("RespRate.50", pct(cat["rr"], 50))
        put("RespRate.95", pct(cat["rr"], 95))
        put("RespRate.Max", float(cat["rr"].max()))
        put("TidVol.50", pct(cat["tv"], 50))
        put("TidVol.95", pct(cat["tv"], 95))
        put("TidVol.Max", float(cat["tv"].max()))
        put("MinVent.50", pct(cat["mv"], 50))
        put("MinVent.95", pct(cat["mv"], 95))
        put("MinVent.Max", float(cat["mv"].max()))
        if spo2:
            sp = np.concatenate(spo2)
            put("SpO2.50", pct(sp, 50))
            put("SpO2.95", pct(sp, 95))
            put("SpO2.Max", float(sp.max()))
        else:
            put("SpO2.50", -1)
            put("SpO2.95", -1)
            put("SpO2.Max", -1)
        for lab, v in SETTINGS_VALUES.items():
            put(lab, v)

    signals = [
        WSignal("MaskOn", "min", -1, 1440, -1, 1440, 10, values=np.array(maskon).reshape(-1), is_digital=True),
        WSignal("MaskOff", "min", -1, 1440, -1, 1440, 10, values=np.array(maskoff).reshape(-1), is_digital=True),
    ]
    units = {"Leak": "L/s", "TidVol": "L", "MinVent": "L/min", "RespRate": "bpm", "Press": "cmH2O", "IPAP": "cmH2O", "EPAP": "cmH2O"}
    for lab, vals in cols.items():
        dim = next((u for k, u in units.items() if k in lab), "")
        if lab in ("Leak.50", "Leak.70", "Leak.95", "Leak.Max", "TidVol.50", "TidVol.95", "TidVol.Max"):
            sig = WSignal(lab, dim, -0.01, 327.66, -1, 32766, 1, values=np.array(vals, float))
        elif lab in ("Duration", "MaskEvents", "Mode") or lab.startswith("S."):
            sig = WSignal(lab, dim, -1, 32766, -1, 32766, 1, values=np.array(vals, float))
        else:
            sig = WSignal(lab, dim, -0.1, 3276.6, -1, 32766, 1, values=np.array(vals, float))
        signals.append(sig)
    signals.append(WSignal("Crc16", "", -32768, 32767, -32768, 32767, 1, is_digital=True))
    write_edf(
        path,
        EDFSpec(
            start=datetime.combine(first_day, time(12, 0)),
            record_duration=86400,
            n_records=ndays,
            recording=recording,
            signals=signals,
        ),
    )


SETTINGS_VALUES = {
    "S.RampEnable": 1,
    "S.RampTime": 20,
    "S.AS.Comfort": 0,
    "S.AS.StartPress": 5,
    "S.AS.MinPress": 7,
    "S.AS.MaxPress": 13,
    "S.EPR.ClinEnable": 1,
    "S.EPR.EPREnable": 1,
    "S.EPR.Level": 2,
    "S.EPR.EPRType": 1,
    "S.SmartStart": 1,
    "S.ABFilter": 0,
    "S.Mask": 2,
    "S.Tube": 1,
    "S.ClimateControl": 1,
    "S.HumEnable": 1,
    "S.HumLevel": 4,
    "S.TempEnable": 1,
    "S.Temp": 27,
}
STR_SCALARS = [
    "AHI", "AI", "HI", "OAI", "CAI", "UAI", "RIN", "CSR",
    "Leak.50", "Leak.70", "Leak.95", "Leak.Max", "MaskPress.50", "MaskPress.95", "MaskPress.Max",
    "TgtIPAP.50", "TgtIPAP.95", "TgtIPAP.Max", "TgtEPAP.50", "TgtEPAP.95", "TgtEPAP.Max",
    "RespRate.50", "RespRate.95", "RespRate.Max", "TidVol.50", "TidVol.95", "TidVol.Max",
    "MinVent.50", "MinVent.95", "MinVent.Max", "SpO2.50", "SpO2.95", "SpO2.Max",
] + list(SETTINGS_VALUES)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Synthetische ResMed-SD-Karte erzeugen (Testdaten!)")
    ap.add_argument("target")
    ap.add_argument("--nights", type=int, default=14)
    ap.add_argument("--start", default=None, help="erster Therapietag YYYY-MM-DD")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--oximetry", action="store_true")
    ap.add_argument("--as11", action="store_true")
    a = ap.parse_args(argv)
    start = date.fromisoformat(a.start) if a.start else date.today() - timedelta(days=a.nights)
    write_card(a.target, start, a.nights, seed=a.seed, oximetry=a.oximetry, as11=a.as11,
               model="AirSense_11_AutoSet" if a.as11 else "AirSense_10_AutoSet")
    print(f"Synthetische Daten geschrieben nach {a.target}")


if __name__ == "__main__":
    main()
