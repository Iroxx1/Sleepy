"""Weekly / monthly / custom reports (HTML, PDF, CSV, JSON)."""

from __future__ import annotations

import calendar
import csv
import io
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..analysis import insights as ins
from ..analysis.metrics import metric_info
from ..api.statistics import latest_date, period_summary
from ..models import Device, User
from ..repo import display_metrics, history_metrics, metrics_for, night_row, nights_in_range, thresholds_for

REPORT_COLUMNS = [
    ("date", "Datum"),
    ("usage_h", "Nutzung (h)"),
    ("ahi", "AHI"),
    ("oai", "OAI"),
    ("cai", "CAI"),
    ("hi", "HI"),
    ("rera_index", "RERA-Index"),
    ("leak.median", "Leck Median (L/min)"),
    ("leak.p95", "Leck 95 % (L/min)"),
    ("pressure.median", "Druck Median"),
    ("pressure.p95", "Druck 95 %"),
    ("flow_limit.p95", "FL 95 %"),
    ("spo2.median", "SpO2 Median"),
]


def period_for(kind: str, start: date | None, month: str | None, last: date | None) -> tuple[date, date, str]:
    ref = last or date.today()
    if kind == "week":
        s = start or (ref - timedelta(days=ref.weekday()))
        s = s - timedelta(days=s.weekday())
        e = s + timedelta(days=6)
        return s, e, f"Wochenbericht KW {s.isocalendar()[1]}/{s.isocalendar()[0]}"
    if kind == "month":
        if month:
            y, m = map(int, month.split("-"))
        else:
            y, m = ref.year, ref.month
        s = date(y, m, 1)
        e = date(y, m, calendar.monthrange(y, m)[1])
        names = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
                 "November", "Dezember"]
        return s, e, f"Monatsbericht {names[m - 1]} {y}"
    raise ValueError(kind)


def build_report(
    db: Session,
    user: User,
    kind: str,
    d0: date,
    d1: date,
    title: str,
    device_id: int | None = None,
) -> dict:
    summary = period_summary(db, user, d0, d1, device_id)
    span = (d1 - d0).days + 1
    prev = period_summary(db, user, d0 - timedelta(days=span), d0 - timedelta(days=1), device_id)
    nights = nights_in_range(db, user, d0, d1, device_id)
    mm = metrics_for(db, [n.id for n in nights])
    th = thresholds_for(user)
    rows = []
    anomalies = []
    for n in nights:
        m = mm.get(n.id, {"device": {}, "computed": {}})
        r = night_row(n, m, th)
        disp = display_metrics(m)
        r["all_metrics"] = disp
        rows.append(r)
        if disp.get("usage_h"):
            hist, _ = history_metrics(db, user, n.device_id, n.date, 30)
            units = {k: metric_info(k)["unit"] for k in disp}
            for a in ins.anomalies(disp, hist, units):
                anomalies.append({"date": n.date.isoformat(), "night_id": n.id, **a})
    st = summary["stats"]
    pst = prev["stats"]
    highlights: list[str] = []
    c = summary["compliance"]
    highlights.append(
        f"{c['nights_with_data']} von {c['days']} Nächten mit Therapiedaten, davon {c['nights_ge_4h']} mit "
        f"mindestens 4 Stunden Nutzung."
    )
    if "usage_h" in st:
        txt = f"Durchschnittliche Nutzungsdauer {ins.duration_hm(st['usage_h']['mean'])}"
        if "usage_h" in pst:
            txt += f" (Vorperiode {ins.duration_hm(pst['usage_h']['mean'])})"
        highlights.append(txt + ".")
    if "ahi" in st:
        txt = f"AHI im Mittel {ins.fmt(st['ahi']['mean'], 1)} (Median {ins.fmt(st['ahi']['median'], 1)}, " \
              f"Spanne {ins.fmt(st['ahi']['min'], 1)}–{ins.fmt(st['ahi']['max'], 1)})"
        if "ahi" in pst:
            txt += f"; Vorperiode im Mittel {ins.fmt(pst['ahi']['mean'], 1)}"
        highlights.append(txt + ".")
    if summary["best"] and summary["worst"] and summary["best"]["date"] != summary["worst"]["date"]:
        b, w = summary["best"], summary["worst"]
        highlights.append(
            f"Niedrigster AHI am {_de(b['date'])} ({ins.fmt(b['ahi'], 1)}), höchster am {_de(w['date'])} "
            f"({ins.fmt(w['ahi'], 1)})."
        )
    if "leak.p95" in st:
        highlights.append(
            f"Leckage (95 %-Perzentil) im Mittel {ins.fmt(st['leak.p95']['mean'], 1)} L/min, "
            f"Maximum einer Nacht {ins.fmt(st['leak.p95']['max'], 1)} L/min."
        )
    if "pressure.p95" in st:
        highlights.append(
            f"Druck (95 %-Perzentil) im Mittel {ins.fmt(st['pressure.p95']['mean'], 1)} cmH2O."
        )
    for _k, t in summary["trends"].items():
        if t["direction"] != "stabil":
            highlights.append(
                f"Statistischer Trend {t['label']}: {t['direction']} "
                f"({ins.fmt(t['slope_per_30d'], 2)} {t['unit']} pro 30 Tage)."
            )
    device = db.get(Device, device_id) if device_id else None
    return {
        "kind": kind,
        "title": title,
        "from": d0.isoformat(),
        "to": d1.isoformat(),
        "generated": datetime.now().isoformat(timespec="seconds"),
        "user": user.username,
        "device": {"model": device.model, "serial": device.serial} if device else None,
        "summary": summary,
        "previous": {"from": prev["from"], "to": prev["to"], "stats": prev["stats"],
                     "compliance": prev["compliance"]},
        "highlights": highlights,
        "anomalies": anomalies,
        "nights": rows,
        "thresholds": th,
        "disclaimer": ins.DISCLAIMER,
    }


