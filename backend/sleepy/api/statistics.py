"""/api/statistics and /api/dashboard – long term statistics and trends."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cpap_parser.channels import AHI_EVENTS, EVENTS

from ..analysis import insights as ins
from ..analysis.metrics import metric_info
from ..analysis.stats import describe_values, linear_trend, rolling_mean
from ..models import Event, Night, User
from ..repo import display_metrics, history_metrics, metrics_for, night_row, nights_in_range, thresholds_for
from .deps import current_user, get_db

router = APIRouter(prefix="/api", tags=["statistics"])

SUMMARY_KEYS = [
    "usage_h", "ahi", "ai", "hi", "oai", "cai", "uai", "rera_index", "rdi", "odi", "csr_pct",
    "leak.median", "leak.p95", "leak.max", "leak.time_above_pct",
    "pressure.median", "pressure.p95", "pressure.max", "epap.median", "epap.p95",
    "ipap.median", "ipap.p95", "mask_pressure.median", "mask_pressure.p95",
    "flow_limit.median", "flow_limit.p95", "snore.median", "snore.p95",
    "resp_rate.median", "tidal_volume.median", "minute_vent.median",
    "spo2.median", "spo2.min", "spo2.time_below_90_pct", "pulse.mean", "pulse.max",
]

PRESETS = {"7": 7, "30": 30, "90": 90, "180": 180, "365": 365}


def resolve_period(
    preset: str | None, date_from: date | None, date_to: date | None, last: date | None
) -> tuple[date, date]:
    end = date_to or last or date.today()
    if preset and preset in PRESETS:
        return end - timedelta(days=PRESETS[preset] - 1), end
    if preset == "all":
        return date(2000, 1, 1), end
    if date_from:
        return date_from, end
    return end - timedelta(days=29), end


def latest_date(db: Session, user: User, device_id: int | None) -> date | None:
    q = select(func.max(Night.date)).where(Night.owner_id == user.id)
    if device_id:
        q = q.where(Night.device_id == device_id)
    return db.scalar(q)


def period_summary(db: Session, user: User, d0: date, d1: date, device_id: int | None) -> dict:
    nights = nights_in_range(db, user, d0, d1, device_id)
    mm = metrics_for(db, [n.id for n in nights])
    th = thresholds_for(user)
    rows = []
    for n in nights:
        disp = display_metrics(mm.get(n.id, {"device": {}, "computed": {}}))
        if not disp.get("usage_h"):
            continue
        rows.append((n, disp))
    days_total = (d1 - d0).days + 1
    stats = {}
    keys = [k for k in SUMMARY_KEYS if any(k in d for _, d in rows)]
    for k in keys:
        s = describe_values([d.get(k) for _, d in rows])
        if s:
            stats[k] = {**metric_info(k), **s}
    used = len(rows)
    usage = [d["usage_h"] for _, d in rows]
    compliance = {
        "days": days_total,
        "nights_with_data": used,
        "nights_ge_4h": sum(1 for u in usage if u >= 4),
        "pct_nights_used": 100.0 * used / days_total if days_total else 0,
        "pct_ge_4h": 100.0 * sum(1 for u in usage if u >= 4) / days_total if days_total else 0,
        "total_hours": sum(usage),
    }
    best = worst = None
    with_ahi = [(n, d) for n, d in rows if d.get("ahi") is not None]
    if with_ahi:
        b = min(with_ahi, key=lambda x: (x[1]["ahi"], -x[1]["usage_h"]))
        w = max(with_ahi, key=lambda x: (x[1]["ahi"], -x[1]["usage_h"]))
        best = {"id": b[0].id, "date": b[0].date.isoformat(), "ahi": b[1]["ahi"], "usage_h": b[1]["usage_h"]}
        worst = {"id": w[0].id, "date": w[0].date.isoformat(), "ahi": w[1]["ahi"], "usage_h": w[1]["usage_h"]}
    trends = {}
    for k in ("ahi", "usage_h", "leak.p95", "pressure.p95", "cai", "flow_limit.p95"):
        t = linear_trend([(n.date - d0).days for n, _ in rows], [d.get(k) for _, d in rows])
        if t:
            trends[k] = {**metric_info(k), **t}
    # events
    ids = [n.id for n, _ in rows]
    ev_counts: Counter = Counter()
    by_hour: Counter = Counter()
    if ids:
        for code, start_ms in db.execute(select(Event.code, Event.start_ms).where(Event.night_id.in_(ids))):
            ev_counts[code] += 1
            if code in AHI_EVENTS:
                by_hour[int((start_ms // 3600000) % 24)] += 1
    status = Counter(night_row(n, mm[n.id], th)["status"] for n, _ in rows)
    return {
        "from": d0.isoformat(),
        "to": d1.isoformat(),
        "compliance": compliance,
        "stats": stats,
        "best": best,
        "worst": worst,
        "trends": trends,
        "event_totals": dict(ev_counts),
        "events_by_clock_hour": {h: by_hour.get(h, 0) for h in range(24)},
        "status_counts": dict(status),
    }


@router.get("/statistics/summary")
def statistics_summary(
    preset: str | None = Query(None, description="7|30|90|180|365|all"),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    device_id: int | None = None,
    compare_previous: bool = True,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    last = latest_date(db, user, device_id)
    d0, d1 = resolve_period(preset, date_from, date_to, last)
    if preset == "all":
        first = db.scalar(select(func.min(Night.date)).where(Night.owner_id == user.id))
        d0 = first or d0
    if d1 < d0:
        raise HTTPException(400, "Ungültiger Zeitraum")
    cur = period_summary(db, user, d0, d1, device_id)
    if compare_previous and preset != "all":
        span = (d1 - d0).days + 1
        prev = period_summary(db, user, d0 - timedelta(days=span), d0 - timedelta(days=1), device_id)
        cur["previous"] = {
            "from": prev["from"],
            "to": prev["to"],
            "nights": prev["compliance"]["nights_with_data"],
            "means": {k: v["mean"] for k, v in prev["stats"].items()},
            "medians": {k: v["median"] for k, v in prev["stats"].items()},
        }
    return cur


@router.get("/statistics/trends")
def trends(
    metrics: str = Query("ahi,usage_h", description="kommaseparierte Kennzahlen"),
    preset: str | None = None,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    device_id: int | None = None,
    bucket: str = Query("day", pattern="^(day|week|month)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    last = latest_date(db, user, device_id)
    d0, d1 = resolve_period(preset, date_from, date_to, last)
    if preset == "all":
        d0 = db.scalar(select(func.min(Night.date)).where(Night.owner_id == user.id)) or d0
    keys = [k.strip() for k in metrics.split(",") if k.strip()][:16]
    nights = nights_in_range(db, user, d0, d1, device_id)
    mm = metrics_for(db, [n.id for n in nights])
    per_day: dict[date, dict] = {}
    for n in nights:
        disp = display_metrics(mm.get(n.id, {"device": {}, "computed": {}}))
        cur = per_day.setdefault(n.date, {"id": n.id})
        for k in keys:
            if k in disp:
                cur[k] = disp[k]
        if "_events" in metrics:
            pass
    # day axis including gaps
    days = []
    d = d0
    while d <= d1:
        days.append(d)
        d += timedelta(days=1)
    series = {}
    for k in keys:
        vals = [per_day.get(x, {}).get(k) for x in days]
        if bucket == "day":
            series[k] = {
                **metric_info(k),
                "x": [x.isoformat() for x in days],
                "y": vals,
                "rolling7": rolling_mean(vals, 7),
                "night_ids": [per_day.get(x, {}).get("id") for x in days],
                "trend": linear_trend([(x - d0).days for x in days], vals),
            }
        else:
            groups: dict[str, list[float]] = defaultdict(list)
            for x, v in zip(days, vals, strict=False):
                key = f"{x.isocalendar()[0]}-W{x.isocalendar()[1]:02d}" if bucket == "week" else f"{x:%Y-%m}"
                groups.setdefault(key, [])
                if v is not None:
                    groups[key].append(v)
            xs = list(groups)
            series[k] = {
                **metric_info(k),
                "x": xs,
                "y": [sum(v) / len(v) if v else None for v in groups.values()],
                "min": [min(v) if v else None for v in groups.values()],
                "max": [max(v) if v else None for v in groups.values()],
                "n": [len(v) for v in groups.values()],
            }
    return {"from": d0.isoformat(), "to": d1.isoformat(), "bucket": bucket, "series": series}


@router.get("/statistics/events")
def event_distribution(
    preset: str | None = None,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    device_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    last = latest_date(db, user, device_id)
    d0, d1 = resolve_period(preset, date_from, date_to, last)
    q = (
        select(Night.date, Event.code, func.count())
        .join(Night, Night.id == Event.night_id)
        .where(Night.owner_id == user.id, Night.date >= d0, Night.date <= d1)
        .group_by(Night.date, Event.code)
    )
    if device_id:
        q = q.where(Night.device_id == device_id)
    per_day: dict[str, dict[str, int]] = defaultdict(dict)
    for d, code, c in db.execute(q):
        per_day[d.isoformat()][code] = c
    return {
        "from": d0.isoformat(),
        "to": d1.isoformat(),
        "per_day": per_day,
        "types": {c: {"name": e.name, "short": e.short, "color": e.color} for c, e in EVENTS.items()},
    }


@router.get("/dashboard")
def dashboard(device_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    last = latest_date(db, user, device_id)
    th = thresholds_for(user)
    if last is None:
        return {"empty": True, "disclaimer": ins.DISCLAIMER}
    recent = nights_in_range(db, user, last - timedelta(days=29), last, device_id)
    mm = metrics_for(db, [n.id for n in recent])
    rows = [night_row(n, mm.get(n.id, {"device": {}, "computed": {}}), th) for n in recent]
    rows.sort(key=lambda r: r["date"], reverse=True)
    last_row = rows[0]
    last_night = next(n for n in recent if n.id == last_row["id"])
    disp = display_metrics(mm.get(last_night.id, {"device": {}, "computed": {}}))
    hist, n_hist = history_metrics(db, user, last_night.device_id, last_night.date, 30)
    units = {k: metric_info(k)["unit"] for k in disp}
    last_events = [
        ins.Ev(c, s, e, d)
        for c, s, e, d in db.execute(
            select(Event.code, Event.start_ms, Event.end_ms, Event.duration_s).where(Event.night_id == last_night.id)
        )
    ]

    def agg(days: int) -> dict:
        d0 = last - timedelta(days=days - 1)
        rr = [r for r in rows if r["date"] >= d0.isoformat() and r["usage_h"]]
        ahi = [r["metrics"]["ahi"] for r in rr if r["metrics"].get("ahi") is not None]
        use = [r["usage_h"] for r in rr]
        leak = [r["metrics"]["leak.p95"] for r in rr if r["metrics"].get("leak.p95") is not None]
        sa = describe_values(ahi)
        return {
            "days": days,
            "nights": len(rr),
            "ahi_mean": sum(ahi) / len(ahi) if ahi else None,
            "ahi_median": sa["median"] if sa else None,
            "usage_mean": sum(use) / len(use) if use else None,
            "leak_p95_mean": sum(leak) / len(leak) if leak else None,
            "compliance_pct": 100.0 * sum(1 for u in use if u >= 4) / days,
        }

    return {
        "empty": False,
        "last_night": {
            **last_row,
            "all_metrics": disp,
            "summary": ins.summary_text(
                disp, {k: sum(v) / len(v) for k, v in hist.items() if v}, n_hist, last_night.session_count, last_events,
                th["leak_p95_max"], last_night.start_ms, last_night.end_ms,
            ),
            "anomalies": ins.anomalies(disp, hist, units),
        },
        "agg7": agg(7),
        "agg30": agg(30),
        "recent": rows[:14],
        "series30": [
            {"date": r["date"], "id": r["id"], "ahi": r["metrics"].get("ahi"), "usage_h": r["usage_h"],
             "leak_p95": r["metrics"].get("leak.p95"), "status": r["status"]}
            for r in sorted(rows, key=lambda r: r["date"])
        ],
        "thresholds": th,
        "disclaimer": ins.DISCLAIMER,
    }
