"""/api/reports – weekly / monthly / custom reports in HTML, PDF, CSV, JSON."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from ..models import User
from ..reports.builder import build_report, latest, period_for, report_csv
from ..reports.render import render_html, render_pdf
from .deps import current_user, get_db

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/{kind}")
def report(
    kind: str,
    format: str = Query("json", pattern="^(json|html|pdf|csv)$"),
    start: date | None = Query(None, description="Woche: beliebiger Tag der Woche; custom: Startdatum"),
    end: date | None = Query(None, description="custom: Enddatum"),
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    device_id: int | None = None,
    download: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if kind in ("week", "month"):
        d0, d1, title = period_for(kind, start, month, latest(db, user, device_id))
    elif kind == "custom":
        if not start or not end or end < start:
            raise HTTPException(400, "start und end erforderlich")
        if (end - start).days > 400:
            raise HTTPException(400, "Zeitraum höchstens 400 Tage")
        d0, d1 = start, end
        title = f"Bericht {d0:%d.%m.%Y} – {d1:%d.%m.%Y}"
    else:
        raise HTTPException(404, "Unbekannter Berichtstyp (week|month|custom)")
    rep = build_report(db, user, kind, d0, d1, title, device_id)
    fname = f"sleepy-{kind}-{d0.isoformat()}_{d1.isoformat()}"
    disp = "attachment" if download else "inline"
    if format == "json":
        headers = {"Content-Disposition": f'{disp}; filename="{fname}.json"'} if download else {}
        return JSONResponse(rep, headers=headers)
    if format == "html":
        return HTMLResponse(render_html(rep), headers={"Content-Disposition": f'{disp}; filename="{fname}.html"'})
    if format == "csv":
        return Response(report_csv(rep), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'})
    return Response(render_pdf(rep), media_type="application/pdf",
                    headers={"Content-Disposition": f'{disp}; filename="{fname}.pdf"'})
