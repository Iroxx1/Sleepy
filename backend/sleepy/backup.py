"""Backup / restore of database, configuration, raw archive and analysis data.

Backup format: ``sleepy-backup-YYYYmmdd-HHMMSS.tar.gz`` containing::

    manifest.json
    db/sleepy.db          (SQLite online snapshot)   or  db/postgres.sql (pg_dump)
    config/sleepy.env     (if SLEEPY_CONFIG_FILE is set and readable)
    raw/...               original files (content addressed)
    signals/...           normalised signal arrays
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import get_settings

PREFIX = "sleepy-backup-"


def _sqlite_path() -> Path | None:
    url = get_settings().db_url
    if url.startswith("sqlite:///"):
        return Path(url[len("sqlite:///"):])
    return None


def _snapshot_db(dest_dir: Path) -> str:
    sp = _sqlite_path()
    dest_dir.mkdir(parents=True, exist_ok=True)
    if sp is not None:
        target = dest_dir / "sleepy.db"
        src = sqlite3.connect(str(sp))
        dst = sqlite3.connect(str(target))
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        return "sqlite"
    url = get_settings().db_url
    if url.startswith("postgresql"):
        pg_url = url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")
        out = dest_dir / "postgres.sql"
        with open(out, "wb") as fh:
            subprocess.run(["pg_dump", "--no-owner", "--dbname", pg_url], stdout=fh, check=True)
        return "postgresql"
    raise RuntimeError(f"Backup für Datenbank-URL nicht unterstützt: {url.split(':')[0]}")


def create_backup(dest: Path | None = None, include_raw: bool = True, include_signals: bool = True) -> Path:
    st = get_settings()
    out_dir = dest or st.backups_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = out_dir / f"{PREFIX}{stamp}.tar.gz"
    with tempfile.TemporaryDirectory(dir=st.data_dir) as tmp:
        tmpd = Path(tmp)
        db_kind = _snapshot_db(tmpd / "db")
        manifest = {
            "app": "sleepy",
            "version": __version__,
            "created": datetime.now().isoformat(timespec="seconds"),
            "database": db_kind,
            "include_raw": include_raw,
            "include_signals": include_signals,
        }
        (tmpd / "manifest.json").write_text(json.dumps(manifest, indent=2))
        partial = target.with_suffix(".partial")
        with tarfile.open(partial, "w:gz", compresslevel=6) as tar:
            tar.add(tmpd / "manifest.json", arcname="manifest.json")
            tar.add(tmpd / "db", arcname="db")
            if st.config_file and Path(st.config_file).is_file():
                tar.add(st.config_file, arcname="config/sleepy.env")
            if include_raw and st.raw_dir.exists():
                tar.add(st.raw_dir, arcname="raw")
            if include_signals and st.signals_dir.exists():
                tar.add(st.signals_dir, arcname="signals")
        os.replace(partial, target)
    _rotate(out_dir, st.backup_keep)
    return target


def _rotate(out_dir: Path, keep: int) -> None:
    files = sorted(out_dir.glob(f"{PREFIX}*.tar.gz"))
    for f in files[:-keep] if keep > 0 else []:
        f.unlink(missing_ok=True)


def list_backups() -> list[dict]:
    d = get_settings().backups_dir
    if not d.exists():
        return []
    return [
        {"name": f.name, "size": f.stat().st_size, "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat()}
        for f in sorted(d.glob(f"{PREFIX}*.tar.gz"), reverse=True)
    ]


def _safe_members(tar: tarfile.TarFile):
    for m in tar.getmembers():
        name = m.name
        if name.startswith("/") or ".." in Path(name).parts or m.issym() or m.islnk():
            raise RuntimeError(f"Unsicherer Eintrag im Backup: {name}")
        yield m


def restore_backup(archive: Path, restore_config_to: Path | None = None) -> dict:
    """Restore a backup.  The service must be stopped.

    Existing data is *not deleted* but moved to ``<data_dir>/pre-restore-<ts>/``.
    """
    st = get_settings()
    if not archive.is_file():
        raise FileNotFoundError(archive)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    keep_dir = st.data_dir / f"pre-restore-{stamp}"
    with tempfile.TemporaryDirectory(dir=st.data_dir) as tmp:
        tmpd = Path(tmp)
        with tarfile.open(archive, "r:gz") as tar:
            members = list(_safe_members(tar))
            tar.extractall(tmpd, members=members)
        manifest = json.loads((tmpd / "manifest.json").read_text())
        if manifest.get("app") != "sleepy":
            raise RuntimeError("Kein Sleepy-Backup")
        keep_dir.mkdir(parents=True)
        # database
        if manifest["database"] == "sqlite":
            sp = _sqlite_path()
            if sp is None:
                raise RuntimeError("Backup enthält SQLite, konfiguriert ist aber eine andere Datenbank")
            sp.parent.mkdir(parents=True, exist_ok=True)
            for suffix in ("", "-wal", "-shm"):
                p = Path(str(sp) + suffix)
                if p.exists():
                    shutil.move(str(p), keep_dir / p.name)
            shutil.copy2(tmpd / "db" / "sleepy.db", sp)
        else:
            url = st.db_url.replace("postgresql+psycopg://", "postgresql://")
            subprocess.run(["psql", "--dbname", url, "-f", str(tmpd / "db" / "postgres.sql")], check=True)
        for name, target in (("raw", st.raw_dir), ("signals", st.signals_dir)):
            src = tmpd / name
            if src.exists():
                if target.exists():
                    shutil.move(str(target), keep_dir / name)
                shutil.move(str(src), target)
        cfg = tmpd / "config" / "sleepy.env"
        if cfg.exists() and restore_config_to:
            if restore_config_to.exists():
                shutil.copy2(restore_config_to, keep_dir / "sleepy.env")
            shutil.copy2(cfg, restore_config_to)
    return {"manifest": manifest, "previous_data": str(keep_dir)}
