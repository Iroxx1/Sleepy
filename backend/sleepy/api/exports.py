"""/api/export – analysed data (CSV/JSON/ZIP/Parquet) and original files."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import zipfile
from collections.abc import Iterator
from datetime import date, datetime, timezone

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from .. import storage
from ..analysis.timeseries import segment_physical
from ..config import get_settings
from ..models import Device, DeviceFile, Event, ImportFile, Night, RawFile, SignalSegment, User
from ..repo import display_metrics, metrics_for, nights_in_range
from .deps import audit, current_user, get_db
from .nights import get_night

router = APIRouter(prefix="/api/export", tags=["export"])


def iso(ms: int | None) -> str:
    if ms is None:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]


def nights_table(db: Session, user: User, d0, d1, device_id, both_sources: bool = False) -> tuple[list[str], list[dict]]:
    nights = nights_in_range(db, user, d0, d1, device_id)
    mm = metrics_for(db, [n.id for n in nights])
    rows = []
    keys: set[str] = set()
    for n in nights:
        m = mm.get(n.id, {"device": {}, "computed": {}})
        r = {
            "date": n.date.isoformat(),
            "device_id": n.device_id,
            "start": iso(n.start_ms),
            "end": iso(n.end_ms),
            "sessions": n.session_count,
            "has_detail": n.has_detail,
        }
        if both_sources:
            for src in ("device", "computed"):
                for k, v in m.get(src, {}).items():
                    r[f"{k}[{src}]"] = v
                    keys.add(f"{k}[{src}]")
        else:
            disp = display_metrics(m)
            r.update(disp)
            keys |= set(disp)
        rows.append(r)
    base = ["date", "device_id", "start", "end", "sessions", "has_detail"]
    return base + sorted(keys), rows


def to_csv(columns: list[str], rows: list[dict], sep: str = ",") -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, delimiter=sep, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in columns})
    return buf.getvalue()


def events_rows(db: Session, user: User, d0, d1, device_id) -> list[dict]:
    q = (
        select(Event, Night.date, Night.device_id)
        .join(Night, Night.id == Event.night_id)
        .where(Night.owner_id == user.id)
        .order_by(Event.start_ms)
    )
    if d0:
        q = q.where(Night.date >= d0)
    if d1:
        q = q.where(Night.date <= d1)
    if device_id:
        q = q.where(Night.device_id == device_id)
    return [
        {
            "night_date": d.isoformat(),
            "device_id": dev,
            "code": e.code,
            "label": e.label,
            "start": iso(e.start_ms),
            "end": iso(e.end_ms),
            "onset_raw": iso(e.onset_ms),
            "duration_s": e.duration_s,
            "source_file": e.source_file,
        }
        for e, d, dev in db.execute(q)
    ]


EVENT_COLUMNS = ["night_date", "device_id", "code", "label", "start", "end", "onset_raw", "duration_s", "source_file"]


@router.get("/nights.{fmt}")
def export_nights(
    fmt: str,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    device_id: int | None = None,
    both_sources: bool = False,
    sep: str = Query("comma", pattern="^(comma|semicolon)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    cols, rows = nights_table(db, user, date_from, date_to, device_id, both_sources)
    name = "sleepy-naechte"
    if fmt == "csv":
        return Response(to_csv(cols, rows, ";" if sep == "semicolon" else ","), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    if fmt == "json":
        return JSONResponse(rows, headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    if fmt == "parquet":
        try:
            import pandas as pd  # optional dependency
        except ImportError as exc:
            raise HTTPException(501, "Parquet-Export benötigt die optionalen Pakete pandas und pyarrow.") from exc
        buf = io.BytesIO()
        try:
            pd.DataFrame(rows, columns=cols).to_parquet(buf, index=False)
        except ImportError as exc:
            raise HTTPException(501, "Parquet-Export benötigt das optionale Paket pyarrow.") from exc
        return Response(buf.getvalue(), media_type="application/vnd.apache.parquet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.parquet"'})
    raise HTTPException(404, "Format nicht unterstützt (csv|json|parquet)")


@router.get("/events.{fmt}")
def export_events(
    fmt: str,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    device_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows = events_rows(db, user, date_from, date_to, device_id)
    if fmt == "csv":
        return Response(to_csv(EVENT_COLUMNS, rows), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="sleepy-ereignisse.csv"'})
    if fmt == "json":
        return JSONResponse(rows, headers={"Content-Disposition": 'attachment; filename="sleepy-ereignisse.json"'})
    raise HTTPException(404, "Format nicht unterstützt (csv|json)")


def _timeseries_csv(segs: list[SignalSegment]) -> Iterator[str]:
    yield "timestamp,channel,value,unit\n"
    for s in sorted(segs, key=lambda x: (x.channel, x.start_ms)):
        v = segment_physical(s)
        step = 1000.0 / s.sample_rate
        for i0 in range(0, v.size, 20000):
            chunk = v[i0: i0 + 20000]
            t = s.start_ms + (np.arange(i0, i0 + chunk.size) * step)
            lines = []
            for tt, vv in zip(t, chunk, strict=False):
                lines.append(f"{iso(int(round(tt)))},{s.channel},{'' if not np.isfinite(vv) else round(float(vv), 4)},{s.unit}\n")
            yield "".join(lines)


@router.get("/nights/{night_id}/timeseries.{fmt}")
def export_night_timeseries(
    night_id: int,
    fmt: str,
    channels: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    n = get_night(db, user, night_id)
    segs = list(db.scalars(select(SignalSegment).where(SignalSegment.night_id == n.id)))
    if channels:
        wanted = {c.strip() for c in channels.split(",")}
        segs = [s for s in segs if s.channel in wanted]
    fname = f"sleepy-{n.date.isoformat()}-zeitreihen"
    if fmt == "csv":
        return StreamingResponse(_timeseries_csv(segs), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'})
    if fmt == "json":
        out = {}
        for s in segs:
            v = segment_physical(s)
            out.setdefault(s.channel, []).append(
                {
                    "start": iso(s.start_ms),
                    "start_ms": s.start_ms,
                    "sample_rate_hz": s.sample_rate,
                    "unit": s.unit,
                    "label": s.label,
                    "values": [None if not np.isfinite(x) else round(float(x), 4) for x in v],
                }
            )
        return JSONResponse(out, headers={"Content-Disposition": f'attachment; filename="{fname}.json"'})
    raise HTTPException(404, "Format nicht unterstützt (csv|json)")


def _tmp_zip() -> tuple[zipfile.ZipFile, str]:
    d = get_settings().exports_dir
    d.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="export-", suffix=".zip", dir=d)
    os.close(fd)
    return zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6), path


@router.get("/archive.zip")
def export_archive(
    request: Request,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    device_id: int | None = None,
    timeseries: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Analysed data as ZIP: nights, events, settings and optionally all time series."""
    cols, rows = nights_table(db, user, date_from, date_to, device_id, both_sources=True)
    zf, path = _tmp_zip()
    with zf:
        zf.writestr("naechte.csv", to_csv(cols, rows))
        zf.writestr("naechte.json", json.dumps(rows, indent=1))
        zf.writestr("ereignisse.csv", to_csv(EVENT_COLUMNS, events_rows(db, user, date_from, date_to, device_id)))
        nights = nights_in_range(db, user, date_from, date_to, device_id)
        settings = {n.date.isoformat(): n.settings for n in nights if n.settings}
        zf.writestr("einstellungen.json", json.dumps(settings, indent=1))
        devices = [
            {"id": d.id, "manufacturer": d.manufacturer, "model": d.model, "serial": d.serial, "firmware": d.firmware,
             "identification": d.identification}
            for d in db.scalars(select(Device).where(Device.owner_id == user.id))
        ]
        zf.writestr("geraete.json", json.dumps(devices, indent=1))
        zf.writestr(
            "LIESMICH.txt",
            "Export aus Sleepy. Zeiten sind Gerätezeit (ohne Zeitzone).\n"
            "naechte.csv: Kennzahlen je Nacht; [device] = vom Gerät berechnet, [computed] = von Sleepy berechnet.\n"
            "ereignisse.csv: alle Ereignisse; onset_raw = Zeitpunkt wie in der Rohdatei gespeichert.\n"
            "zeitreihen/: (optional) alle Signale in voller Auflösung (timestamp,channel,value,unit).\n",
        )
        if timeseries:
            for n in nights:
                segs = list(db.scalars(select(SignalSegment).where(SignalSegment.night_id == n.id)))
                if segs:
                    with zf.open(f"zeitreihen/{n.date.isoformat()}_dev{n.device_id}.csv", "w") as fh:
                        for chunk in _timeseries_csv(segs):
                            fh.write(chunk.encode())
    audit(db, request, user, "export_archive", timeseries=timeseries)
    return FileResponse(path, filename="sleepy-export.zip", media_type="application/zip",
                        background=BackgroundTask(os.unlink, path))


