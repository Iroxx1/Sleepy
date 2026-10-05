"""Import pipeline.

Stages:  check -> detect -> archive -> parse/store -> analyse -> done

* Every original file is hashed (SHA-256) and archived unchanged (read-only,
  content addressed).  The same content is stored only once.
* Every import records, per file, whether it was new, an updated version of a
  known file, a duplicate, ignored or faulty.
* Nights are rebuilt from the archive only if one of their files changed (or
  the device's daily summary for that night changed).
"""

from __future__ import annotations

import logging
import os
import shutil
import time
import traceback
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import cpap_parser
from cpap_parser import CPAPParser, FileSet, FormatNotSupported

from .. import storage
from ..config import get_settings
from ..db import SessionLocal
from ..models import (
    Device,
    DeviceFile,
    Import,
    ImportFile,
    Night,
    RawFile,
    ServerFileIndex,
    User,
    utcnow,
)
from .processing import rebuild_night
from .zipsafe import UnsafeArchive, extract_zip, is_junk

log = logging.getLogger(__name__)

STAGES = {
    "check": ("Prüfung", 0.00, 0.05),
    "detect": ("Erkennung", 0.05, 0.10),
    "archive": ("Archivierung", 0.10, 0.40),
    "parse": ("Parsing, Validierung & Speicherung", 0.40, 0.95),
    "analyze": ("Analyse", 0.95, 0.99),
}


STAT_KEYS = (
    "files_total", "files_new", "files_updated", "files_duplicate", "files_ignored", "files_error",
    "nights_created", "nights_updated", "nights_unchanged", "nights_failed", "devices_new",
)


DEMO_SERIAL = "DEMO00000001"


class ImportAbort(Exception):
    """User-facing import failure."""


def new_import_id() -> str:
    return uuid.uuid4().hex


def staging_path(import_id: str) -> Path:
    return get_settings().staging_dir / import_id


