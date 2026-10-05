"""/api/nights, /api/events – single night analysis, lists, search, compare."""

from __future__ import annotations

from collections import Counter
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cpap_parser.channels import AHI_EVENTS, EVENTS
from cpap_parser.resmed.labels import SETTING_NAMES

from ..analysis import insights as ins
from ..analysis.metrics import metric_info
from ..analysis.timeseries import ChannelCache, series
from ..config import get_settings
from ..models import Device, DeviceFile, Event, Night, NightSourceFile, RawFile, SignalSegment, User
from ..repo import (
    detailed_metrics,
    display_metrics,
    filter_nights,
    history_metrics,
    metrics_for,
    night_row,
    thresholds_for,
)
from .deps import current_user, get_db
from .query import QueryError, parse_query

router = APIRouter(prefix="/api", tags=["nights"])


def get_night(db: Session, user: User, night_id: int) -> Night:
    n = db.get(Night, night_id)
    if n is None or n.owner_id != user.id:
        raise HTTPException(404, "Nacht nicht gefunden")
    return n


def device_out(d: Device | None) -> dict | None:
    if d is None:
        return None
    return {
        "id": d.id,
        "manufacturer": d.manufacturer,
        "model": d.model,
        "serial": d.serial,
        "display_name": d.display_name,
        "device_type": d.device_type,
    }


def _resolve_device(db: Session, user: User, dev: str | None) -> int | None:
    if not dev:
        return None
    q = select(Device).where(Device.owner_id == user.id)
    d = db.scalar(q.where(Device.serial == dev))
    if d is None and dev.isdigit():
        d = db.scalar(q.where(Device.id == int(dev)))
    if d is None:
        raise HTTPException(400, f"Gerät '{dev}' nicht gefunden")
    return d.id


