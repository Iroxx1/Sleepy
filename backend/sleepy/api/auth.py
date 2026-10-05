"""/api/auth – login, logout, 2FA, password, preferences, first setup."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AuthSession, User, utcnow
from ..security import (
    dummy_verify,
    hash_password,
    login_limiter,
    needs_rehash,
    new_totp_secret,
    totp_qr_svg,
    totp_uri,
    validate_password_strength,
    verify_password,
    verify_totp,
)
from .deps import (
    SESSION_COOKIE,
    _load_session,
    audit,
    clear_session_cookies,
    client_ip,
    create_session,
    current_session,
    current_user,
    get_db,
    set_session_cookies,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=1, max_length=1024)


class SetupIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=1, max_length=1024)


class DisableTotpIn(BaseModel):
    password: str
    code: str


def user_out(u: User, s: AuthSession | None = None) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "totp_enabled": u.totp_enabled,
        "preferences": u.preferences or {},
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "csrf_token": s.csrf_token if s else None,
    }


def _rate_keys(request: Request, username: str) -> list[str]:
    return [f"ip:{client_ip(request)}", f"user:{username.lower()}"]


@router.get("/setup-status")
def setup_status(db: Session = Depends(get_db)):
    count = db.scalar(select(func.count()).select_from(User)) or 0
    return {"needs_setup": count == 0}


@router.post("/setup")
def setup(body: SetupIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Create the first administrator.  Only possible while no user exists."""
    if (db.scalar(select(func.count()).select_from(User)) or 0) > 0:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Die Ersteinrichtung wurde bereits durchgeführt.")
    err = validate_password_strength(body.password)
    if err:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, err)
    u = User(username=body.username, password_hash=hash_password(body.password), role="admin")
    db.add(u)
    db.commit()
    audit(db, request, u, "setup")
    token, s = create_session(db, request, u, mfa_pending=False)
    u.last_login_at = utcnow()
    db.commit()
    set_session_cookies(request, response, token, s.csrf_token)
    return {"user": user_out(u, s)}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    st = get_settings()
    window = st.login_rate_window_minutes * 60
    keys = _rate_keys(request, body.username)
    if any(login_limiter.blocked(k, st.login_rate_limit, window) for k in keys):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Zu viele Anmeldeversuche. Bitte in {st.login_rate_window_minutes} Minuten erneut versuchen.",
        )
    u = db.scalar(select(User).where(func.lower(User.username) == body.username.lower()))
    if u is None:
        dummy_verify()
        ok = False
    else:
        ok = verify_password(u.password_hash, body.password) and u.is_active
    if not ok:
        for k in keys:
            login_limiter.hit(k, st.login_rate_limit, window)
        audit(db, request, None, "login_failed", username=body.username[:64])
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Benutzername oder Passwort falsch.")
    for k in keys:
        login_limiter.reset(k)
    if needs_rehash(u.password_hash):
        u.password_hash = hash_password(body.password)
    token, s = create_session(db, request, u, mfa_pending=u.totp_enabled)
    if not u.totp_enabled:
        u.last_login_at = utcnow()
        audit(db, request, u, "login")
    db.commit()
    set_session_cookies(request, response, token, s.csrf_token)
    return {"mfa_required": u.totp_enabled, "user": None if u.totp_enabled else user_out(u, s)}


class AppLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)
    code: str | None = Field(None, max_length=10)
    device_name: str | None = Field(None, max_length=128)


@router.post("/app-login")
def app_login(body: AppLoginIn, request: Request, db: Session = Depends(get_db)):
    """Login for the mobile app. Returns a bearer token (no cookies).

    If two-factor authentication is enabled and no code is given, the response
    is ``{"mfa_required": true}`` and the app asks for the code.
    """
    st = get_settings()
    window = st.login_rate_window_minutes * 60
    keys = _rate_keys(request, body.username)
    if any(login_limiter.blocked(k, st.login_rate_limit, window) for k in keys):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Zu viele Anmeldeversuche. Bitte in {st.login_rate_window_minutes} Minuten erneut versuchen.",
        )
    u = db.scalar(select(User).where(func.lower(User.username) == body.username.lower()))
    if u is None:
        dummy_verify()
        ok = False
    else:
        ok = verify_password(u.password_hash, body.password) and u.is_active
    if ok and u.totp_enabled:
        if not body.code:
            return {"mfa_required": True, "token": None, "user": None}
        ok = bool(u.totp_secret) and verify_totp(u.totp_secret, body.code)
    if not ok:
        for k in keys:
            login_limiter.hit(k, st.login_rate_limit, window)
        audit(db, request, None, "app_login_failed", username=body.username[:64])
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Benutzername, Passwort oder Code falsch.")
    for k in keys:
        login_limiter.reset(k)
    token, s = create_session(db, request, u, mfa_pending=False, kind="app",
                              device_name=body.device_name or "Android-App")
    u.last_login_at = utcnow()
    db.commit()
    audit(db, request, u, "app_login", device=s.device_name)
    return {"mfa_required": False, "token": token, "user": user_out(u, None),
            "expires_at": s.expires_at.isoformat()}


