"""/api/imports – upload, start, monitor and retry imports."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..importer.pipeline import create_import, disk_free, staging_path
from ..importer.worker import worker
from ..importer.zipsafe import safe_rel
from ..models import Device, Import, ImportFile, User
from .deps import audit, current_user, get_db

router = APIRouter(prefix="/api/imports", tags=["imports"])


class CreateIn(BaseModel):
    source: str  # zip | folder
    name: str | None = None


def _get(db: Session, user: User, import_id: str) -> Import:
    imp = db.get(Import, import_id)
    if imp is None or (imp.owner_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Import nicht gefunden")
    return imp


def import_out(imp: Import, with_log: bool = False) -> dict:
    d = {
        "id": imp.id,
        "source": imp.source,
        "original_name": imp.original_name,
        "status": imp.status,
        "stage": imp.stage,
        "progress": imp.progress,
        "message": imp.message,
        "error": imp.error,
        "created_at": imp.created_at.isoformat() if imp.created_at else None,
        "started_at": imp.started_at.isoformat() if imp.started_at else None,
        "finished_at": imp.finished_at.isoformat() if imp.finished_at else None,
        "stats": imp.stats or {},
        "uploaded_bytes": imp.uploaded_bytes,
        "can_retry": imp.status in ("failed", "completed_with_errors"),
    }
    if with_log:
        d["log"] = imp.log or []
    return d


@router.get("")
def list_imports(
    limit: int = Query(50, le=500), offset: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    q = select(Import).where(Import.owner_id == user.id).order_by(Import.created_at.desc())
    total = db.scalar(select(func.count()).select_from(Import).where(Import.owner_id == user.id))
    rows = db.scalars(q.offset(offset).limit(limit))
    return {"total": total, "items": [import_out(i) for i in rows]}


@router.post("")
def create(body: CreateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.source not in ("zip", "folder"):
        raise HTTPException(400, "source muss 'zip' oder 'folder' sein")
    st = get_settings()
    free = disk_free(st.data_dir)
    if 0 <= free < 200 * 1024 * 1024:
        raise HTTPException(507, "Zu wenig freier Speicherplatz auf dem Server (< 200 MB).")
    imp = create_import(db, user, body.source, (body.name or "")[:255] or None)
    audit(db, request, user, "import_created", import_id=imp.id, source=body.source)
    return import_out(imp)


@router.put("/{import_id}/upload")
async def upload_zip(
    import_id: str,
    request: Request,
    filename: str = Query(..., max_length=255),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Stream a ZIP file as raw request body (supports multi-GB uploads)."""
    imp = _get(db, user, import_id)
    if imp.source != "zip" or imp.status not in ("created", "uploading"):
        raise HTTPException(409, "Upload für diesen Import nicht möglich")
    name = Path(filename).name or "upload.zip"
    if not name.lower().endswith(".zip"):
        raise HTTPException(400, "Bitte eine .zip-Datei hochladen")
    limit = get_settings().max_upload_mb * 1024 * 1024
    dest_dir = staging_path(imp.id) / "upload"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    imp.status = "uploading"
    db.commit()
    written = 0
    try:
        with open(dest, "wb") as fh:
            async for chunk in request.stream():
                written += len(chunk)
                if written > limit:
                    raise HTTPException(413, f"Datei größer als {get_settings().max_upload_mb} MB")
                fh.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Upload abgebrochen: {exc}") from exc
    imp.uploaded_bytes = (imp.uploaded_bytes or 0) + written
    imp.original_name = imp.original_name or name
    db.commit()
    return {"ok": True, "bytes": written}


