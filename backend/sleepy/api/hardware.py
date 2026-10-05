"""/api/hardware – equipment inventory (masks, tubes, filters, device) and
manually recorded counters such as the blower/turbine hours of the device.

All "due" information is based on intervals the user enters himself; Sleepy
does not ship manufacturer replacement intervals or blower lifetimes.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysis.metrics import metric_info
from ..analysis.stats import describe_values
from ..models import Device, HardwareItem, HardwareReading, User, utcnow
from ..repo import display_metrics, metrics_for, nights_in_range
from .deps import current_user, get_db

router = APIRouter(prefix="/api/hardware", tags=["hardware"])

CATEGORIES = {
    "device": "PAP-Gerät",
    "mask": "Maske",
    "cushion": "Maskenkissen / Polster",
    "headgear": "Kopfband",
    "tube": "Schlauch",
    "filter": "Filter",
    "humidifier": "Befeuchter / Wasserkammer",
    "oximeter": "Pulsoximeter",
    "other": "Sonstiges",
}
READING_KINDS = {
    "blower_hours": "Turbinen-/Gebläselaufzeit (h)",
    "device_hours": "Gerätelaufzeit (h)",
    "therapy_hours": "Therapiestunden laut Gerät (h)",
    "other": "Sonstiger Zählerstand",
}
IMPACT_KEYS = ["usage_h", "ahi", "leak.median", "leak.p95", "pressure.median", "pressure.p95", "flow_limit.p95"]


class ItemIn(BaseModel):
    category: str = Field(pattern="^(" + "|".join(CATEGORIES) + ")$")
    name: str = Field(min_length=1, max_length=128)
    manufacturer: str | None = Field(None, max_length=128)
    model: str | None = Field(None, max_length=128)
    size: str | None = Field(None, max_length=32)
    serial: str | None = Field(None, max_length=64)
    device_id: int | None = None
    started_on: date | None = None
    ended_on: date | None = None
    replace_after_days: int | None = Field(None, ge=1, le=3650)
    expected_hours: float | None = Field(None, gt=0, le=1_000_000)
    notes: str | None = Field(None, max_length=5000)


class ItemPatch(BaseModel):
    category: str | None = Field(None, pattern="^(" + "|".join(CATEGORIES) + ")$")
    name: str | None = Field(None, min_length=1, max_length=128)
    manufacturer: str | None = Field(None, max_length=128)
    model: str | None = Field(None, max_length=128)
    size: str | None = Field(None, max_length=32)
    serial: str | None = Field(None, max_length=64)
    device_id: int | None = None
    started_on: date | None = None
    ended_on: date | None = None
    replace_after_days: int | None = Field(None, ge=1, le=3650)
    expected_hours: float | None = Field(None, gt=0, le=1_000_000)
    notes: str | None = Field(None, max_length=5000)


class ReadingIn(BaseModel):
    read_on: date
    value: float = Field(ge=0, le=10_000_000)
    kind: str = Field("blower_hours", pattern="^(" + "|".join(READING_KINDS) + ")$")
    note: str | None = Field(None, max_length=255)


class ReplaceIn(BaseModel):
    started_on: date
    name: str | None = Field(None, max_length=128)
    size: str | None = Field(None, max_length=32)
    serial: str | None = Field(None, max_length=64)
    notes: str | None = Field(None, max_length=5000)


def _item(db: Session, user: User, item_id: int) -> HardwareItem:
    it = db.get(HardwareItem, item_id)
    if it is None or it.owner_id != user.id:
        raise HTTPException(404, "Eintrag nicht gefunden")
    return it


def _check_device(db: Session, user: User, device_id: int | None) -> None:
    if device_id is not None:
        d = db.get(Device, device_id)
        if d is None or d.owner_id != user.id:
            raise HTTPException(400, "Gerät nicht gefunden")


def _validate_dates(started: date | None, ended: date | None) -> None:
    if started and ended and ended < started:
        raise HTTPException(400, "Das Enddatum liegt vor dem Startdatum.")


def therapy_hours(db: Session, user: User, start: date, end: date, device_id: int | None) -> tuple[float, int]:
    nights = nights_in_range(db, user, start, end, device_id)
    mm = metrics_for(db, [n.id for n in nights])
    hours = 0.0
    used = 0
    for n in nights:
        u = display_metrics(mm.get(n.id, {"device": {}, "computed": {}})).get("usage_h")
        if u:
            hours += u
            used += 1
    return hours, used


def reading_stats(item: HardwareItem, kind: str) -> dict | None:
    rs = [r for r in item.readings if r.kind == kind]
    if not rs:
        return None
    rs.sort(key=lambda r: (r.read_on, r.id))
    last = rs[-1]
    out: dict = {"kind": kind, "label": READING_KINDS.get(kind, kind), "count": len(rs), "latest_value": last.value,
                 "latest_on": last.read_on.isoformat(), "per_day": None, "projection": None}
    first = rs[0]
    days = (last.read_on - first.read_on).days
    if days > 0 and last.value >= first.value:
        per_day = (last.value - first.value) / days
        out["per_day"] = per_day
        if item.expected_hours and per_day > 0:
            remaining = item.expected_hours - last.value
            out["projection"] = {
                "expected_hours": item.expected_hours,
                "pct_used": 100.0 * last.value / item.expected_hours,
                "remaining_hours": remaining,
                "estimated_date": (last.read_on + timedelta(days=max(0, remaining) / per_day)).isoformat()
                if remaining > 0 else None,
            }
    elif item.expected_hours:
        out["projection"] = {
            "expected_hours": item.expected_hours,
            "pct_used": 100.0 * last.value / item.expected_hours,
            "remaining_hours": item.expected_hours - last.value,
            "estimated_date": None,
        }
    # plausibility: decreasing counter (device replaced or typo)
    out["decreasing"] = any(b.value < a.value for a, b in zip(rs, rs[1:], strict=False))
    return out


def item_out(db: Session, user: User, it: HardwareItem, today: date | None = None) -> dict:
    today = today or date.today()
    end = it.ended_on or today
    age_days = (end - it.started_on).days if it.started_on else None
    due = None
    if it.started_on and it.replace_after_days and it.ended_on is None:
        due_on = it.started_on + timedelta(days=it.replace_after_days)
        left = (due_on - today).days
        due = {"due_on": due_on.isoformat(), "days_left": left,
               "status": "due" if left < 0 else "soon" if left <= 14 else "ok"}
    usage = None
    if it.started_on:
        h, n = therapy_hours(db, user, it.started_on, end, it.device_id)
        usage = {"hours": h, "nights": n}
    stats = {k: s for k in READING_KINDS if (s := reading_stats(it, k))}
    return {
        "id": it.id,
        "category": it.category,
        "category_label": CATEGORIES.get(it.category, it.category),
        "name": it.name,
        "manufacturer": it.manufacturer,
        "model": it.model,
        "size": it.size,
        "serial": it.serial,
        "device_id": it.device_id,
        "started_on": it.started_on.isoformat() if it.started_on else None,
        "ended_on": it.ended_on.isoformat() if it.ended_on else None,
        "active": it.ended_on is None,
        "age_days": age_days,
        "replace_after_days": it.replace_after_days,
        "expected_hours": it.expected_hours,
        "due": due,
        "therapy_usage": usage,
        "notes": it.notes,
        "readings": [
            {"id": r.id, "read_on": r.read_on.isoformat(), "kind": r.kind, "value": r.value, "note": r.note}
            for r in sorted(it.readings, key=lambda r: (r.read_on, r.id))
        ],
        "reading_stats": stats,
    }


@router.get("")
def list_items(include_inactive: bool = True, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(HardwareItem).where(HardwareItem.owner_id == user.id)
    if not include_inactive:
        q = q.where(HardwareItem.ended_on.is_(None))
    items = list(db.scalars(q))
    items.sort(key=lambda i: (i.ended_on is not None, i.category, -(i.started_on or date.min).toordinal()))
    return {
        "items": [item_out(db, user, i) for i in items],
        "categories": CATEGORIES,
        "reading_kinds": READING_KINDS,
    }


@router.post("")
def create_item(body: ItemIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_device(db, user, body.device_id)
    _validate_dates(body.started_on, body.ended_on)
    it = HardwareItem(owner_id=user.id, **body.model_dump())
    db.add(it)
    db.commit()
    return item_out(db, user, it)


@router.get("/timeline")
def timeline(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Start/end dates of equipment, e.g. as markers in trend charts."""
    out = []
    for it in db.scalars(select(HardwareItem).where(HardwareItem.owner_id == user.id)):
        for kind, d in (("start", it.started_on), ("end", it.ended_on)):
            if d and (not date_from or d >= date_from) and (not date_to or d <= date_to):
                out.append({"date": d.isoformat(), "kind": kind, "item_id": it.id, "name": it.name,
                            "category": it.category, "category_label": CATEGORIES.get(it.category, it.category)})
    out.sort(key=lambda x: x["date"])
    return out


