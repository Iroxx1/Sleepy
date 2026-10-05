"""Turn parsed nights into normalised database rows and signal files.

A night is always rebuilt *completely* from the archived raw files.  New
signal files are written to a fresh "generation" directory first; database
rows are replaced in a single transaction; only after a successful commit the
previous generation is removed.  A failure therefore never destroys the
previously stored state of a night.
"""

from __future__ import annotations

import logging
import re
from datetime import date

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cpap_parser import CPAPParser, FileSet, ParsedNight
from cpap_parser.channels import CHANNELS

from .. import storage
from ..analysis.metrics import compute_night_metrics, union_seconds
from ..config import get_settings
from ..models import (
    Device,
    Event,
    Night,
    NightMetric,
    NightSourceFile,
    SignalSegment,
    TherapySession,
    utcnow,
)

log = logging.getLogger(__name__)


def _events_available(parser: CPAPParser, parsed: ParsedNight) -> bool:
    return any(parser.classify(f).kind == "events" for f in parsed.source_files)


def rebuild_night(
    db: Session,
    device: Device,
    parser: CPAPParser,
    files: FileSet,
    night_date: date,
    raw_ids: dict[str, int],
    import_id: str | None,
) -> tuple[str, list[str]]:
    """Parse and store one night. Returns ("created"|"updated", warnings)."""
    parsed = parser.parse_night(files, night_date)
    settings = get_settings()
    computed = compute_night_metrics(parsed, _events_available(parser, parsed), settings.leak_threshold)

    existing = db.scalar(select(Night).where(Night.device_id == device.id, Night.date == night_date))
    old_gen = existing.storage_gen if existing else None
    gen = storage.new_generation()
    out_dir = storage.night_signal_dir(device.id, night_date, gen)

    # 1) write signal arrays (outside of the DB transaction)
    seg_specs = []
    try:
        for si, sess in enumerate(parsed.sessions):
            for gi, sig in enumerate(sess.signals):
                fname = f"s{si:02d}_{gi:02d}_{sig.channel}.npy"
                path = out_dir / fname
                storage.write_signal(path, sig.digital)
                phys = sig.physical()
                finite = phys[np.isfinite(phys)]
                seg_specs.append(
                    (
                        si,
                        dict(
                            channel=sig.channel,
                            label=sig.label[:64],
                            unit=sig.unit[:16],
                            sample_rate=sig.sample_rate,
                            start_ms=sig.start_ms,
                            end_ms=sig.end_ms,
                            n_samples=sig.n_samples,
                            gain=sig.gain,
                            offset=sig.offset,
                            invalid_digital=sig.invalid_digital,
                            physical_min=sig.physical_min,
                            physical_max=sig.physical_max,
                            vmin=float(finite.min()) if finite.size else None,
                            vmax=float(finite.max()) if finite.size else None,
                            vmean=float(finite.mean()) if finite.size else None,
                            path=storage.signal_rel(path),
                            source_file=sig.source_file,
                            raw_file_id=raw_ids.get(sig.source_file),
                            conversion=sig.conversion,
                        ),
                    )
                )
    except Exception:
        storage.remove_generation(device.id, night_date, gen)
        raise

    # 2) replace DB rows
    try:
        if existing is None:
            night = Night(
                owner_id=device.owner_id,
                device_id=device.id,
                date=night_date,
                parser=parser.name,
                parser_version=parser.version,
            )
            db.add(night)
            db.flush()
            status = "created"
        else:
            night = existing
            for model in (Event, SignalSegment, NightMetric, NightSourceFile):
                db.execute(delete(model).where(model.night_id == night.id))
            db.execute(delete(TherapySession).where(TherapySession.night_id == night.id))
            db.flush()
            status = "updated"

        detail_sessions = [s for s in parsed.sessions if s.source == "detail"]
        all_sessions = parsed.sessions
        night.start_ms = min((s.start_ms for s in all_sessions), default=None)
        night.end_ms = max((s.end_ms for s in all_sessions), default=None)
        night.usage_s = union_seconds((s.start_ms, s.end_ms) for s in (detail_sessions or all_sessions))
        night.session_count = len(detail_sessions or all_sessions)
        night.has_detail = bool(detail_sessions)
        night.has_summary = bool(parsed.device_metrics or parsed.settings)
        night.parser = parser.name
        night.parser_version = parser.version
        night.settings = parsed.settings
        night.summary_raw = parsed.summary_raw
        night.mask_intervals = [list(x) for x in parsed.mask_intervals]
        night.warnings = parsed.warnings[:200]
        night.storage_gen = gen
        night.updated_at = utcnow()
        if import_id:
            night.last_import_id = import_id

        session_rows = []
        for sess in parsed.sessions:
            row = TherapySession(
                night_id=night.id,
                start_ms=sess.start_ms,
                end_ms=sess.end_ms,
                duration_s=sess.duration_s,
                source=sess.source,
                files=sess.files,
            )
            db.add(row)
            session_rows.append(row)
        db.flush()

        channels: dict[str, dict] = {}
        for si, spec in seg_specs:
            db.add(SignalSegment(night_id=night.id, session_id=session_rows[si].id, **spec))
            ch = spec["channel"]
            base = ch if ch in CHANNELS else re.sub(r"_\d+$", "", ch)
            cdef = CHANNELS.get(base)
            if cdef is not None:
                name = cdef.name if base == ch else f"{cdef.name} ({ch.rsplit('_', 1)[1]})"
            else:
                name = spec["label"]
            info = channels.setdefault(
                ch,
                {
                    "code": ch,
                    "name": name,
                    "label": spec["label"],
                    "unit": spec["unit"],
                    "group": cdef.group if cdef else "other",
                    "sample_rate": spec["sample_rate"],
                    "min": spec["vmin"],
                    "max": spec["vmax"],
                    "conversion": spec["conversion"],
                },
            )
            for k, fn in (("min", min), ("max", max)):
                if spec[f"v{k}"] is not None:
                    info[k] = spec[f"v{k}"] if info[k] is None else fn(info[k], spec[f"v{k}"])
        night.channels = list(channels.values())

        for ev in parsed.events:
            sid = None
            for row, sess in zip(session_rows, parsed.sessions, strict=False):
                if sess.start_ms - 60000 <= ev.start_ms <= sess.end_ms + 60000:
                    sid = row.id
                    break
            db.add(
                Event(
                    night_id=night.id,
                    session_id=sid,
                    code=ev.code,
                    label=ev.label[:128],
                    onset_ms=ev.onset_ms,
                    start_ms=ev.start_ms,
                    end_ms=ev.end_ms,
                    duration_s=ev.duration_s,
                    source_file=ev.source_file,
                    raw_file_id=raw_ids.get(ev.source_file),
                )
            )
        for key, value in parsed.device_metrics.items():
            db.add(NightMetric(night_id=night.id, key=key, value=float(value), source="device"))
        for key, value in computed.items():
            db.add(NightMetric(night_id=night.id, key=key, value=float(value), source="computed"))
        for rel in sorted(set(parsed.source_files)):
            db.add(NightSourceFile(night_id=night.id, rel_path=rel, raw_file_id=raw_ids.get(rel)))
        db.commit()
    except Exception:
        db.rollback()
        storage.remove_generation(device.id, night_date, gen)
        raise

    if old_gen and old_gen != gen:
        storage.remove_generation(device.id, night_date, old_gen)
    return status, parsed.warnings
