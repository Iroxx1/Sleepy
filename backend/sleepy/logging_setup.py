"""Logging to stdout (journald) and a rotating log file."""

from __future__ import annotations

import logging
import logging.handlers

from .config import get_settings

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    s = get_settings()
    level = getattr(logging, s.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter(FORMAT)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)
    try:
        s.logs_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            s.logs_dir / "sleepy.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError as exc:  # pragma: no cover - read-only FS etc.
        root.warning("Log-Datei kann nicht geschrieben werden: %s", exc)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _configured = True


def tail_log(lines: int = 200) -> list[str]:
    p = get_settings().logs_dir / "sleepy.log"
    if not p.exists():
        return []
    with open(p, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - 256 * 1024))
        data = fh.read().decode("utf-8", errors="replace")
    return data.splitlines()[-lines:]
