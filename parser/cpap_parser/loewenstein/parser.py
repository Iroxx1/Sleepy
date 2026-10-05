"""Löwenstein Medical prisma SMART / prisma SOFT SD card parser.

SD card layout (prisma SMART, firmware 3.x)::

    config.pscfg                         JSON: device (serial, firmware, device id)
    statistic.psstat                     JSON: long-term statistics (numeric keys,
                                         meaning not documented -> archived only)
    Dcm/dcm.zip                          device communication module (archived only)
    <serial>/YYYYMMDD/signal_<n>.wmedf   waveforms of one mask session (WMEDF)
    <serial>/YYYYMMDD/event_<n>.xml      settings + respiratory events of session <n>
    <serial>/YYYYMMDD/trendCurves.tc     binary trend data (archived only)
    <serial>/log/*.log                   device logs (archived only)

``<serial>`` is the decimal serial number, zero padded to 10 digits
(``config.pscfg`` stores it hexadecimal).  The day folder is the therapy day
the device assigned to the session; it is used as the night date.

prisma LINE devices (``config.pcfg`` + ``therapy.pdat``) are recognised but
not supported.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import PurePosixPath

import numpy as np

from ..base import CPAPParser, Detection, FileSet, FormatNotSupported, ParserError, register
from ..channels import slugify
from ..edf import EDFError
from ..model import (
    DeviceInfo,
    FileClassification,
    NightPlan,
    ParsedEvent,
    ParsedNight,
    ParsedSession,
    ParsedSignal,
    wall_ms,
)
from .events import EVENT_CODES, SETTING_NAMES, read_event_file, settings_from_parameters
from .wmedf import read_wmedf, read_wmedf_header

SESSION_FILE_RE = re.compile(r"^(signal|event)_(\d+)\.(wmedf|xml)$", re.I)
DAY_DIR_RE = re.compile(r"^\d{8}$")
SERIAL_DIR_RE = re.compile(r"^\d{6,12}$")

CONFIG_SMART = "config.pscfg"
CONFIG_LINE = "config.pcfg"

#: 1 hPa = 1 / 0.980665 cmH2O (exact by definition of cmH2O)
HPA_TO_CMH2O = 1 / 0.980665
HPA_NOTE = "hPa × 1,0197 → cmH2O"

#: WMEDF label -> (channel code, factor, unit, note)
SIGNAL_LABELS: dict[str, tuple[str, float, str, str | None]] = {
    "respflow": ("flow", 1.0, "L/min", None),
    "leakflowbreath": ("leak", 1.0, "L/min", None),
    "cpappressure": ("pressure", HPA_TO_CMH2O, "cmH2O", HPA_NOTE),
    "pressure": ("mask_pressure", HPA_TO_CMH2O, "cmH2O", HPA_NOTE),
    "pressuremeasured": ("pressure_measured", HPA_TO_CMH2O, "cmH2O", HPA_NOTE),
    "ipap": ("ipap", HPA_TO_CMH2O, "cmH2O", HPA_NOTE),
    "epap": ("epap", HPA_TO_CMH2O, "cmH2O", HPA_NOTE),
    "ipapsoll": ("ipap", HPA_TO_CMH2O, "cmH2O", HPA_NOTE),
    "epapsoll": ("epap", HPA_TO_CMH2O, "cmH2O", HPA_NOTE),
    "obstructlevel": ("obstruct_level", 1.0, "%", None),
    "flowfull": ("flow_full", 1.0, "L/min", None),
    "rrmv": ("rrmv", 1.0, "%", None),
    "rmvfluctuation": ("rmv_fluctuation", 1.0, "%", None),
}

#: IPAP/EPAP are dropped when they are identical to the therapy pressure (CPAP/APAP)
DUPLICATE_OF_PRESSURE = {"ipap", "epap"}

#: tested device ids (``devid`` in config.pscfg), see OSCAR's prisma loader
MODELS = {"0x92": "prisma SMART", "0x91": "prisma SOFT"}


@dataclass
class _Session:
    sid: int
    signal: str | None = None
    event: str | None = None
    day: date | None = None


def _day_from_dir(rel: str) -> date | None:
    parts = PurePosixPath(rel).parts
    if len(parts) >= 2 and DAY_DIR_RE.match(parts[-2]):
        try:
            return datetime.strptime(parts[-2], "%Y%m%d").date()
        except ValueError:
            return None
    return None


def therapy_day(ts: datetime) -> date:
    return (ts - timedelta(hours=12)).date()


class PrismaParser(CPAPParser):
    name = "loewenstein"
    manufacturer = "Löwenstein Medical"
    version = "1.0"
    setting_names = SETTING_NAMES

    # ------------------------------------------------------------------ detection
    def find_roots(self, rel_paths: Iterable[str]) -> list[str]:
        roots: set[str] = set()
        for rel in rel_paths:
            parts = PurePosixPath(rel).parts
            if not parts:
                continue
            low = parts[-1].lower()
            if low in (CONFIG_SMART, CONFIG_LINE):
                roots.add("/".join(parts[:-1]))
            elif (
                len(parts) >= 3
                and SESSION_FILE_RE.match(parts[-1])
                and DAY_DIR_RE.match(parts[-2])
                and SERIAL_DIR_RE.match(parts[-3])
            ):
                roots.add("/".join(parts[:-3]))
        return sorted(r + "/" if r else "" for r in roots)

    def _sessions(self, files: FileSet) -> dict[int, _Session]:
        out: dict[int, _Session] = {}
        for rel in files.names():
            m = SESSION_FILE_RE.match(rel.rsplit("/", 1)[-1])
            if not m:
                continue
            kind, sid = m.group(1).lower(), int(m.group(2))
            s = out.setdefault(sid, _Session(sid))
            setattr(s, kind, rel)
            s.day = s.day or _day_from_dir(rel)
        return out

    def detect(self, files: FileSet) -> Detection | None:
        has_smart = files.find(CONFIG_SMART) is not None
        sessions = self._sessions(files)
        if has_smart or any(s.signal for s in sessions.values()):
            reasons = [x for x, ok in ((CONFIG_SMART, has_smart), ("signal_*.wmedf", bool(sessions))) if ok]
            return Detection(self.name, 0.9, True, ", ".join(reasons))
        if files.find(CONFIG_LINE) is not None:
            return Detection(
                self.name, 0.8, supported=False,
                reason="config.pcfg gefunden – Löwenstein prisma LINE wird noch nicht unterstützt",
            )
        return None

    def classify(self, rel_path: str) -> FileClassification:
        name = rel_path.rsplit("/", 1)[-1]
        low = name.lower()
        m = SESSION_FILE_RE.match(name)
        if m:
            if m.group(1).lower() == "signal":
                return FileClassification(rel_path, "waveform", "Signale einer Maskensitzung (WMEDF)")
            return FileClassification(rel_path, "events", "Einstellungen und Atemereignisse (XML)")
        if low in (CONFIG_SMART, CONFIG_LINE):
            return FileClassification(rel_path, "identification", "Gerätekonfiguration")
        if low.endswith(".psstat"):
            return FileClassification(rel_path, "summary", "Langzeitstatistik (nur archiviert, nicht interpretiert)")
        if low.endswith(".tc"):
            return FileClassification(rel_path, "other", "Trendkurven (nur archiviert)")
        if low.endswith(".log"):
            return FileClassification(rel_path, "other", "Geräteprotokoll (nur archiviert)")
        return FileClassification(rel_path, "other", "Nicht interpretiert (archiviert)")

    # ------------------------------------------------------------- identification
    def identify(self, files: FileSet) -> DeviceInfo:
        info = DeviceInfo(manufacturer=self.manufacturer, data_format="Löwenstein prisma (WMEDF + XML)")
        key = files.find(CONFIG_SMART) or files.find(CONFIG_LINE)
        if key is not None:
            try:
                cfg = json.loads(files.files[key].read_text(encoding="utf-8", errors="replace"))
            except (OSError, ValueError):
                cfg = {}
            dev = cfg.get("dev") if isinstance(cfg.get("dev"), dict) else {}
            devid = str(cfg.get("devid") or dev.get("devid") or "")
            info.identification = {"config_file": key, "devid": devid, **{k: v for k, v in dev.items() if isinstance(v, str)}}
            info.product_code = devid or None
            info.model = MODELS.get(devid.lower(), f"prisma (Gerätekennung {devid})" if devid else "prisma")
            info.firmware = dev.get("fwversion")
            info.series = f"HW {dev['hwversion']}" if dev.get("hwversion") else None
            sn = str(dev.get("sn") or "")
            try:
                info.serial = str(int(sn, 16)) if sn.lower().startswith("0x") else (sn or None)
            except ValueError:
                info.serial = sn or None
        if not info.serial:
            for rel in files.names():
                parts = PurePosixPath(rel).parts
                if len(parts) >= 3 and SERIAL_DIR_RE.match(parts[-3]) and SESSION_FILE_RE.match(parts[-1]):
                    info.serial = str(int(parts[-3]))
                    info.identification.setdefault("serial_source", f"Verzeichnisname {parts[-3]}")
                    break
        # device type from the newest session's settings
        sessions = sorted(self._sessions(files).values(), key=lambda s: s.sid)
        for s in reversed(sessions):
            if s.event:
                try:
                    ev = read_event_file(files.files[s.event])
                except (ParserError, OSError):
                    continue
                kind = settings_from_parameters(ev.parameters)[0].get("mode_kind")
                if kind:
                    info.device_type = kind
                    break
        return info

    # ------------------------------------------------------------------- planning
    def _session_days(self, files: FileSet) -> dict[date, list[_Session]]:
        by_day: dict[date, list[_Session]] = defaultdict(list)
        for s in self._sessions(files).values():
            day = s.day
            if day is None and s.signal:
                try:
                    day = therapy_day(read_wmedf_header(files.files[s.signal]).start)
                except (EDFError, OSError):
                    day = None
            if day is not None:
                by_day[day].append(s)
        return by_day

    def plan(self, files: FileSet) -> list[NightPlan]:
        if files.find(CONFIG_LINE) is not None and files.find(CONFIG_SMART) is None:
            raise FormatNotSupported("Löwenstein prisma LINE wird erkannt und archiviert, aber noch nicht ausgewertet.")
        out = []
        for day, sessions in sorted(self._session_days(files).items()):
            rels = sorted(r for s in sessions for r in (s.signal, s.event) if r)
            out.append(NightPlan(date=day, files=rels))
        return out

    # -------------------------------------------------------------------- parsing
    def parse_night(self, files: FileSet, night: date) -> ParsedNight:
        result = ParsedNight(date=night)
        sessions = sorted(self._session_days(files).get(night, []), key=lambda s: s.sid)
        if not sessions:
            raise ParserError(f"Keine verwertbaren Daten für {night} gefunden")
        unknown_events: Counter[int] = Counter()
        unknown_params: dict[str, int] = {}
        raw_sessions = []
        last_settings: dict = {}
        seen: set[tuple] = set()
        for s in sessions:
            if not s.signal:
                result.warnings.append(f"{s.event}: keine zugehörige Signaldatei – Sitzung übersprungen")
                continue
            try:
                edf = read_wmedf(files.files[s.signal])
            except (EDFError, OSError) as exc:
                result.warnings.append(f"{s.signal}: Datei konnte nicht gelesen werden ({exc})")
                continue
            for w in edf.warnings:
                result.warnings.append(f"{s.signal}: {w}")
            start = wall_ms(edf.start)
            end = start + int(round(edf.duration_seconds * 1000))
            sigs = self._signals(edf, s.signal, start, result.warnings)
            result.sessions.append(ParsedSession(start_ms=start, end_ms=end, signals=sigs, files=[s.signal]))
            result.source_files.append(s.signal)
            if not s.event:
                result.warnings.append(f"{s.signal}: keine Ereignisdatei event_{s.sid}.xml gefunden")
                continue
            try:
                ev = read_event_file(files.files[s.event])
            except (ParserError, OSError) as exc:
                result.warnings.append(f"{s.event}: Datei konnte nicht gelesen werden ({exc})")
                continue
            result.sessions[-1].files.append(s.event)
            result.source_files.append(s.event)
            settings, unknown = settings_from_parameters(ev.parameters)
            if settings:
                last_settings = settings
            unknown_params.update(unknown)
            raw_sessions.append({"session": s.sid, "parameters": {str(k): v for k, v in sorted(ev.parameters.items())}})
            for e in ev.events:
                spec = EVENT_CODES.get(e.event_id)
                if spec is None:
                    unknown_events[e.event_id] += 1
                    continue
                code, label = spec
                end_ms = start + e.end_ds * 100
                start_ms = end_ms - e.duration_ds * 100
                key = (code, label, start_ms, end_ms)
                if key in seen:
                    continue
                seen.add(key)
                result.events.append(
                    ParsedEvent(code, label, end_ms, start_ms, end_ms, e.duration_ds / 10, s.event)
                )
        if not result.sessions:
            raise ParserError(f"Keine lesbaren Sitzungen für {night}")
        result.events.sort(key=lambda e: e.start_ms)
        result.settings = last_settings
        result.summary_raw = {"sessions": raw_sessions}
        if unknown_params:
            result.summary_raw["unknown_parameters"] = unknown_params
        if unknown_events:
            result.summary_raw["unknown_event_codes"] = {str(k): v for k, v in sorted(unknown_events.items())}
        return result

    def _signals(self, edf, rel: str, start: int, warnings: list[str]) -> list[ParsedSignal]:
        out: list[ParsedSignal] = []
        by_code: dict[str, np.ndarray] = {}
        for sig in edf.signals:
            if sig.digital is None or len(sig.digital) == 0:
                continue
            spec = SIGNAL_LABELS.get(sig.label.strip().lower())
            if spec is None:
                code, factor, unit, note = "x_" + slugify(sig.label or f"signal{sig.index}"), 1.0, sig.dimension, None
            else:
                code, factor, unit, note = spec
            if code in by_code:
                warnings.append(f"{rel}: Signal '{sig.label}' doppelt – zweites Vorkommen ignoriert")
                continue
            rate = edf.sample_rate(sig)
            if rate <= 0:
                warnings.append(f"{rel}: Signal '{sig.label}' ohne gültige Abtastrate übersprungen")
                continue
            by_code[code] = sig.digital
            out.append(
                ParsedSignal(
                    channel=code,
                    label=sig.label,
                    unit=unit,
                    sample_rate=rate,
                    start_ms=start,
                    digital=sig.digital,
                    gain=sig.gain * factor,
                    offset=sig.offset * factor,
                    physical_min=sig.physical_min * factor,
                    physical_max=sig.physical_max * factor,
                    source_file=rel,
                    conversion=note,
                )
            )
        pressure = by_code.get("pressure")
        if pressure is not None:
            out = [
                s for s in out
                if not (s.channel in DUPLICATE_OF_PRESSURE and np.array_equal(s.digital, pressure))
            ]
        return out


PARSER = register(PrismaParser())