@router.get("/raw.zip")
def export_raw(
    request: Request,
    device_id: int | None = None,
    import_id: str | None = None,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Original files as imported (unchanged bytes, original directory layout)."""
    entries: list[tuple[str, str]] = []  # (arcname, storage path)
    if import_id:
        rows = db.execute(
            select(ImportFile.path, RawFile.storage_path)
            .join(RawFile, RawFile.id == ImportFile.raw_file_id)
            .join(Device, Device.id == ImportFile.device_id, isouter=True)
            .where(ImportFile.import_id == import_id)
        ).all()
        from ..models import Import

        imp = db.get(Import, import_id)
        if imp is None or imp.owner_id != user.id:
            raise HTTPException(404, "Import nicht gefunden")
        entries = [(p, sp) for p, sp in rows]
    else:
        devs = [d for d in db.scalars(select(Device).where(Device.owner_id == user.id))
                if device_id is None or d.id == device_id]
        if not devs:
            raise HTTPException(404, "Kein Gerät gefunden")
        for d in devs:
            rows = db.execute(
                select(DeviceFile.rel_path, RawFile.storage_path)
                .join(RawFile, RawFile.id == DeviceFile.raw_file_id)
                .where(DeviceFile.device_id == d.id)
                .order_by(DeviceFile.created_at, DeviceFile.id)
            ).all()
            latest: dict[str, str] = {}
            for rel, sp in rows:
                latest[rel] = sp
            prefix = f"{d.manufacturer}_{d.serial}/" if len(devs) > 1 else ""
            for rel, sp in sorted(latest.items()):
                if (date_from or date_to) and rel.lower().startswith("datalog/"):
                    parts = rel.split("/")
                    day = None
                    if len(parts) >= 3 and parts[1].isdigit() and len(parts[1]) == 8:
                        day = date(int(parts[1][:4]), int(parts[1][4:6]), int(parts[1][6:]))
                    if day and ((date_from and day < date_from) or (date_to and day > date_to)):
                        continue
                entries.append((prefix + rel, sp))
    if not entries:
        raise HTTPException(404, "Keine Dateien für diese Auswahl")
    zf, path = _tmp_zip()
    with zf:
        for arc, sp in entries:
            zf.write(storage.raw_abs_path(sp), arcname=arc)
    audit(db, request, user, "export_raw", device_id=device_id, import_id=import_id, files=len(entries))
    return FileResponse(path, filename="sleepy-originaldaten.zip", media_type="application/zip",
                        background=BackgroundTask(os.unlink, path))


@router.get("/formats")
def formats(user: User = Depends(current_user)):
    try:
        import pandas  # noqa: F401
        import pyarrow  # noqa: F401

        parquet = True
    except ImportError:
        parquet = False
    return {"csv": True, "json": True, "zip": True, "parquet": parquet}
