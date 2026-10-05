"""ResMed SD card parser (S9, AirSense/AirCurve 10, AirSense/AirCurve 11).

SD card layout::

    Identification.tgt | Identification.json   device identification
    Identification.crc                          checksum (not interpreted)
    STR.edf                                     one record per therapy day
    SETTINGS/                                   settings change files (archived only)
    DATALOG/YYYYMMDD/YYYYMMDD_HHMMSS_BRP.edf    25 Hz flow + pressure
                     YYYYMMDD_HHMMSS_PLD.edf    0.5 Hz pressure/leak/resp. data
                     YYYYMMDD_HHMMSS_SAD.edf    1 Hz SpO2 / pulse (oximeter)
                     YYYYMMDD_HHMMSS_EVE.edf    EDF+ event annotations
                     YYYYMMDD_HHMMSS_CSL.edf    EDF+ Cheyne-Stokes annotations
                     *.crc                      checksums (not interpreted)

S9 devices store the EDF files directly in DATALOG (no day sub folders).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from pathlib import PurePosixPath

import numpy as np

from ..base import CPAPParser, Detection, FileSet, ParserError, register
from ..channels import slugify
from ..edf import EDFError, read_edf, read_edf_header
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
from . import identification
from .labels import (
    BRP_LABELS,
    CSR_END,
    CSR_START,
    IGNORED_SIGNAL_LABELS,
    INVALID_MINUS_ONE,
    NON_EVENT_ANNOTATIONS,
    PLD_LABELS,
    SAD_LABELS,
    match_event,
    match_label,
    unit_conversion,
)
from .str_file import STRRecord, merge_str_versions

FILE_RE = re.compile(r"^(\d{8})_(\d{6})_([A-Za-z0-9]+)\.edf(\.gz)?$", re.I)
DAY_DIR_RE = re.compile(r"^\d{8}$")

SIGNAL_TYPES = {"BRP": BRP_LABELS, "PLD": PLD_LABELS, "SAD": SAD_LABELS, "SA2": SAD_LABELS}
ANNOTATION_TYPES = {"EVE", "CSL", "AEV"}

#: ResMed annotations mark the *end* of a respiratory event; the duration
#: extends backwards.  This follows how OSCAR renders ResMed flags and must be
#: verified against real flow data (see docs/VALIDATION.md).  Raw onsets are
#: always stored so the interpretation can be changed and re-processed.
EVENT_ONSET_IS_END = True

#: Files belonging to the same mask session start within this tolerance
SESSION_GAP_TOLERANCE_MS = 5_000


def _parse_file_name(name: str):
    m = FILE_RE.match(name)
    if not m:
        return None
    d, t, kind, _ = m.groups()
    try:
        ts = datetime.strptime(d + t, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return ts, kind.upper()


def therapy_day(ts: datetime) -> date:
    """ResMed therapy days run noon to noon."""
    return (ts - timedelta(hours=12)).date()


class ResMedParser(CPAPParser):
    name = "resmed"
    manufacturer = "ResMed"
    version = "1.0"

    # ------------------------------------------------------------------ detection
    def find_roots(self, rel_paths: Iterable[str]) -> list[str]:
        roots: set[str] = set()
        for rel in rel_paths:
            p = PurePosixPath(rel)
            parts = p.parts
            low = [x.lower() for x in parts]
            if low and low[-1] in ("str.edf", "identification.tgt", "identification.json"):
                roots.add("/".join(parts[:-1]))
            if "datalog" in low[:-1]:
                i = low.index("datalog")
                if _parse_file_name(parts[-1]) is not None:
                    roots.add("/".join(parts[:i]))
        out = []
        for r in sorted(roots):
            out.append(r + "/" if r else "")
        return out

    def detect(self, files: FileSet) -> Detection | None:
        names = [n.lower() for n in files.names()]
        score = 0.0
        reasons = []
        if "str.edf" in names or "str.edf.gz" in names:
            score += 0.4
            reasons.append("STR.edf")
        if "identification.tgt" in names or "identification.json" in names:
            score += 0.4
            reasons.append("Identification")
        if any(n.startswith("datalog/") and _parse_file_name(n.rsplit("/", 1)[-1]) for n in names):
            score += 0.3
            reasons.append("DATALOG/*.edf")
        if score <= 0:
            return None
        return Detection(self.name, min(score, 1.0), True, ", ".join(reasons))

    def classify(self, rel_path: str) -> FileClassification:
        name = rel_path.rsplit("/", 1)[-1]
        low = name.lower()
        if low.startswith("identification."):
            kind = "identification" if not low.endswith(".crc") else "checksum"
            return FileClassification(rel_path, kind, "Geräteidentifikation")
        if low in ("str.edf", "str.edf.gz"):
            return FileClassification(rel_path, "summary", "Tageszusammenfassung + Einstellungen")
        if low.endswith(".crc"):
            return FileClassification(rel_path, "checksum", "Prüfsumme (nicht interpretiert)")
        parsed = _parse_file_name(name)
        if parsed:
            kind = parsed[1]
            desc = {
                "BRP": "Hochaufgelöster Flow/Druck (25 Hz)",
                "PLD": "Druck, Leckage, Atemparameter (0,5 Hz)",
                "SAD": "SpO2/Puls (1 Hz)",
                "SA2": "SpO2/Puls (1 Hz)",
                "EVE": "Ereignisse (EDF+ Annotationen)",
                "CSL": "Cheyne-Stokes-Perioden (EDF+ Annotationen)",
                "AEV": "Weitere Ereignisse (EDF+ Annotationen)",
            }.get(kind, f"Unbekannter EDF-Typ {kind}")
            return FileClassification(
                rel_path, "events" if kind in ANNOTATION_TYPES else "waveform", desc
            )
        if rel_path.lower().startswith("settings/"):
            return FileClassification(rel_path, "settings", "Einstellungsdatei (nur archiviert)")
        return FileClassification(rel_path, "other", "Nicht interpretiert (archiviert)")

    # ------------------------------------------------------------- identification
    def identify(self, files: FileSet) -> DeviceInfo:
        tgt = files.find("Identification.tgt")
        js = files.find("Identification.json")
        info = identification.identify(
            files.files[tgt] if tgt else None, files.files[js] if js else None
        )
        if not info.serial:
            # fall back to the SRN= field of any EDF header
            for rel in files.names():
                if rel.lower().endswith((".edf", ".edf.gz")):
                    try:
                        h = read_edf_header(files.files[rel])
                    except (EDFError, OSError):
                        continue
                    srn = identification.serial_from_recording_field(h.recording)
                    if srn:
                        info.serial = srn
                        info.identification.setdefault("serial_source", f"EDF header {rel}")
                        break
        if info.device_type is None:
            recs = self._str_records(files)[0]
            if recs:
                last = recs[max(recs)]
                kind = last.settings.get("mode_kind")
                info.device_type = {
                    "CPAP": "CPAP",
                    "APAP": "APAP",
                    "BILEVEL": "BiLevel",
                    "BILEVEL_AUTO": "BiLevel",
                    "ASV": "ASV",
                    "ASV_AUTO": "ASV",
                    "AVAPS": "iVAPS",
                }.get(kind or "", None)
        return info

    def _is_as11(self, files: FileSet) -> bool:
        return files.find("Identification.json") is not None

    def _str_records(self, files: FileSet) -> tuple[dict[date, STRRecord], list[str]]:
        key = files.find("STR.edf") or files.find("STR.edf.gz")
        if key is None:
            return {}, []
        cache_key = tuple(str(p) for p in files.versions(key))
        cached = getattr(self, "_str_cache", None)
        if cached and cached[0] == cache_key:
            return cached[1]
        result = merge_str_versions(files.versions(key), is_as11=self._is_as11(files))
        self._str_cache = (cache_key, result)
        return result

    # ------------------------------------------------------------------- planning
    def _datalog_files(self, files: FileSet) -> dict[date, list[str]]:
        by_day: dict[date, list[str]] = defaultdict(list)
        for rel in files.names():
            parts = PurePosixPath(rel).parts
            if len(parts) < 2 or parts[0].lower() != "datalog":
                continue
            parsed = _parse_file_name(parts[-1])
            if not parsed:
                continue
            ts, _kind = parsed
            day: date | None = None
            if len(parts) >= 3 and DAY_DIR_RE.match(parts[-2]):
                try:
                    day = datetime.strptime(parts[-2], "%Y%m%d").date()
                except ValueError:
                    day = None
            if day is None:
                day = therapy_day(ts)
            by_day[day].append(rel)
        return by_day

    def plan(self, files: FileSet) -> list[NightPlan]:
        by_day = self._datalog_files(files)
        str_key = files.find("STR.edf") or files.find("STR.edf.gz")
        summary = [str_key] if str_key else []
        recs, _ = self._str_records(files)
        days = set(by_day) | set(recs)
        return [
            NightPlan(date=d, files=sorted(by_day.get(d, [])), summary_files=summary)
            for d in sorted(days)
        ]

    def summaries(self, files: FileSet) -> dict[date, dict]:
        recs, _ = self._str_records(files)
        return {d: r.raw for d, r in recs.items()}

    # -------------------------------------------------------------------- parsing
    def parse_night(self, files: FileSet, night: date) -> ParsedNight:
        result = ParsedNight(date=night)
        day_files = sorted(self._datalog_files(files).get(night, []))
        recs, str_warnings = self._str_records(files)
        rec = recs.get(night)
        window_start = datetime.combine(night, time(12, 0)) - timedelta(hours=2)
        window_end = datetime.combine(night + timedelta(days=1), time(12, 0)) + timedelta(hours=2)

        # ---- waveform files -> segments
        segments: list[tuple[int, int, str, list[ParsedSignal]]] = []
        annotation_files: list[str] = []
        for rel in day_files:
            parsed = _parse_file_name(rel.rsplit("/", 1)[-1])
            assert parsed is not None
            _, kind = parsed
            if kind in ANNOTATION_TYPES:
                annotation_files.append(rel)
                continue
            try:
                edf = read_edf(files.files[rel], read_annotations=False)
            except (EDFError, OSError) as exc:
                result.warnings.append(f"{rel}: Datei konnte nicht gelesen werden ({exc})")
                continue
            for w in edf.warnings:
                result.warnings.append(f"{rel}: {w}")
            if not (window_start <= edf.start <= window_end):
                result.warnings.append(
                    f"{rel}: Startzeit {edf.start:%Y-%m-%d %H:%M:%S} liegt außerhalb des Therapietags {night}"
                )
            table = SIGNAL_TYPES.get(kind)
            if table is None:
                result.warnings.append(f"{rel}: unbekannter Dateityp {kind}, Signale werden generisch übernommen")
                table = []
            sigs = self._signals_from_edf(edf, rel, table, result.warnings)
            if not sigs:
                continue
            start = wall_ms(edf.start)
            end = start + int(round(edf.duration_seconds * 1000))
            segments.append((start, end, rel, sigs))
            result.source_files.append(rel)

        # ---- group into sessions
        segments.sort(key=lambda s: (s[0], s[2]))
        sessions: list[ParsedSession] = []
        for start, end, rel, sigs in segments:
            cur = sessions[-1] if sessions else None
            # Files of one mask session (BRP/PLD/SAD) start at (almost) the same
            # time and overlap; anything else starts a new session.
            if cur is not None and (
                start < cur.end_ms or abs(start - cur.start_ms) <= SESSION_GAP_TOLERANCE_MS
            ):
                cur.end_ms = max(cur.end_ms, end)
                cur.signals.extend(sigs)
                cur.files.append(rel)
                continue
            sessions.append(ParsedSession(start_ms=start, end_ms=end, signals=list(sigs), files=[rel]))
        result.sessions = sessions

        # ---- annotations -> events
        seen: set[tuple] = set()
        for rel in annotation_files:
            try:
                edf = read_edf(files.files[rel], read_annotations=True)
            except (EDFError, OSError) as exc:
                result.warnings.append(f"{rel}: Datei konnte nicht gelesen werden ({exc})")
                continue
            result.source_files.append(rel)
            base = wall_ms(edf.start)
            csr_open: int | None = None
            for a in edf.annotations:
                text = a.text.strip()
                low = text.lower()
                onset = base + int(round(a.onset * 1000))
                if low in NON_EVENT_ANNOTATIONS:
                    continue
                if low == CSR_START:
                    csr_open = onset
                    continue
                if low == CSR_END:
                    if csr_open is not None:
                        ev = ParsedEvent("CSR", "CSR", csr_open, csr_open, onset, (onset - csr_open) / 1000, rel)
                        key = ("CSR", ev.start_ms, ev.end_ms)
                        if key not in seen:
                            seen.add(key)
                            result.events.append(ev)
                    else:
                        result.warnings.append(f"{rel}: 'CSR End' ohne 'CSR Start' bei {a.onset:.0f}s")
                    csr_open = None
                    continue
                code = match_event(text)
                dur = a.duration if (a.duration is not None and a.duration >= 0) else None
                dms = int(round((dur or 0) * 1000))
                if EVENT_ONSET_IS_END:
                    start_ms, end_ms = onset - dms, onset
                else:
                    start_ms, end_ms = onset, onset + dms
                key = (code, onset, dms, text)
                if key in seen:
                    continue
                seen.add(key)
                result.events.append(ParsedEvent(code, text, onset, start_ms, end_ms, dur, rel))
                if code == "OTHER":
                    result.warnings.append(f"{rel}: unbekannte Annotation '{text}' als 'Sonstiges' übernommen")
            if csr_open is not None:
                result.warnings.append(f"{rel}: 'CSR Start' ohne Ende – Periode verworfen")
        result.events.sort(key=lambda e: e.start_ms)

        # ---- daily summary (STR.edf)
        if rec is not None:
            result.device_metrics = dict(rec.metrics)
            result.settings = dict(rec.settings)
            result.summary_raw = dict(rec.raw)
            result.mask_intervals = list(rec.mask_intervals)
            str_key = files.find("STR.edf") or files.find("STR.edf.gz")
            if str_key:
                result.source_files.append(str_key)
            if not result.sessions:
                for s, e in rec.mask_intervals:
                    result.sessions.append(ParsedSession(start_ms=s, end_ms=e, source="summary"))
        result.warnings.extend(w for w in str_warnings if w.startswith(str(night)))

        if not result.sessions and not result.events and rec is None:
            raise ParserError(f"Keine verwertbaren Daten für {night} gefunden")
        return result

    def _signals_from_edf(self, edf, rel: str, table, warnings: list[str]) -> list[ParsedSignal]:
        out: list[ParsedSignal] = []
        used: dict[str, int] = {}
        start = wall_ms(edf.start)
        for s in edf.data_signals():
            if s.label.strip().lower() in IGNORED_SIGNAL_LABELS:
                continue
            if s.digital is None or len(s.digital) == 0:
                continue
            code = match_label(s.label, table) if table else None
            if code is None:
                code = "x_" + slugify(s.label or f"signal{s.index}")
            factor, unit, note = unit_conversion(code, s.dimension)
            invalid = -1 if code in INVALID_MINUS_ONE else None
            if invalid is not None and np.all(s.digital == invalid):
                # e.g. SAD file written without oximeter connected
                continue
            n = used.get(code, 0)
            used[code] = n + 1
            ch = code if n == 0 else f"{code}_{n + 1}"
            rate = edf.sample_rate(s)
            if rate <= 0:
                warnings.append(f"{rel}: Signal '{s.label}' ohne gültige Abtastrate übersprungen")
                continue
            out.append(
                ParsedSignal(
                    channel=ch,
                    label=s.label,
                    unit=unit,
                    sample_rate=rate,
                    start_ms=start,
                    digital=s.digital.astype(np.int16, copy=False),
                    gain=s.gain * factor,
                    offset=s.offset * factor,
                    physical_min=s.physical_min * factor,
                    physical_max=s.physical_max * factor,
                    source_file=rel,
                    invalid_digital=invalid,
                    conversion=note,
                )
            )
        return out


PARSER = register(ResMedParser())
