"""Safe ZIP extraction (path traversal, symlinks, zip bombs)."""

from __future__ import annotations

import os
import stat
import zipfile
from pathlib import Path, PurePosixPath

JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
JUNK_DIRS = {"__macosx", "system volume information", ".spotlight-v100", ".trashes", ".fseventsd"}


class UnsafeArchive(Exception):
    pass


def is_junk(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    if not parts:
        return True
    if any(p.lower() in JUNK_DIRS for p in parts[:-1]):
        return True
    name = parts[-1]
    return name.lower() in JUNK_NAMES or name.startswith("._")


def safe_rel(name: str) -> str | None:
    """Normalise an archive member name; None if it is unsafe."""
    n = name.replace("\\", "/")
    if n.startswith("/") or (len(n) > 1 and n[1] == ":"):
        return None
    parts = []
    for p in n.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            return None
        parts.append(p)
    return "/".join(parts) if parts else None


def extract_zip(zip_path: Path, dest: Path, max_total_bytes: int, max_files: int = 200_000) -> list[str]:
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise UnsafeArchive(f"Die Datei ist kein gültiges ZIP-Archiv ({exc}).") from exc
    out: list[str] = []
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > max_files:
            raise UnsafeArchive(f"Das Archiv enthält zu viele Dateien ({len(infos)}).")
        total = sum(i.file_size for i in infos)
        if total > max_total_bytes:
            raise UnsafeArchive(
                f"Das entpackte Archiv wäre {total / 1e9:.1f} GB groß und überschreitet das Limit "
                f"von {max_total_bytes / 1e9:.1f} GB."
            )
        dest.mkdir(parents=True, exist_ok=True)
        written = 0
        for info in infos:
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                continue  # never extract symlinks
            rel = safe_rel(info.filename)
            if rel is None:
                raise UnsafeArchive(f"Unsicherer Pfad im Archiv: {info.filename!r}")
            if info.flag_bits & 0x1:
                raise UnsafeArchive(f"Verschlüsselte Datei im Archiv: {info.filename!r}")
            target = dest / rel
            if not str(target.resolve()).startswith(str(dest.resolve()) + os.sep):
                raise UnsafeArchive(f"Unsicherer Pfad im Archiv: {info.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                while True:
                    b = src.read(1024 * 1024)
                    if not b:
                        break
                    written += len(b)
                    if written > max_total_bytes:
                        raise UnsafeArchive("Entpackte Datenmenge überschreitet das Limit (Zip-Bombe?).")
                    dst.write(b)
            out.append(rel)
    return out
