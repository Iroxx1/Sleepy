"""/api/devices, /api/users, /api/system – devices, user admin, diagnostics, backups."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import __version__, storage
from ..backup import create_backup, list_backups
from ..config import get_settings
from ..db import get_engine
from ..importer.pipeline import create_import, disk_free
from ..importer.worker import worker
from ..logging_setup import tail_log
from ..models import AuditLog, AuthSession, Device, DeviceFile, Import, Night, RawFile, User
from ..security import hash_password, validate_password_strength
from .deps import audit, current_user, get_db, require_admin

router = APIRouter(prefix="/api", tags=["admin"])


# ----------------------------------------------------------------- devices
def device_full(db: Session, d: Device) -> dict:
    nights = db.execute(
        select(func.count(), func.min(Night.date), func.max(Night.date)).where(Night.device_id == d.id)
    ).one()
    files = db.scalar(select(func.count()).select_from(DeviceFile).where(DeviceFile.device_id == d.id))
    channels: set[str] = set()
    last = db.scalar(select(Night).where(Night.device_id == d.id).order_by(Night.date.desc()).limit(1))
    for n in db.scalars(select(Night).where(Night.device_id == d.id).order_by(Night.date.desc()).limit(30)):
        for c in n.channels or []:
            channels.add(c["code"])
    return {
        "id": d.id,
        "manufacturer": d.manufacturer,
        "model": d.model,
        "product_code": d.product_code,
        "serial": d.serial,
        "firmware": d.firmware,
        "series": d.series,
        "device_type": d.device_type,
        "data_format": d.data_format,
        "parser": d.parser,
        "display_name": d.display_name,
        "identification": d.identification,
        "first_seen_at": d.first_seen_at.isoformat() if d.first_seen_at else None,
        "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
        "nights": nights[0],
        "first_night": nights[1].isoformat() if nights[1] else None,
        "last_night": nights[2].isoformat() if nights[2] else None,
        "files": files,
        "channels": sorted(channels),
        "current_settings": last.settings if last else {},
    }


@router.get("/devices")
def devices(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [device_full(db, d) for d in db.scalars(select(Device).where(Device.owner_id == user.id).order_by(Device.id))]


def _device(db: Session, user: User, device_id: int) -> Device:
    d = db.get(Device, device_id)
    if d is None or d.owner_id != user.id:
        raise HTTPException(404, "Gerät nicht gefunden")
    return d


@router.get("/devices/{device_id}")
def device(device_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return device_full(db, _device(db, user, device_id))


class DeviceIn(BaseModel):
    display_name: str | None = Field(None, max_length=128)


@router.patch("/devices/{device_id}")
def update_device(device_id: int, body: DeviceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = _device(db, user, device_id)
    d.display_name = (body.display_name or "").strip() or None
    db.commit()
    return device_full(db, d)


@router.delete("/devices/{device_id}")
def delete_device(
    device_id: int,
    request: Request,
    confirm: str = Query(..., description="Seriennummer zur Bestätigung"),
    delete_raw: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Delete a device with all its nights.  Original files stay in the archive
    unless delete_raw=true (then only files no other device references)."""
    import shutil

    from sqlalchemy import delete as sql_delete
    from sqlalchemy import update

    from ..config import get_settings
    from ..models import HardwareItem, ImportFile

    d = _device(db, user, device_id)
    if confirm != d.serial:
        raise HTTPException(400, "Zur Bestätigung die Seriennummer des Geräts angeben.")
    raw_ids = {r for (r,) in db.execute(select(DeviceFile.raw_file_id).where(DeviceFile.device_id == d.id))}
    nights = db.scalar(select(func.count()).select_from(Night).where(Night.device_id == d.id))
    db.execute(sql_delete(Night).where(Night.device_id == d.id))
    db.execute(sql_delete(DeviceFile).where(DeviceFile.device_id == d.id))
    db.execute(update(ImportFile).where(ImportFile.device_id == d.id).values(device_id=None))
    db.execute(update(HardwareItem).where(HardwareItem.device_id == d.id).values(device_id=None))
    serial = d.serial
    db.delete(d)
    db.commit()
    shutil.rmtree(get_settings().signals_dir / str(device_id), ignore_errors=True)
    removed_raw = 0
    if delete_raw and raw_ids:
        still = {r for (r,) in db.execute(select(DeviceFile.raw_file_id).where(DeviceFile.raw_file_id.in_(raw_ids)))}
        for rid in raw_ids - still:
            raw = db.get(RawFile, rid)
            if raw is None:
                continue
            db.execute(update(ImportFile).where(ImportFile.raw_file_id == rid).values(raw_file_id=None))
            p = storage.raw_abs_path(raw.storage_path)
            try:
                p.chmod(0o600)
                p.unlink()
            except OSError:
                pass
            db.delete(raw)
            removed_raw += 1
        db.commit()
    audit(db, request, user, "device_deleted", serial=serial, nights=nights, raw_deleted=removed_raw)
    return {"ok": True, "nights_deleted": nights, "raw_files_deleted": removed_raw}


