"""/api/appearance – custom CSS (per user and global) for theming."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import AppSetting, User
from .deps import _load_session, audit, current_user, get_db, require_admin

router = APIRouter(prefix="/api/appearance", tags=["appearance"])

MAX_CSS = 100_000
_FORBIDDEN = re.compile(r"(javascript:|expression\s*\(|behavior\s*:|-moz-binding|</style)", re.I)


class CssIn(BaseModel):
    css: str = Field("", max_length=MAX_CSS)


def _check(css: str) -> str:
    if _FORBIDDEN.search(css):
        raise HTTPException(400, "Das CSS enthält nicht erlaubte Konstrukte (javascript:, expression(), behavior …).")
    return css


def _global(db: Session) -> str:
    row = db.get(AppSetting, "global_css")
    return (row.value or "") if row else ""


def _css_response(css: str) -> Response:
    return Response(css, media_type="text/css; charset=utf-8", headers={"Cache-Control": "no-cache"})


@router.get("")
def get_appearance(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"user_css": (user.preferences or {}).get("custom_css", ""), "global_css": _global(db)}


@router.put("/user")
def put_user_css(body: CssIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    prefs = dict(user.preferences or {})
    prefs["custom_css"] = _check(body.css)
    user.preferences = prefs
    db.commit()
    return {"ok": True}


@router.put("/global")
def put_global_css(body: CssIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    css = _check(body.css)
    row = db.get(AppSetting, "global_css")
    if row is None:
        db.add(AppSetting(key="global_css", value=css))
    else:
        row.value = css
    db.commit()
    audit(db, request, admin, "global_css_changed", size=len(css))
    return {"ok": True}


@router.get("/global.css", include_in_schema=False)
def global_css(db: Session = Depends(get_db)):
    """Public so that the login page can be themed too (contains no data)."""
    return _css_response(_global(db))


@router.get("/user.css", include_in_schema=False)
def user_css(request: Request, db: Session = Depends(get_db)):
    s = _load_session(request, db)
    css = (s.user.preferences or {}).get("custom_css", "") if s and not s.mfa_pending else ""
    return _css_response(css)