@router.get("/{item_id}")
def get_item(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return item_out(db, user, _item(db, user, item_id))


@router.patch("/{item_id}")
def update_item(item_id: int, body: ItemPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    it = _item(db, user, item_id)
    data = body.model_dump(exclude_unset=True)
    if "device_id" in data:
        _check_device(db, user, data["device_id"])
    for k, v in data.items():
        setattr(it, k, v)
    _validate_dates(it.started_on, it.ended_on)
    it.updated_at = utcnow()
    db.commit()
    return item_out(db, user, it)


@router.delete("/{item_id}")
def delete_item(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    it = _item(db, user, item_id)
    db.delete(it)
    db.commit()
    return {"ok": True}


@router.post("/{item_id}/replace")
def replace_item(item_id: int, body: ReplaceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Retire an item and create its successor (e.g. the yearly new mask)."""
    old = _item(db, user, item_id)
    if old.started_on and body.started_on <= old.started_on:
        raise HTTPException(400, "Das neue Startdatum muss nach dem Start des bisherigen Eintrags liegen.")
    old.ended_on = body.started_on - timedelta(days=1)
    old.updated_at = utcnow()
    new = HardwareItem(
        owner_id=user.id,
        category=old.category,
        name=body.name or old.name,
        manufacturer=old.manufacturer,
        model=old.model,
        size=body.size if body.size is not None else old.size,
        serial=body.serial,
        device_id=old.device_id,
        started_on=body.started_on,
        replace_after_days=old.replace_after_days,
        expected_hours=old.expected_hours,
        notes=body.notes,
    )
    db.add(new)
    db.commit()
    return {"old": item_out(db, user, old), "new": item_out(db, user, new)}


@router.post("/{item_id}/readings")
def add_reading(item_id: int, body: ReadingIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    it = _item(db, user, item_id)
    db.add(HardwareReading(item_id=it.id, **body.model_dump()))
    db.commit()
    db.refresh(it)
    return item_out(db, user, it)


@router.delete("/{item_id}/readings/{reading_id}")
def delete_reading(item_id: int, reading_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    it = _item(db, user, item_id)
    r = db.get(HardwareReading, reading_id)
    if r is None or r.item_id != it.id:
        raise HTTPException(404, "Ablesung nicht gefunden")
    db.delete(r)
    db.commit()
    db.refresh(it)
    return item_out(db, user, it)


@router.get("/{item_id}/impact")
def impact(item_id: int, days: int = Query(30, ge=7, le=180), user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    """Statistical comparison of key metrics before vs. after the start date."""
    it = _item(db, user, item_id)
    if not it.started_on:
        raise HTTPException(400, "Kein Startdatum hinterlegt.")
    s = it.started_on
    before = nights_in_range(db, user, s - timedelta(days=days), s - timedelta(days=1), it.device_id)
    after_end = min(s + timedelta(days=days - 1), it.ended_on or date.max)
    after = nights_in_range(db, user, s, after_end, it.device_id)
    mm = metrics_for(db, [n.id for n in before + after])

    def collect(nights):
        vals: dict[str, list[float]] = {k: [] for k in IMPACT_KEYS}
        for n in nights:
            disp = display_metrics(mm.get(n.id, {"device": {}, "computed": {}}))
            if not disp.get("usage_h"):
                continue
            for k in IMPACT_KEYS:
                if k in disp:
                    vals[k].append(disp[k])
        return vals

    b, a = collect(before), collect(after)
    rows = []
    for k in IMPACT_KEYS:
        sb, sa = describe_values(b[k]), describe_values(a[k])
        if not sb and not sa:
            continue
        rows.append({**metric_info(k), "before": sb, "after": sa,
                     "diff_median": (sa["median"] - sb["median"]) if sa and sb else None})
    return {
        "item_id": it.id,
        "days": days,
        "before": {"from": (s - timedelta(days=days)).isoformat(), "to": (s - timedelta(days=1)).isoformat()},
        "after": {"from": s.isoformat(), "to": after_end.isoformat()},
        "metrics": rows,
        "note": "Rein statistischer Vergleich der Zeiträume vor und nach dem Startdatum – andere Einflüsse "
                "(Erkältung, Einstellungen, Schlafposition …) sind nicht berücksichtigt.",
    }