@router.post("/app-logout")
def app_logout(s: AuthSession = Depends(current_session), db: Session = Depends(get_db)):
    if s.kind == "app":
        db.delete(s)
        db.commit()
    return {"ok": True}


@router.get("/app-sessions")
def app_sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.kind == "app")
        .order_by(AuthSession.last_seen_at.desc())
    )
    return [
        {"id": r.id, "device_name": r.device_name, "created_at": r.created_at.isoformat(),
         "last_seen_at": r.last_seen_at.isoformat(), "expires_at": r.expires_at.isoformat(), "ip": r.ip}
        for r in rows
    ]


@router.delete("/app-sessions/{session_id}")
def revoke_app_session(session_id: int, request: Request, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    r = db.get(AuthSession, session_id)
    if r is None or r.user_id != user.id or r.kind != "app":
        raise HTTPException(404, "Nicht gefunden")
    db.delete(r)
    db.commit()
    audit(db, request, user, "app_session_revoked", device=r.device_name)
    return {"ok": True}


@router.post("/totp/verify")
def totp_verify(body: CodeIn, request: Request, s: AuthSession = Depends(current_session), db: Session = Depends(get_db)):
    st = get_settings()
    key = f"totp:{s.user_id}"
    if not login_limiter.hit(key, st.login_rate_limit, st.login_rate_window_minutes * 60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Zu viele Versuche.")
    u = s.user
    if not s.mfa_pending:
        return {"user": user_out(u, s)}
    if not u.totp_secret or not verify_totp(u.totp_secret, body.code):
        audit(db, request, u, "totp_failed")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Code ungültig.")
    login_limiter.reset(key)
    s.mfa_pending = False
    u.last_login_at = utcnow()
    db.commit()
    audit(db, request, u, "login", mfa=True)
    return {"user": user_out(u, s)}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    s = _load_session(request, db)
    if s is not None:
        from .deps import check_csrf

        check_csrf(request, s)
        db.delete(s)
        db.commit()
    clear_session_cookies(response)
    return {"ok": True}


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    s = _load_session(request, db)
    if s is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet")
    if s.mfa_pending:
        return {"mfa_required": True, "user": None}
    return {"mfa_required": False, "user": user_out(s.user, s)}


@router.post("/password")
def change_password(body: PasswordIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Aktuelles Passwort ist falsch.")
    err = validate_password_strength(body.new_password)
    if err:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, err)
    user.password_hash = hash_password(body.new_password)
    # invalidate all other sessions
    from .deps import bearer_token

    current = bearer_token(request) or request.cookies.get(SESSION_COOKIE)
    from ..security import token_hash

    db.execute(
        delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.token_hash != token_hash(current or ""))
    )
    db.commit()
    audit(db, request, user, "password_changed")
    return {"ok": True}


@router.post("/totp/setup")
def totp_setup(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.totp_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "2FA ist bereits aktiv.")
    user.totp_secret = new_totp_secret()
    db.commit()
    uri = totp_uri(user.totp_secret, user.username)
    return {"secret": user.totp_secret, "uri": uri, "qr_svg": totp_qr_svg(uri)}


@router.post("/totp/enable")
def totp_enable(body: CodeIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.totp_secret or not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code ungültig – bitte Uhrzeit des Geräts prüfen.")
    user.totp_enabled = True
    db.commit()
    audit(db, request, user, "totp_enabled")
    return {"ok": True}


@router.post("/totp/disable")
def totp_disable(body: DisableTotpIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(user.password_hash, body.password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Passwort ist falsch.")
    if user.totp_enabled and (not user.totp_secret or not verify_totp(user.totp_secret, body.code)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code ungültig.")
    user.totp_enabled = False
    user.totp_secret = None
    db.commit()
    audit(db, request, user, "totp_disabled")
    return {"ok": True}


ALLOWED_PREFS = {"theme", "thresholds", "default_device_id", "chart_channels", "chart_heights"}  # custom_css: /api/appearance


@router.get("/preferences")
def get_preferences(user: User = Depends(current_user)):
    return user.preferences or {}


@router.put("/preferences")
def put_preferences(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    prefs = dict(user.preferences or {})
    for k, v in body.items():
        if k in ALLOWED_PREFS:
            prefs[k] = v
    if "thresholds" in prefs and not isinstance(prefs["thresholds"], dict):
        raise HTTPException(400, "thresholds muss ein Objekt sein")
    user.preferences = prefs
    db.commit()
    return prefs