@router.post("/{import_id}/files")
async def upload_files(
    import_id: str,
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Upload a batch of files of a folder (relative paths in *paths*)."""
    imp = _get(db, user, import_id)
    if imp.source != "folder" or imp.status not in ("created", "uploading"):
        raise HTTPException(409, "Upload für diesen Import nicht möglich")
    if len(files) != len(paths):
        raise HTTPException(400, "Anzahl Dateien und Pfade unterschiedlich")
    limit = get_settings().max_upload_mb * 1024 * 1024
    root = staging_path(imp.id) / "files"
    total = imp.uploaded_bytes or 0
    for f, rel in zip(files, paths, strict=False):
        safe = safe_rel(rel)
        if safe is None:
            raise HTTPException(400, f"Unsicherer Pfad: {rel!r}")
        target = root / safe
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as out:
            shutil.copyfileobj(f.file, out, 1024 * 1024)
            total += out.tell()
        if total > limit:
            raise HTTPException(413, f"Upload größer als {get_settings().max_upload_mb} MB")
    imp.status = "uploading"
    imp.uploaded_bytes = total
    db.commit()
    return {"ok": True, "count": len(files), "bytes": total}


@router.post("/{import_id}/start")
def start(import_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    imp = _get(db, user, import_id)
    if imp.status not in ("created", "uploading"):
        raise HTTPException(409, f"Import kann im Status '{imp.status}' nicht gestartet werden")
    worker.enqueue(imp.id)
    db.refresh(imp)
    return import_out(imp)


@router.get("/server-info")
def server_info(user: User = Depends(current_user)):
    st = get_settings()
    p = st.import_dir
    return {
        "configured": bool(p),
        "path": str(p) if p else None,
        "exists": bool(p and Path(p).is_dir()),
        "auto_scan_minutes": st.import_scan_interval_minutes,
        "max_upload_mb": st.max_upload_mb,
    }


@router.post("/server-scan")
def server_scan(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = get_settings()
    if not st.import_dir or not Path(st.import_dir).is_dir():
        raise HTTPException(400, "Kein Server-Importverzeichnis konfiguriert (SLEEPY_IMPORT_DIR).")
    imp_id = worker.scan_server_dir(user_id=user.id, automatic=False)
    audit(db, request, user, "import_server_scan", import_id=imp_id)
    return import_out(db.get(Import, imp_id))


@router.get("/{import_id}")
def get_import(import_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    imp = _get(db, user, import_id)
    out = import_out(imp, with_log=True)
    counts = dict(
        db.execute(
            select(ImportFile.status, func.count()).where(ImportFile.import_id == imp.id).group_by(ImportFile.status)
        ).all()
    )
    out["file_counts"] = counts
    dev_ids = [
        r[0]
        for r in db.execute(
            select(ImportFile.device_id).where(ImportFile.import_id == imp.id, ImportFile.device_id.is_not(None)).distinct()
        )
    ]
    out["devices"] = [
        {"id": d.id, "manufacturer": d.manufacturer, "model": d.model, "serial": d.serial}
        for d in db.scalars(select(Device).where(Device.id.in_(dev_ids)))
    ] if dev_ids else []
    return out


@router.get("/{import_id}/files")
def import_files(
    import_id: str,
    status: str | None = None,
    offset: int = 0,
    limit: int = Query(200, le=2000),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    imp = _get(db, user, import_id)
    q = select(ImportFile).where(ImportFile.import_id == imp.id)
    cq = select(func.count()).select_from(ImportFile).where(ImportFile.import_id == imp.id)
    if status:
        q = q.where(ImportFile.status == status)
        cq = cq.where(ImportFile.status == status)
    rows = db.scalars(q.order_by(ImportFile.id).offset(offset).limit(limit))
    return {
        "total": db.scalar(cq),
        "items": [
            {
                "path": f.path,
                "sd_path": f.sd_path,
                "status": f.status,
                "kind": f.kind,
                "size": f.size,
                "sha256": f.sha256,
                "message": f.message,
                "device_id": f.device_id,
            }
            for f in rows
        ],
    }


@router.post("/{import_id}/retry")
def retry(import_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    imp = _get(db, user, import_id)
    if imp.status in ("running", "queued"):
        raise HTTPException(409, "Import läuft bereits")
    stage = staging_path(imp.id)
    if imp.source in ("zip", "folder") and stage.exists() and any(stage.iterdir()):
        db.execute(delete(ImportFile).where(ImportFile.import_id == imp.id))
        imp.log = list(imp.log or []) + [{"t": "", "level": "info", "text": "— Erneuter Versuch —"}]
        db.commit()
        worker.enqueue(imp.id)
        audit(db, request, user, "import_retry", import_id=imp.id, mode="full")
        db.refresh(imp)
        return import_out(imp)
    if imp.source == "server_dir":
        db.execute(delete(ImportFile).where(ImportFile.import_id == imp.id))
        db.commit()
        worker.enqueue(imp.id)
        db.refresh(imp)
        return import_out(imp)
    archived = db.scalar(
        select(func.count()).select_from(ImportFile).where(
            ImportFile.import_id == imp.id, ImportFile.status.in_(["new", "updated"])
        )
    )
    if not archived:
        raise HTTPException(
            409, "Die Upload-Daten sind nicht mehr vorhanden und es wurde nichts archiviert. Bitte erneut hochladen."
        )
    new = create_import(db, user, "reprocess", f"Neuberechnung für Import {imp.id[:8]}", {"import_id": imp.id})
    worker.enqueue(new.id, mode="reprocess")
    audit(db, request, user, "import_retry", import_id=imp.id, mode="reprocess", new_import=new.id)
    return import_out(db.get(Import, new.id))


@router.delete("/{import_id}")
def delete_draft(import_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    imp = _get(db, user, import_id)
    if imp.status not in ("created", "uploading"):
        raise HTTPException(409, "Nur nicht gestartete Importe können verworfen werden (Daten bleiben erhalten).")
    shutil.rmtree(staging_path(imp.id), ignore_errors=True)
    db.delete(imp)
    db.commit()
    return {"ok": True}