# ----------------------------------------------------------------- listing
@router.get("/nights")
def list_nights(
    q: str | None = Query(None, description="Suchsprache, z. B. 'ahi>5 2026-09'"),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    device_id: int | None = None,
    ahi_min: float | None = None,
    ahi_max: float | None = None,
    leak_min: float | None = None,
    leak_max: float | None = None,
    pressure_min: float | None = None,
    pressure_max: float | None = None,
    usage_min: float | None = None,
    usage_max: float | None = None,
    event: str | None = Query(None, description="Ereignistyp(en), kommasepariert, z. B. CA,OA"),
    event_min: int = 1,
    sort: str = "date",
    order: str = "desc",
    offset: int = 0,
    limit: int = Query(100, le=5000),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    ranges: dict[str, tuple] = {}
    codes = [c.strip().upper() for c in event.split(",")] if event else []
    has_notes = None
    for key, lo, hi in (
        ("ahi", ahi_min, ahi_max),
        ("leak.p95", leak_min, leak_max),
        ("pressure.p95", pressure_min, pressure_max),
        ("usage_h", usage_min, usage_max),
    ):
        if lo is not None or hi is not None:
            ranges[key] = (lo, hi)
    if q:
        try:
            pq = parse_query(q)
        except QueryError as exc:
            raise HTTPException(400, str(exc)) from exc
        date_from = pq.date_from or date_from
        date_to = pq.date_to or date_to
        for k, v in pq.ranges.items():
            ranges[k] = tuple(v)
        codes += pq.event_codes
        if pq.event_codes:
            event_min = pq.event_min
        if pq.device:
            device_id = _resolve_device(db, user, pq.device)
        has_notes = pq.has_notes
    nights = filter_nights(
        db, user, date_from=date_from, date_to=date_to, device_id=device_id, ranges=ranges,
        event_codes=codes or None, event_min=event_min, has_notes=has_notes,
    )
    mm = metrics_for(db, [n.id for n in nights])
    th = thresholds_for(user)
    rows = [night_row(n, mm.get(n.id, {"device": {}, "computed": {}}), th) for n in nights]

    def sort_key(r):
        if sort == "date":
            return r["date"]
        if sort == "usage":
            return r["usage_h"] if r["usage_h"] is not None else -1
        v = r["metrics"].get(sort)
        return v if v is not None else -1e9

    rows.sort(key=sort_key, reverse=(order == "desc"))
    return {"total": len(rows), "items": rows[offset: offset + limit]}


@router.get("/nights/calendar")
def calendar(
    date_from: date = Query(..., alias="from"),
    date_to: date = Query(..., alias="to"),
    device_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if (date_to - date_from).days > 800:
        raise HTTPException(400, "Zeitraum zu groß")
    nights = filter_nights(db, user, date_from=date_from, date_to=date_to, device_id=device_id)
    mm = metrics_for(db, [n.id for n in nights])
    th = thresholds_for(user)
    out = []
    for n in nights:
        r = night_row(n, mm.get(n.id, {"device": {}, "computed": {}}), th)
        out.append(
            {
                "id": n.id,
                "date": r["date"],
                "device_id": n.device_id,
                "status": r["status"],
                "ahi": r["metrics"].get("ahi"),
                "usage_h": r["usage_h"],
                "leak_p95": r["metrics"].get("leak.p95"),
            }
        )
    return {"thresholds": th, "days": out}


@router.get("/nights/by-date/{day}")
def by_date(day: date, device_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Night).where(Night.owner_id == user.id, Night.date == day)
    if device_id:
        q = q.where(Night.device_id == device_id)
    n = db.scalars(q.order_by(Night.device_id)).first()
    if n is None:
        raise HTTPException(404, "Keine Daten für diesen Tag")
    return {"id": n.id}


@router.get("/nights/compare")
def compare(ids: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()][:12]
    except ValueError as exc:
        raise HTTPException(400, "ids muss eine kommaseparierte Liste sein") from exc
    nights = [get_night(db, user, i) for i in id_list]
    mm = metrics_for(db, id_list)
    th = thresholds_for(user)
    counts = {
        nid: dict(Counter(c for (c,) in db.execute(select(Event.code).where(Event.night_id == nid))))
        for nid in id_list
    }
    keys: set[str] = set()
    items = []
    for n in nights:
        m = mm.get(n.id, {"device": {}, "computed": {}})
        disp = display_metrics(m)
        keys |= set(disp)
        items.append({**night_row(n, m, th), "all_metrics": disp, "event_counts": counts.get(n.id, {})})
    ordered = sorted(keys, key=_metric_sort_key)
    return {"items": items, "metrics": [metric_info(k) for k in ordered]}


def _metric_sort_key(k: str):
    order = ["usage_h", "ahi", "ai", "hi", "oai", "cai", "uai", "rera_index", "rdi", "odi", "csr_pct"]
    if k in order:
        return (0, order.index(k), k)
    if k.startswith("count."):
        return (2, 0, k)
    return (1, 0, k)


# ------------------------------------------------------------------ detail
@router.get("/nights/{night_id}")
def night_detail(night_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = get_night(db, user, night_id)
    mm = metrics_for(db, [n.id]).get(n.id, {"device": {}, "computed": {}})
    th = thresholds_for(user)
    row = night_row(n, mm, th)
    prev_n = db.scalar(
        select(Night).where(Night.owner_id == user.id, Night.device_id == n.device_id, Night.date < n.date)
        .order_by(Night.date.desc()).limit(1)
    )
    next_n = db.scalar(
        select(Night).where(Night.owner_id == user.id, Night.device_id == n.device_id, Night.date > n.date)
        .order_by(Night.date).limit(1)
    )
    ev_counts = dict(
        db.execute(select(Event.code, func.count()).where(Event.night_id == n.id).group_by(Event.code)).all()
    )
    sources = []
    for sf in db.scalars(select(NightSourceFile).where(NightSourceFile.night_id == n.id).order_by(NightSourceFile.rel_path)):
        raw = db.get(RawFile, sf.raw_file_id) if sf.raw_file_id else None
        df = (
            db.scalar(
                select(DeviceFile).where(
                    DeviceFile.device_id == n.device_id,
                    DeviceFile.rel_path == sf.rel_path,
                    DeviceFile.raw_file_id == sf.raw_file_id,
                )
            )
            if sf.raw_file_id
            else None
        )
        sources.append(
            {
                "rel_path": sf.rel_path,
                "sha256": raw.sha256 if raw else None,
                "size": raw.size if raw else None,
                "import_id": df.import_id if df else None,
                "imported_at": df.created_at.isoformat() if df else None,
            }
        )
    settings_out = []
    for k, v in sorted((n.settings or {}).items()):
        settings_out.append({"key": k, "label": SETTING_NAMES.get(k, k), "value": v})
    return {
        "night": {
            **row,
            "device": device_out(n.device),
            "parser": n.parser,
            "parser_version": n.parser_version,
            "notes_text": n.notes,
            "warnings": n.warnings or [],
            "updated_at": n.updated_at.isoformat() if n.updated_at else None,
            "mask_intervals": n.mask_intervals or [],
        },
        "metrics": detailed_metrics(mm),
        "sessions": [
            {"id": s.id, "start_ms": s.start_ms, "end_ms": s.end_ms, "duration_s": s.duration_s, "source": s.source,
             "files": s.files}
            for s in n.sessions
        ],
        "channels": n.channels or [],
        "event_counts": ev_counts,
        "settings": settings_out,
        "summary_raw": n.summary_raw or {},
        "source_files": sources,
        "prev_id": prev_n.id if prev_n else None,
        "next_id": next_n.id if next_n else None,
        "leak_threshold": get_settings().leak_threshold,
        "disclaimer": ins.DISCLAIMER,
    }


class NotesIn(BaseModel):
    notes: str | None = Field(None, max_length=20000)


@router.patch("/nights/{night_id}")
def update_night(night_id: int, body: NotesIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = get_night(db, user, night_id)
    n.notes = (body.notes or "").strip() or None
    db.commit()
    return {"ok": True, "notes": n.notes}


def _segments(db: Session, night_id: int) -> list[SignalSegment]:
    return list(db.scalars(select(SignalSegment).where(SignalSegment.night_id == night_id)))


def _events(db: Session, night_id: int) -> list[Event]:
    return list(db.scalars(select(Event).where(Event.night_id == night_id).order_by(Event.start_ms)))


@router.get("/nights/{night_id}/events")
def night_events(night_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = get_night(db, user, night_id)
    evs = _events(db, n.id)
    low_rate = [s for s in _segments(db, n.id) if s.sample_rate <= 2]
    cache = ChannelCache(low_rate)
    ctx_channels = [c for c in ("pressure", "epap", "leak", "flow_limit", "spo2") if cache.has(c)]
    items = []
    for e in evs:
        ctx = {}
        a, b = (e.start_ms, e.end_ms) if e.end_ms > e.start_ms else (e.start_ms - 5000, e.start_ms + 5000)
        for c in ctx_channels:
            v = cache.mean_between(c, a, b)
            if v is not None:
                ctx[c] = round(v, 2)
        items.append(
            {
                "id": e.id,
                "code": e.code,
                "label": e.label,
                "start_ms": e.start_ms,
                "end_ms": e.end_ms,
                "onset_ms": e.onset_ms,
                "duration_s": e.duration_s,
                "session_id": e.session_id,
                "source_file": e.source_file,
                "context": ctx,
            }
        )
    return {
        "items": items,
        "context_channels": ctx_channels,
        "types": {c: {"name": d.name, "short": d.short, "color": d.color, "span": d.span} for c, d in EVENTS.items()},
    }


@router.get("/nights/{night_id}/timeseries")
def night_timeseries(
    night_id: int,
    channels: str = Query(..., description="kommaseparierte Kanalcodes"),
    start: int | None = Query(None, description="Start (Wall-Clock-ms)"),
    end: int | None = Query(None, description="Ende (Wall-Clock-ms)"),
    points: int = Query(1500, ge=50, le=20000),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    n = get_night(db, user, night_id)
    wanted = [c.strip() for c in channels.split(",") if c.strip()][:24]
    segs = [s for s in _segments(db, n.id) if s.channel in wanted]
    meta = {c["code"]: c for c in (n.channels or [])}
    out = {}
    for ch in wanted:
        cs = [s for s in segs if s.channel == ch]
        if not cs:
            continue
        data = series(cs, start, end, points)
        out[ch] = {"unit": cs[0].unit, "name": meta.get(ch, {}).get("name", ch), **data}
    return {"start": start, "end": end, "channels": out}


@router.get("/nights/{night_id}/insights")
def night_insights(night_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = get_night(db, user, night_id)
    mm = metrics_for(db, [n.id]).get(n.id, {"device": {}, "computed": {}})
    disp = display_metrics(mm)
    evs = [ins.Ev(e.code, e.start_ms, e.end_ms, e.duration_s) for e in _events(db, n.id)]
    cache = ChannelCache([s for s in _segments(db, n.id) if s.sample_rate <= 2])
    lt = get_settings().leak_threshold
    hist, n_hist = history_metrics(db, user, n.device_id, n.date, 30)
    baseline = {k: sum(v) / len(v) for k, v in hist.items() if v}
    units = {k: metric_info(k)["unit"] for k in disp}
    ahi_evs = [e for e in evs if e.code in AHI_EVENTS]
    return {
        "summary": ins.summary_text(disp, baseline, n_hist, n.session_count, evs, lt, n.start_ms, n.end_ms),
        "observations": ins.observations(evs, cache, lt, n.start_ms, n.end_ms),
        "clusters": ins.find_clusters(evs),
        "hourly": ins.hourly_counts(evs, n.start_ms, n.end_ms),
        "anomalies": ins.anomalies(disp, hist, units),
        "peri_event": ins.peri_event(cache, evs),
        "baseline": {"nights": n_hist, "ahi_mean": baseline.get("ahi"), "usage_mean": baseline.get("usage_h"),
                     "leak_p95_mean": baseline.get("leak.p95")},
        "n_ahi_events": len(ahi_evs),
        "disclaimer": ins.DISCLAIMER,
    }


# ---------------------------------------------------------- global events
@router.get("/events")
def search_events(
    code: str | None = None,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    device_id: int | None = None,
    min_duration: float | None = None,
    offset: int = 0,
    limit: int = Query(500, le=10000),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = (
        select(Event, Night.date, Night.device_id)
        .join(Night, Night.id == Event.night_id)
        .where(Night.owner_id == user.id)
    )
    if code:
        q = q.where(Event.code.in_([c.strip().upper() for c in code.split(",")]))
    if date_from:
        q = q.where(Night.date >= date_from)
    if date_to:
        q = q.where(Night.date <= date_to)
    if device_id:
        q = q.where(Night.device_id == device_id)
    if min_duration is not None:
        q = q.where(Event.duration_s >= min_duration)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.execute(q.order_by(Event.start_ms.desc()).offset(offset).limit(limit)).all()
    return {
        "total": total,
        "items": [
            {
                "id": e.id,
                "night_id": e.night_id,
                "date": d.isoformat(),
                "device_id": dev,
                "code": e.code,
                "label": e.label,
                "start_ms": e.start_ms,
                "end_ms": e.end_ms,
                "duration_s": e.duration_s,
            }
            for e, d, dev in rows
        ],
    }


@router.get("/events/types")
def event_types(user: User = Depends(current_user)):
    return {c: {"name": d.name, "short": d.short, "color": d.color, "span": d.span, "ahi": d.apnea_hypopnea}
            for c, d in EVENTS.items()}

