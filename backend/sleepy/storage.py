"""File storage: immutable raw archive and normalised signal arrays."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import uuid
from pathlib import Path

import numpy as np

from .config import get_settings

CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def raw_rel_path(sha: str) -> str:
    return f"{sha[:2]}/{sha[2:4]}/{sha}"


def raw_abs_path(rel: str) -> Path:
    return get_settings().raw_dir / rel


def archive_raw(src: Path, sha: str) -> tuple[str, bool]:
    """Copy *src* into the content addressed archive.

    Returns (relative storage path, created).  Existing archive files are never
    overwritten.  Archived files are made read-only.
    """
    rel = raw_rel_path(sha)
    dest = raw_abs_path(rel)
    if dest.exists():
        return rel, False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + f".tmp-{uuid.uuid4().hex}")
    h = hashlib.sha256()
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        while True:
            b = fi.read(CHUNK)
            if not b:
                break
            h.update(b)
            fo.write(b)
        fo.flush()
        os.fsync(fo.fileno())
    if h.hexdigest() != sha:
        tmp.unlink(missing_ok=True)
        raise OSError(f"Prüfsumme hat sich beim Kopieren geändert: {src}")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IRGRP)
    os.replace(tmp, dest)
    return rel, True


# ------------------------------------------------------------------ signals
def new_generation() -> str:
    return uuid.uuid4().hex[:12]


def night_signal_dir(device_id: int, night_date, gen: str) -> Path:
    return get_settings().signals_dir / str(device_id) / f"{night_date:%Y}" / f"{night_date:%Y-%m-%d}" / gen


def signal_rel(path: Path) -> str:
    return path.relative_to(get_settings().signals_dir).as_posix()


def signal_abs(rel: str) -> Path:
    return get_settings().signals_dir / rel


def write_signal(path: Path, digital: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, np.ascontiguousarray(digital, dtype="<i2"), allow_pickle=False)


def load_signal(rel: str) -> np.ndarray:
    return np.load(signal_abs(rel), mmap_mode="r", allow_pickle=False)


def remove_generation(device_id: int, night_date, gen: str | None) -> None:
    if not gen:
        return
    d = night_signal_dir(device_id, night_date, gen)
    shutil.rmtree(d, ignore_errors=True)


def dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total