def _de(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%d.%m.%Y}"


def report_csv(rep: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([label for _, label in REPORT_COLUMNS] + ["Status"])
    for r in rep["nights"]:
        line = []
        for key, _ in REPORT_COLUMNS:
            if key == "date":
                line.append(r["date"])
            else:
                v = r["all_metrics"].get(key)
                line.append("" if v is None else f"{v:.3f}")
        line.append(r["status"])
        w.writerow(line)
    return buf.getvalue()


def svg_bars(points: list[tuple[str, float | None]], color: str, unit: str, ref: float | None = None,
             width: int = 720, height: int = 180) -> str:
    """Simple inline SVG bar chart (no JavaScript, works offline and in print)."""
    vals = [v for _, v in points if v is not None]
    vmax = max(vals + [ref or 0, 1e-6]) * 1.15 if vals else 1
    n = max(len(points), 1)
    left, bottom, top = 40, 24, 10
    plot_w = width - left - 10
    plot_h = height - bottom - top
    bw = plot_w / n
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" role="img">']
    for i in range(5):
        y = top + plot_h * i / 4
        val = vmax * (1 - i / 4)
        parts.append(f'<line x1="{left}" x2="{width - 10}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        parts.append(f'<text x="{left - 4}" y="{y + 4:.1f}" font-size="10" text-anchor="end" fill="#6b7280">'
                     f'{val:.1f}</text>')
    for i, (label, v) in enumerate(points):
        x = left + i * bw
        if v is not None:
            h = plot_h * v / vmax
            parts.append(f'<rect x="{x + bw * 0.15:.1f}" y="{top + plot_h - h:.1f}" width="{bw * 0.7:.1f}" '
                         f'height="{h:.1f}" fill="{color}" rx="2"><title>{label}: {v:.2f} {unit}</title></rect>')
        if n <= 16 or i % max(1, n // 10) == 0:
            parts.append(f'<text x="{x + bw / 2:.1f}" y="{height - 8}" font-size="9" text-anchor="middle" '
                         f'fill="#6b7280">{label}</text>')
    if ref is not None and ref < vmax:
        y = top + plot_h * (1 - ref / vmax)
        parts.append(f'<line x1="{left}" x2="{width - 10}" y1="{y:.1f}" y2="{y:.1f}" stroke="#dc2626" '
                     f'stroke-dasharray="4 3"/>')
    parts.append("</svg>")
    return "".join(parts)


def chart_points(rep: dict, key: str) -> list[tuple[str, float | None]]:
    by = {r["date"]: r["all_metrics"].get(key) for r in rep["nights"]}
    d0, d1 = date.fromisoformat(rep["from"]), date.fromisoformat(rep["to"])
    out = []
    d = d0
    while d <= d1:
        out.append((f"{d:%d.%m.}", by.get(d.isoformat())))
        d += timedelta(days=1)
    return out


def latest(db: Session, user: User, device_id: int | None) -> date | None:
    return latest_date(db, user, device_id)