class Runner:
    def __init__(self, import_id: str, mode: str = "full"):
        self.import_id = import_id
        self.mode = mode  # full | reprocess
        self.db: Session = SessionLocal()
        self.imp: Import = self.db.get(Import, import_id)
        self._last_commit = 0.0
        self.stats: dict = defaultdict(int)
        self.log_lines: list[dict] = list(self.imp.log or []) if self.imp else []

    # ---------------------------------------------------------------- utils
    def logmsg(self, level: str, text: str, file: str | None = None) -> None:
        entry = {"t": datetime.now().isoformat(timespec="seconds"), "level": level, "text": text}
        if file:
            entry["file"] = file
        self.log_lines.append(entry)
        getattr(log, "warning" if level == "warning" else "error" if level == "error" else "info")(
            "[import %s] %s%s", self.import_id[:8], text, f" ({file})" if file else ""
        )

    def progress(self, stage: str, frac: float, message: str | None = None, force: bool = False) -> None:
        name, a, b = STAGES[stage]
        self.imp.stage = stage
        self.imp.progress = round(a + (b - a) * max(0.0, min(1.0, frac)), 4)
        if message:
            self.imp.message = message
        now = time.monotonic()
        if force or now - self._last_commit > 0.7:
            self.flush()

    def flush(self) -> None:
        self.imp.log = self.log_lines[-2000:]
        self.imp.stats = dict(self.stats)
        self.db.commit()
        self._last_commit = time.monotonic()

    # ----------------------------------------------------------------- run
    def run(self) -> None:
        if self.imp is None:
            return
        imp = self.imp
        imp.status = "running"
        imp.started_at = utcnow()
        imp.error = None
        self.stats = defaultdict(int)
        for k in STAT_KEYS:
            self.stats[k] = 0
        self.flush()
        try:
            if self.mode == "reprocess":
                self.run_reprocess()
            else:
                self.run_full()
            if self.stats.get("nights_failed") or self.stats.get("files_error"):
                imp.status = "completed_with_errors"
            else:
                imp.status = "completed"
            imp.message = self.final_message()
            imp.progress = 1.0
            imp.stage = "done"
            if imp.source in ("zip", "folder", "demo") and imp.status == "completed":
                shutil.rmtree(staging_path(imp.id), ignore_errors=True)
        except ImportAbort as exc:
            self.db.rollback()
            imp = self.imp = self.db.get(Import, self.import_id)
            imp.status = "failed"
            imp.error = str(exc)
            imp.message = f"Import fehlgeschlagen: {exc}"
            self.logmsg("error", str(exc))
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            imp = self.imp = self.db.get(Import, self.import_id)
            ref = uuid.uuid4().hex[:8]
            log.error("import %s failed (ref %s): %s", self.import_id, ref, traceback.format_exc())
            imp.status = "failed"
            imp.error = f"Interner Fehler (Referenz {ref}): {type(exc).__name__}: {exc}"
            imp.message = "Import fehlgeschlagen. Details siehe Protokoll; die Originaldaten wurden nicht verändert."
            self.logmsg("error", imp.error)
        finally:
            imp.finished_at = utcnow()
            try:
                self.flush()
            finally:
                self.db.close()

    def final_message(self) -> str:
        s = self.stats
        parts = []
        if self.mode == "reprocess":
            parts.append(f"{s.get('nights_updated', 0) + s.get('nights_created', 0)} Nächte neu berechnet.")
        else:
            parts.append(f"{s.get('nights_created', 0)} neue Nächte importiert.")
            if s.get("nights_updated"):
                parts.append(f"{s['nights_updated']} Nächte aktualisiert.")
            parts.append(f"{s.get('files_duplicate', 0)} Dateien bereits vorhanden.")
        errors = s.get("files_error", 0) + s.get("nights_failed", 0)
        parts.append(f"{errors} Fehler.")
        return " ".join(parts)

    # ------------------------------------------------------------ collect
    def collect(self) -> list[tuple[str, Path]]:
        imp = self.imp
        st = get_settings()
        base = staging_path(imp.id)
        files: list[tuple[str, Path]] = []
        if imp.source == "zip":
            zips = sorted((base / "upload").glob("*")) if (base / "upload").exists() else []
            if not zips:
                raise ImportAbort("Keine hochgeladene ZIP-Datei gefunden (Upload abgebrochen?).")
            extract_root = base / "files"
            if extract_root.exists():
                shutil.rmtree(extract_root)
            for z in zips:
                self.progress("check", 0.2, f"Entpacke {z.name} …", force=True)
                try:
                    rels = extract_zip(z, extract_root / z.stem, st.max_unzipped_mb * 1024 * 1024)
                except UnsafeArchive as exc:
                    raise ImportAbort(str(exc)) from exc
                files.extend((f"{z.stem}/{r}", extract_root / z.stem / r) for r in rels)
        elif imp.source == "demo":
            from datetime import date as _date

            from cpap_parser.testing.synthetic_resmed import write_card

            root = base / "files"
            if not root.exists() or not any(root.rglob("*")):
                n = int(imp.options.get("nights", 60))
                first = _date.today() - timedelta(days=n)
                self.progress("check", 0.1, f"Erzeuge {n} synthetische Beispielnächte …", force=True)
                write_card(root / "DEMO_SD", first, n, seed=int(imp.options.get("seed", 2026)),
                           serial=DEMO_SERIAL, oximetry=bool(imp.options.get("oximetry", False)))
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    files.append((p.relative_to(root).as_posix(), p))
        elif imp.source == "folder":
            root = base / "files"
            if not root.exists():
                raise ImportAbort("Keine hochgeladenen Dateien gefunden (Upload abgebrochen?).")
            for p in sorted(root.rglob("*")):
                if p.is_file() and not p.is_symlink():
                    files.append((p.relative_to(root).as_posix(), p))
        elif imp.source == "server_dir":
            src = Path(imp.options.get("path") or st.import_dir or "")
            if not src or not src.is_dir():
                raise ImportAbort(f"Server-Importverzeichnis {src} existiert nicht oder ist nicht lesbar.")
            for p in sorted(src.rglob("*")):
                if p.is_file() and not p.is_symlink():
                    files.append((p.relative_to(src).as_posix(), p))
        else:
            raise ImportAbort(f"Unbekannte Importquelle {imp.source}")
        if not files:
            raise ImportAbort("Die Importquelle enthält keine Dateien.")
        return files

    # --------------------------------------------------------------- full
    def run_full(self) -> None:
        self.progress("check", 0.0, "Prüfe Upload …", force=True)
        files = self.collect()
        self.stats["files_total"] = len(files)
        junk = [(r, p) for r, p in files if is_junk(r)]
        files = [(r, p) for r, p in files if not is_junk(r)]
        for r, p in junk:
            self.db.add(ImportFile(import_id=self.imp.id, path=r[:1024], status="ignored", size=p.stat().st_size,
                                   message="Systemdatei (z. B. macOS/Windows) ignoriert"))
            self.stats["files_ignored"] += 1
        self.progress("check", 1.0, f"{len(files)} Dateien gefunden", force=True)

        # ---- detection
        self.progress("detect", 0.0, "Erkenne Gerät und Datenformat …", force=True)
        rels = [r for r, _ in files]
        root_parser: dict[str, CPAPParser] = {}
        for parser in cpap_parser.parsers():
            for root in parser.find_roots(rels):
                if root not in root_parser:
                    root_parser[root] = parser
        if not root_parser:
            sample = ", ".join(sorted({r.split("/")[0] for r in rels})[:8])
            raise ImportAbort(
                "Keine bekannten CPAP-Daten erkannt. Erwartet wird der Inhalt der SD-Karte "
                "(z. B. STR.edf, Identification.tgt/.json und der Ordner DATALOG). "
                f"Gefunden: {sample}"
            )
        roots_sorted = sorted(root_parser, key=len, reverse=True)
        groups: dict[str, list[tuple[str, str, Path]]] = defaultdict(list)
        for r, p in files:
            for root in roots_sorted:
                if r.startswith(root):
                    groups[root].append((r, r[len(root):], p))
                    break
            else:
                self.db.add(ImportFile(import_id=self.imp.id, path=r[:1024], status="ignored", size=p.stat().st_size,
                                       message="Liegt außerhalb eines erkannten Geräteverzeichnisses"))
                self.stats["files_ignored"] += 1

        plans = []
        for root, items in groups.items():
            parser = root_parser[root]
            fs = FileSet({sd: p for _r, sd, p in items})
            detection = parser.detect(fs)
            if detection is None:
                continue
            info = parser.identify(fs)
            if not detection.supported:
                self.logmsg("warning", f"{info.manufacturer}: {detection.reason}. Dateien werden nur archiviert.")
            device = self.get_device(parser, info) if detection.supported else None
            if device:
                self.logmsg(
                    "info",
                    f"Gerät erkannt: {device.manufacturer} {device.model or ''} (SN {device.serial}) "
                    f"in '{root or '/'}' – {detection.reason}",
                )
            plans.append((root, parser, detection, device, items))
        self.progress("detect", 1.0, f"{len(plans)} Datenquelle(n) erkannt", force=True)

        # ---- archive
        total = sum(len(x[4]) for x in plans) or 1
        done = 0
        changed: dict[int, set[str]] = defaultdict(set)
        for _root, parser, _detection, device, items in plans:
            for upload_rel, sd_rel, path in items:
                done += 1
                self.archive_file(parser, device, upload_rel, sd_rel, path, changed)
                self.progress("archive", done / total, f"Archiviere Dateien ({done}/{total}) …")
        self.flush()

        # ---- parse
        devices = [(parser, device) for _r, parser, det, device, _ in plans if device is not None and det.supported]
        self.process_devices(devices, changed)

        self.progress("analyze", 0.5, "Erstelle Statistiken …", force=True)
        self.progress("analyze", 1.0, force=True)

    def get_device(self, parser: CPAPParser, info) -> Device:
        serial = info.serial or "unbekannt"
        dev = self.db.scalar(
            select(Device).where(
                Device.owner_id == self.imp.owner_id,
                Device.manufacturer == info.manufacturer,
                Device.serial == serial,
            )
        )
        if dev is None:
            dev = Device(owner_id=self.imp.owner_id, manufacturer=info.manufacturer, serial=serial, parser=parser.name)
            self.db.add(dev)
            self.stats["devices_new"] += 1
        for attr in ("model", "product_code", "firmware", "series", "device_type", "data_format"):
            v = getattr(info, attr)
            if v:
                setattr(dev, attr, v)
        dev.identification = info.identification
        if serial.startswith("DEMO") and not dev.display_name:
            dev.display_name = "Demo-Gerät (synthetische Beispieldaten)"
        dev.parser = parser.name
        dev.last_seen_at = utcnow()
        self.db.flush()
        return dev

    def hash_file(self, path: Path) -> str:
        if self.imp.source != "server_dir":
            return storage.sha256_file(path)
        st = path.stat()
        row = self.db.scalar(select(ServerFileIndex).where(ServerFileIndex.path == str(path)))
        if row and row.size == st.st_size and row.mtime_ns == st.st_mtime_ns:
            return row.sha256
        sha = storage.sha256_file(path)
        if row is None:
            row = ServerFileIndex(path=str(path), size=st.st_size, mtime_ns=st.st_mtime_ns, sha256=sha)
            self.db.add(row)
        else:
            row.size, row.mtime_ns, row.sha256 = st.st_size, st.st_mtime_ns, sha
        return sha

    def archive_file(self, parser, device, upload_rel, sd_rel, path: Path, changed) -> None:
        cls = parser.classify(sd_rel)
        rec = ImportFile(import_id=self.imp.id, path=upload_rel[:1024], sd_path=sd_rel[:1024],
                         device_id=device.id if device else None, kind=cls.kind)
        try:
            size = path.stat().st_size
            rec.size = size
            sha = self.hash_file(path)
            rec.sha256 = sha
            raw = self.db.scalar(select(RawFile).where(RawFile.sha256 == sha))
            if raw is None:
                rel, _created = storage.archive_raw(path, sha)
                raw = RawFile(sha256=sha, size=size, storage_path=rel)
                self.db.add(raw)
                self.db.flush()
            rec.raw_file_id = raw.id
            if device is None:
                rec.status = "ignored"
                rec.message = "Archiviert; Format wird (noch) nicht ausgewertet"
                self.stats["files_archived_only"] += 1
            else:
                latest = self.db.scalar(
                    select(DeviceFile)
                    .where(DeviceFile.device_id == device.id, DeviceFile.rel_path == sd_rel)
                    .order_by(DeviceFile.created_at.desc(), DeviceFile.id.desc())
                    .limit(1)
                )
                if latest is not None and latest.raw_file_id == raw.id:
                    rec.status = "duplicate"
                    rec.message = "Bereits importiert (identischer Inhalt)"
                    self.stats["files_duplicate"] += 1
                else:
                    rec.status = "updated" if latest is not None else "new"
                    if latest is not None:
                        rec.message = "Neue Version einer bekannten Datei"
                    same = self.db.scalar(
                        select(DeviceFile).where(
                            DeviceFile.device_id == device.id,
                            DeviceFile.rel_path == sd_rel,
                            DeviceFile.raw_file_id == raw.id,
                        )
                    )
                    if same is not None:  # an older version re-appeared
                        same.created_at = utcnow()
                        same.import_id = self.imp.id
                    else:
                        self.db.add(DeviceFile(device_id=device.id, rel_path=sd_rel, raw_file_id=raw.id,
                                               import_id=self.imp.id))
                    changed[device.id].add(sd_rel)
                    self.stats[f"files_{rec.status}"] += 1
        except OSError as exc:
            rec.status = "error"
            rec.message = f"Datei konnte nicht gelesen/archiviert werden: {exc}"
            self.stats["files_error"] += 1
            self.logmsg("error", rec.message, upload_rel)
        self.db.add(rec)

    # ----------------------------------------------------------- processing
    def device_fileset(self, device: Device) -> tuple[FileSet, dict[str, int]]:
        rows = self.db.execute(
            select(DeviceFile.rel_path, DeviceFile.raw_file_id, RawFile.storage_path)
            .join(RawFile, RawFile.id == DeviceFile.raw_file_id)
            .where(DeviceFile.device_id == device.id)
            .order_by(DeviceFile.created_at, DeviceFile.id)
        ).all()
        files: dict[str, Path] = {}
        history: dict[str, list[Path]] = defaultdict(list)
        raw_ids: dict[str, int] = {}
        for rel, rid, sp in rows:
            if rel in files:
                history[rel].append(files[rel])
            files[rel] = storage.raw_abs_path(sp)
            raw_ids[rel] = rid
        return FileSet(files, dict(history)), raw_ids

    def process_devices(self, devices, changed: dict[int, set[str]], all_nights: bool = False) -> None:
        work = []
        for parser, device in devices:
            fs, raw_ids = self.device_fileset(device)
            try:
                plan = parser.plan(fs)
                summaries = parser.summaries(fs)
            except FormatNotSupported as exc:
                self.logmsg("warning", str(exc))
                continue
            existing = {
                n.date: n
                for n in self.db.scalars(select(Night).where(Night.device_id == device.id))
            }
            ch = changed.get(device.id, set())
            for p in plan:
                n = existing.get(p.date)
                reason = None
                if all_nights:
                    reason = "reprocess"
                elif n is None:
                    reason = "new"
                elif set(p.files) & ch:
                    reason = "files"
                elif p.date in summaries and summaries[p.date] != (n.summary_raw or {}):
                    reason = "summary"
                if reason:
                    work.append((parser, device, fs, raw_ids, p))
            self.stats["nights_unchanged"] += len(plan) - sum(1 for w in work if w[1] is device)
        total = len(work) or 1
        self.progress("parse", 0.0, f"Analysiere {len(work)} Nächte …", force=True)
        dates = []
        for i, (parser, device, fs, raw_ids, p) in enumerate(work):
            self.progress("parse", i / total, f"Analysiere Nacht {p.date:%d.%m.%Y} ({i + 1}/{len(work)}) …")
            try:
                status, warnings = rebuild_night(self.db, device, parser, fs, p.date, raw_ids, self.imp.id)
                self.stats[f"nights_{status}"] += 1
                dates.append(p.date)
                for w in warnings[:20]:
                    self.logmsg("warning", f"{p.date:%d.%m.%Y}: {w}")
            except Exception as exc:  # noqa: BLE001 - one bad night must not stop the import
                self.db.rollback()
                self.imp = self.db.get(Import, self.import_id)
                self.stats["nights_failed"] += 1
                log.error("night %s failed: %s", p.date, traceback.format_exc())
                files = ", ".join(x.rsplit("/", 1)[-1] for x in p.files[:6]) or "STR.edf"
                self.logmsg("error", f"Nacht {p.date:%d.%m.%Y} konnte nicht verarbeitet werden: {exc}", files)
        if dates:
            self.stats["date_from"] = min(dates).isoformat()
            self.stats["date_to"] = max(dates).isoformat()
        self.progress("parse", 1.0, force=True)

    def run_reprocess(self) -> None:
        self.progress("check", 1.0, "Neuberechnung aus dem Rohdatenarchiv …", force=True)
        q = select(Device).where(Device.owner_id == self.imp.owner_id)
        dev_id = self.imp.options.get("device_id")
        if dev_id:
            q = q.where(Device.id == dev_id)
        devices = []
        for d in self.db.scalars(q):
            try:
                devices.append((cpap_parser.get_parser(d.parser), d))
            except KeyError:
                self.logmsg("warning", f"Kein Parser '{d.parser}' für Gerät {d.serial}")
        self.progress("detect", 1.0, force=True)
        self.progress("archive", 1.0, force=True)
        only = self.imp.options.get("import_id")
        if only:
            # re-run nights touched by a specific import (retry)
            changed: dict[int, set[str]] = defaultdict(set)
            for f in self.db.scalars(
                select(ImportFile).where(ImportFile.import_id == only, ImportFile.status.in_(["new", "updated"]))
            ):
                if f.device_id and f.sd_path:
                    changed[f.device_id].add(f.sd_path)
            self.process_devices(devices, changed)
        else:
            self.process_devices(devices, {}, all_nights=True)
        self.progress("analyze", 1.0, force=True)