@router.get("/devices/{device_id}/settings-history")
def settings_history(device_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Periods with identical device settings (changes over time)."""
    from cpap_parser.resmed.labels import SETTING_NAMES

    d = _device(db, user, device_id)
    periods: list[dict] = []
    for n in db.scalars(select(Night).where(Night.device_id == d.id).order_by(Night.date)):
        s = n.settings or {}
        if not s:
            continue
        if periods and periods[-1]["settings"] == s:
            periods[-1]["to"] = n.date.isoformat()
            periods[-1]["nights"] += 1
        else:
            changes = []
            if periods:
                prev = periods[-1]["settings"]
                for k in sorted(set(prev) | set(s)):
                    if prev.get(k) != s.get(k):
                        changes.append({"key": k, "label": SETTING_NAMES.get(k, k), "from": prev.get(k), "to": s.get(k)})
            periods.append({"from": n.date.isoformat(), "to": n.date.isoformat(), "nights": 1, "settings": s,
                            "changes": changes})
    return {"labels": SETTING_NAMES, "periods": periods}


# ------------------------------------------------------------------- users
class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=1, max_length=1024)
    role: str = Field("user", pattern="^(admin|user)$")


class UserPatch(BaseModel):
    role: str | None = Field(None, pattern="^(admin|user)$")
    is_active: bool | None = None
    password: str | None = None
    reset_totp: bool | None = None


def admin_user_out(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "is_active": u.is_active,
        "totp_enabled": u.totp_enabled,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


@router.get("/users")
def users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [admin_user_out(u) for u in db.scalars(select(User).order_by(User.id))]


@router.post("/users")
def create_user(body: UserIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(func.lower(User.username) == body.username.lower())):
        raise HTTPException(409, "Benutzername existiert bereits")
    err = validate_password_strength(body.password)
    if err:
        raise HTTPException(400, err)
    u = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(u)
    db.commit()
    audit(db, request, admin, "user_created", target=u.username, role=u.role)
    return admin_user_out(u)


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, request: Request, admin: User = Depends(require_admin),
               db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Benutzer nicht gefunden")
    if u.id == admin.id and (body.role == "user" or body.is_active is False):
        raise HTTPException(400, "Eigene Administratorrechte können nicht entfernt werden")
    if body.role:
        u.role = body.role
    if body.is_active is not None:
        u.is_active = body.is_active
        if not body.is_active:
            db.query(AuthSession).filter(AuthSession.user_id == u.id).delete()
    if body.password:
        err = validate_password_strength(body.password)
        if err:
            raise HTTPException(400, err)
        u.password_hash = hash_password(body.password)
        db.query(AuthSession).filter(AuthSession.user_id == u.id).delete()
    if body.reset_totp:
        u.totp_enabled = False
        u.totp_secret = None
    db.commit()
    audit(db, request, admin, "user_updated", target=u.username, changes=body.model_dump(exclude={"password"},
                                                                                             exclude_none=True))
    return admin_user_out(u)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Benutzer nicht gefunden")
    if u.id == admin.id:
        raise HTTPException(400, "Der eigene Benutzer kann nicht gelöscht werden")
    if db.scalar(select(func.count()).select_from(Device).where(Device.owner_id == u.id)):
        raise HTTPException(409, "Benutzer besitzt Gerätedaten – stattdessen deaktivieren.")
    db.delete(u)
    db.commit()
    audit(db, request, admin, "user_deleted", target=u.username)
    return {"ok": True}


# ------------------------------------------------------------------ system
@router.get("/health", tags=["system"])
def health():
    """Unauthenticated health check for monitoring / reverse proxies."""
    ok = True
    db_ok = True
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = ok = False
    st = get_settings()
    free = disk_free(st.data_dir)
    disk_ok = free < 0 or free > 100 * 1024 * 1024
    worker_ok = worker.synchronous or (worker.thread is not None and worker.thread.is_alive())
    ok = ok and disk_ok and worker_ok
    return {"status": "ok" if ok else "degraded", "db": db_ok, "disk": disk_ok, "worker": worker_ok,
            "version": __version__}


@router.get("/system/info", tags=["system"])
def info(user: User = Depends(current_user)):
    st = get_settings()
    return {
        "version": __version__,
        "max_upload_mb": st.max_upload_mb,
        "leak_threshold": st.leak_threshold,
        "import_dir_configured": bool(st.import_dir),
        "api_docs": st.enable_api_docs,
    }


@router.get("/system/diagnostics", tags=["system"])
def diagnostics(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    import numpy
    import sqlalchemy

    import cpap_parser

    st = get_settings()
    counts = {
        "users": db.scalar(select(func.count()).select_from(User)),
        "devices": db.scalar(select(func.count()).select_from(Device)),
        "nights": db.scalar(select(func.count()).select_from(Night)),
        "raw_files": db.scalar(select(func.count()).select_from(RawFile)),
        "imports": db.scalar(select(func.count()).select_from(Import)),
    }
    url = st.db_url
    safe_url = url.split("@")[-1] if "@" in url else url
    last_imports = [
        {"id": i.id, "status": i.status, "created_at": i.created_at.isoformat(), "message": i.message}
        for i in db.scalars(select(Import).order_by(Import.created_at.desc()).limit(5))
    ]
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "libraries": {"numpy": numpy.__version__, "sqlalchemy": sqlalchemy.__version__,
                      "cpap_parser": cpap_parser.__version__},
        "parsers": [{"name": p.name, "manufacturer": p.manufacturer, "version": p.version} for p in cpap_parser.parsers()],
        "database": safe_url,
        "paths": {
            "data_dir": str(st.data_dir),
            "raw_dir": str(st.raw_dir),
            "signals_dir": str(st.signals_dir),
            "logs_dir": str(st.logs_dir),
            "backups_dir": str(st.backups_dir),
            "import_dir": str(st.import_dir) if st.import_dir else None,
            "frontend": str(st.frontend_path),
        },
        "storage": {
            "raw_bytes": storage.dir_size(st.raw_dir),
            "signals_bytes": storage.dir_size(st.signals_dir),
            "staging_bytes": storage.dir_size(st.staging_dir),
            "disk_free_bytes": disk_free(st.data_dir),
        },
        "counts": counts,
        "worker": {"current": worker.current, "queued": worker.q.qsize()},
        "last_imports": last_imports,
        "log_tail": tail_log(150),
    }


@router.post("/system/reprocess", tags=["system"])
def reprocess(request: Request, device_id: int | None = None, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    """Rebuild all nights (or of one device) from the raw archive."""
    imp = create_import(db, user, "reprocess", "Neuberechnung aller Nächte", {"device_id": device_id})
    worker.enqueue(imp.id, mode="reprocess")
    audit(db, request, user, "reprocess", import_id=imp.id, device_id=device_id)
    return {"import_id": imp.id}


@router.get("/system/backups", tags=["system"])
def backups(admin: User = Depends(require_admin)):
    return list_backups()


@router.post("/system/backups", tags=["system"])
def make_backup(request: Request, include_raw: bool = True, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    try:
        path = create_backup(include_raw=include_raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Backup fehlgeschlagen: {exc}") from exc
    audit(db, request, admin, "backup_created", file=path.name)
    return {"name": path.name, "size": path.stat().st_size}


@router.get("/system/backups/{name}", tags=["system"])
def download_backup(name: str, admin: User = Depends(require_admin)):
    st = get_settings()
    p = (st.backups_dir / Path(name).name).resolve()
    if not str(p).startswith(str(st.backups_dir.resolve())) or not p.exists():
        raise HTTPException(404, "Backup nicht gefunden")
    return FileResponse(p, filename=p.name, media_type="application/gzip")


@router.get("/system/audit", tags=["system"])
def audit_log(limit: int = Query(200, le=2000), admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [
        {"id": a.id, "created_at": a.created_at.isoformat(), "username": a.username, "action": a.action,
         "detail": a.detail, "ip": a.ip}
        for a in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
    ]
