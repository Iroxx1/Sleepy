"""Shared API dependencies: DB session, authentication, CSRF, audit."""

from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AuditLog, AuthSession, User, utcnow
from ..security import new_token, token_hash

SESSION_COOKIE = "sleepy_session"
CSRF_COOKIE = "sleepy_csrf"
CSRF_HEADER = "x-csrf-token"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

__all__ = ["get_db"]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def cookie_secure(request: Request) -> bool:
    mode = get_settings().cookie_secure
    if mode == "true":
        return True
    if mode == "false":
        return False
    return request.url.scheme == "https"


def set_session_cookies(request: Request, response: Response, token: str, csrf: str) -> None:
    secure = cookie_secure(request)
    max_age = get_settings().session_max_days * 86400
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=secure, samesite="strict", max_age=max_age, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=secure, samesite="strict", max_age=max_age, path="/")


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def create_session(db: Session, request: Request, user: User, mfa_pending: bool) -> tuple[str, AuthSession]:
    token = new_token()
    s = AuthSession(
        token_hash=token_hash(token),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(24),
        expires_at=utcnow() + timedelta(days=get_settings().session_max_days),
        ip=client_ip(request)[:64],
        user_agent=(request.headers.get("user-agent") or "")[:255],
        mfa_pending=mfa_pending,
    )
    db.add(s)
    db.commit()
    return token, s


def _load_session(request: Request, db: Session) -> AuthSession | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
    if s is None:
        return None
    now = utcnow()
    idle = timedelta(minutes=get_settings().session_idle_minutes)
    if s.expires_at < now or s.last_seen_at + idle < now:
        db.delete(s)
        db.commit()
        return None
    if not s.user.is_active:
        return None
    if (now - s.last_seen_at).total_seconds() > 60:
        s.last_seen_at = now
        db.commit()
    return s


def check_csrf(request: Request, s: AuthSession) -> None:
    if request.method in UNSAFE:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not secrets.compare_digest(sent, s.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF-Prüfung fehlgeschlagen. Bitte Seite neu laden.")


def current_session(request: Request, db: Session = Depends(get_db)) -> AuthSession:
    s = _load_session(request, db)
    if s is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet")
    check_csrf(request, s)
    return s


def current_user(s: AuthSession = Depends(current_session)) -> User:
    if s.mfa_pending:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Zwei-Faktor-Bestätigung erforderlich")
    return s.user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administratorrechte erforderlich")
    return user


def audit(db: Session, request: Request | None, user: User | None, action: str, **detail) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            username=user.username if user else detail.pop("username", None),
            action=action,
            detail=detail,
            ip=client_ip(request)[:64] if request else None,
        )
    )
    db.commit()