# --------------------------------------------------------------- helpers
def create_import(db: Session, user: User, source: str, name: str | None = None, options: dict | None = None) -> Import:
    imp = Import(id=new_import_id(), owner_id=user.id, source=source, original_name=name, options=options or {})
    db.add(imp)
    db.commit()
    if source in ("zip", "folder", "demo"):
        staging_path(imp.id).mkdir(parents=True, exist_ok=True)
    return imp


def cleanup_staging(db: Session) -> int:
    """Remove staging directories of finished or abandoned imports."""
    st = get_settings()
    cutoff = utcnow() - timedelta(days=st.staging_retention_days)
    removed = 0
    if not st.staging_dir.exists():
        return 0
    for d in st.staging_dir.iterdir():
        imp = db.get(Import, d.name)
        old = datetime.fromtimestamp(d.stat().st_mtime) < cutoff
        if imp is None or (imp.status in ("completed",) ) or (old and imp.status not in ("running", "queued")):
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    return removed


def disk_free(path: Path) -> int:
    try:
        s = os.statvfs(path)
        return s.f_bavail * s.f_frsize
    except OSError:
        return -1


def count_device_files(db: Session, device_id: int) -> int:
    return db.scalar(select(func.count()).select_from(DeviceFile).where(DeviceFile.device_id == device_id)) or 0
