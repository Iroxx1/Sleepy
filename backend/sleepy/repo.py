"""Query helpers shared by API, reports and exports."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, timedelta

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from .analysis.insights import DEFAULT_THRESHOLDS, night_status
from .analysis.metrics import metric_info, pick
from .config import get_settings
from .models import Device, Event, Night, NightMetric, User

MetricMap = dict[str, dict[str, float]]


def thresholds_for(user: User) -> dict:
    prefs = user.preferences or {}
    th = dict(DEFAULT_THRESHOLDS)
    th["leak_p95_max"] = get_settings().leak_threshold
    th.update({k: float(v) for k, v in (prefs.get("thresholds") or {}).items() if k in th})
    return th


def metrics_for(db: Session, night_ids: Iterable[int]) -> dict[int, MetricMap]:
    ids = list(night_ids)
    out: dict[int, MetricMap] = defaultdict(lambda: {"device": {}, "computed": {}})
    for chunk in range(0, len(ids), 500):
        part = ids[chunk: chunk + 500]
        if not part:
            continue
        rows = db.execute(
            select(NightMetric.night_id, NightMetric.key, NightMetric.value, NightMetric.source).where(
                NightMetric.night_id.in_(part)
            )
        )
        for nid, key, value, source in rows:
            out[nid].setdefault(source, {})[key] = value
    return out


def display_metrics(mm: MetricMap) -> dict[str, float]:
    """Flatten to the preferred value per key."""
    keys = set(mm.get("device", {})) | set(mm.get("computed", {}))
    out = {}
    for k in keys:
        v, _ = pick(mm, k)
        if v is not None:
            out[k] = v
    return out


def detailed_metrics(mm: MetricMap) -> list[dict]:
    keys = sorted(set(mm.get("device", {})) | set(mm.get("computed", {})))
    out = []
    for k in keys:
        v, src = pick(mm, k)
        info = metric_info(k)
        out.append(
            {
                **info,
                "value": v,
                "source": src,
                "device": mm.get("device", {}).get(k),
                "computed": mm.get("computed", {}).get(k),
            }
        )
    return out


def user_devices(db: Session, user: User) -> list[Device]:
    return list(db.scalars(select(Device).where(Device.owner_id == user.id).order_by(Device.last_seen_at.desc())))


def nights_in_range(
    db: Session,
    user: User,
    date_from: date | None = None,
    date_to: date | None = None,
    device_id: int | None = None,
) -> list[Night]:
    q = select(Night).where(Night.owner_id == user.id)
    if device_id:
        q = q.where(Night.device_id == device_id)
    if date_from:
        q = q.where(Night.date >= date_from)
    if date_to:
        q = q.where(Night.date <= date_to)
    return list(db.scalars(q.order_by(Night.date)))


def night_row(n: Night, mm: MetricMap, thresholds: dict) -> dict:
    disp = display_metrics(mm)
    return {
        "id": n.id,
        "date": n.date.isoformat(),
        "device_id": n.device_id,
        "start_ms": n.start_ms,
        "end_ms": n.end_ms,
        "usage_h": disp.get("usage_h"),
        "session_count": n.session_count,
        "has_detail": n.has_detail,
        "has_summary": n.has_summary,
        "status": night_status(disp, bool(n.session_count or disp.get("usage_h")), thresholds),
        "metrics": {
            k: disp.get(k)
            for k in (
                "ahi", "ai", "hi", "oai", "cai", "uai", "rera_index", "rdi", "odi",
                "leak.median", "leak.p95", "leak.max", "pressure.median", "pressure.p95", "pressure.max",
                "epap.median", "epap.p95", "flow_limit.p95", "flow_limit.median", "snore.p95",
                "resp_rate.median", "tidal_volume.median", "minute_vent.median", "spo2.median",
                "pulse.mean", "csr_pct", "mask_pressure.median",
            )
            if disp.get(k) is not None
        },
        "notes": bool(n.notes),
    }


# --------------------------------------------------------------- filtering
FILTER_KEYS = {
    "ahi": "ahi",
    "cai": "cai",
    "oai": "oai",
    "hi": "hi",
    "rdi": "rdi",
    "leak": "leak.p95",
    "leak_median": "leak.median",
    "pressure": "pressure.p95",
    "pressure_median": "pressure.median",
    "usage": "usage_h",
    "fl": "flow_limit.p95",
    "spo2": "spo2.median",
}


def filter_nights(
    db: Session,
    user: User,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    device_id: int | None = None,
    ranges: dict[str, tuple[float | None, float | None]] | None = None,
    event_codes: Sequence[str] | None = None,
    event_min: int = 1,
    has_notes: bool | None = None,
) -> list[Night]:
    nights = nights_in_range(db, user, date_from, date_to, device_id)
    if not nights:
        return []
    ids = [n.id for n in nights]
    keep = set(ids)
    if ranges:
        mm = metrics_for(db, ids)
        for nid in list(keep):
            disp = display_metrics(mm.get(nid, {"device": {}, "computed": {}}))
            for key, (lo, hi) in ranges.items():
                v = disp.get(key)
                if v is None or (lo is not None and v < lo) or (hi is not None and v > hi):
                    keep.discard(nid)
                    break
    if event_codes:
        rows = db.execute(
            select(Event.night_id, Event.code, func.count())
            .where(Event.night_id.in_(list(keep)), Event.code.in_(list(event_codes)))
            .group_by(Event.night_id, Event.code)
        )
        counts: dict[int, int] = defaultdict(int)
        for nid, _code, c in rows:
            counts[nid] += c
        keep = {nid for nid in keep if counts.get(nid, 0) >= event_min}
    if has_notes is not None:
        keep = {n.id for n in nights if n.id in keep and bool(n.notes) == has_notes}
    return [n for n in nights if n.id in keep]


def history_metrics(
    db: Session, user: User, device_id: int, before: date, days: int = 30
) -> tuple[dict[str, list[float]], int]:
    nights = nights_in_range(db, user, before - timedelta(days=days), before - timedelta(days=1), device_id)
    mm = metrics_for(db, [n.id for n in nights])
    hist: dict[str, list[float]] = defaultdict(list)
    n_used = 0
    for n in nights:
        disp = display_metrics(mm.get(n.id, {"device": {}, "computed": {}}))
        if not disp.get("usage_h"):
            continue
        n_used += 1
        for k, v in disp.items():
            hist[k].append(v)
    return hist, n_used


def device_of_user(db: Session, user: User, device_id: int) -> Device | None:
    return db.scalar(select(Device).where(and_(Device.id == device_id, Device.owner_id == user.id)))


def has_any_nights(db: Session, user: User) -> bool:
    return bool(db.scalar(select(exists().where(Night.owner_id == user.id))))
