"""Background worker: runs imports sequentially in a single thread, and
optionally scans the server import directory periodically."""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

from sqlalchemy import select

from ..config import get_settings
from ..db import SessionLocal
from ..models import AppSetting, Import, User, utcnow
from .pipeline import Runner, cleanup_staging, create_import

log = logging.getLogger(__name__)


class ImportWorker:
    def __init__(self) -> None:
        self.q: queue.Queue[tuple[str, str]] = queue.Queue()
        self.thread: threading.Thread | None = None
        self.scan_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.current: str | None = None
        self.synchronous = False  # tests: run inline

    def start(self) -> None:
        self.recover()
        if self.synchronous:
            return
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._loop, name="import-worker", daemon=True)
            self.thread.start()
        st = get_settings()
        if st.import_dir and st.import_scan_interval_minutes > 0:
            self.scan_thread = threading.Thread(target=self._scan_loop, name="import-scan", daemon=True)
            self.scan_thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def recover(self) -> None:
        """Imports interrupted by a restart are marked failed (retry possible)."""
        with SessionLocal() as db:
            for imp in db.scalars(select(Import).where(Import.status.in_(["running", "queued"]))):
                imp.status = "failed"
                imp.error = "Durch Neustart des Dienstes unterbrochen."
                imp.message = "Import unterbrochen – bitte 'Erneut versuchen' wählen."
                imp.finished_at = utcnow()
            db.commit()
            cleanup_staging(db)

    def enqueue(self, import_id: str, mode: str = "full") -> None:
        with SessionLocal() as db:
            imp = db.get(Import, import_id)
            if imp:
                imp.status = "queued"
                imp.message = "In Warteschlange …"
                imp.progress = 0.0
                db.commit()
        if self.synchronous:
            Runner(import_id, mode).run()
        else:
            self.q.put((import_id, mode))

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                import_id, mode = self.q.get(timeout=1.0)
            except queue.Empty:
                continue
            self.current = import_id
            try:
                Runner(import_id, mode).run()
            except Exception:  # pragma: no cover - Runner handles its own errors
                log.exception("import worker crashed for %s", import_id)
            finally:
                self.current = None

    # ------------------------------------------------------------ auto scan
    def _scan_loop(self) -> None:
        st = get_settings()
        interval = max(1, st.import_scan_interval_minutes) * 60
        while not self.stop_event.wait(interval):
            try:
                self.scan_server_dir(automatic=True)
            except Exception:  # pragma: no cover
                log.exception("automatic import scan failed")

    def scan_server_dir(self, user_id: int | None = None, automatic: bool = False) -> str | None:
        st = get_settings()
        src = st.import_dir
        if not src or not Path(src).is_dir():
            return None
        sig = _dir_signature(Path(src))
        with SessionLocal() as db:
            key = "server_dir_signature"
            row = db.get(AppSetting, key)
            if automatic and row is not None and row.value == sig:
                return None
            if user_id is None:
                admin = db.scalar(select(User).where(User.role == "admin", User.is_active.is_(True)).order_by(User.id))
                if admin is None:
                    return None
                user_id = admin.id
            user = db.get(User, user_id)
            imp = create_import(db, user, "server_dir", str(src), {"path": str(src), "automatic": automatic})
            if row is None:
                db.add(AppSetting(key=key, value=sig))
            else:
                row.value = sig
            db.commit()
            imp_id = imp.id
        self.enqueue(imp_id)
        return imp_id


def _dir_signature(root: Path) -> list:
    n = 0
    size = 0
    mtime = 0
    for p in root.rglob("*"):
        try:
            if p.is_file():
                st = p.stat()
                n += 1
                size += st.st_size
                mtime = max(mtime, st.st_mtime_ns)
        except OSError:
            continue
    return [n, size, mtime]


worker = ImportWorker()


def wait_idle(timeout: float = 60.0) -> bool:
    """Test helper: wait until the queue is empty and nothing runs."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if worker.q.empty() and worker.current is None:
            return True
        time.sleep(0.05)
    return False
