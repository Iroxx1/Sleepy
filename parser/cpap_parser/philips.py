"""Philips Respironics (System One / DreamStation) – detection only.

Philips SD cards contain a ``P-Series`` directory (as used by OSCAR's PRS1
loader for detection).  The binary formats (.000/.001/.002/.005/.006 chunks,
several versions, DreamStation 2 additionally encrypted) are *not* implemented
here.  Rather than guessing, the importer reports the card as recognised but
unsupported and still archives all original files, so they can be parsed once
a parser exists.  See docs/PARSERS.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import PurePosixPath

from .base import CPAPParser, Detection, FileSet, FormatNotSupported, register
from .model import DeviceInfo, FileClassification, NightPlan, ParsedNight


class PhilipsParser(CPAPParser):
    name = "philips"
    manufacturer = "Philips Respironics"
    version = "0"

    def find_roots(self, rel_paths: Iterable[str]) -> list[str]:
        roots = set()
        for rel in rel_paths:
            parts = PurePosixPath(rel).parts
            low = [p.lower() for p in parts]
            if "p-series" in low[:-1]:
                i = low.index("p-series")
                roots.add("/".join(parts[:i]))
        return sorted(r + "/" if r else "" for r in roots)

    def detect(self, files: FileSet) -> Detection | None:
        if any(n.lower().startswith("p-series/") for n in files.names()):
            return Detection(
                self.name,
                0.9,
                supported=False,
                reason="P-Series Verzeichnis gefunden – Philips-Format wird noch nicht unterstützt",
            )
        return None

    def identify(self, files: FileSet) -> DeviceInfo:
        return DeviceInfo(manufacturer=self.manufacturer, data_format="Philips P-Series (nicht unterstützt)")

    def classify(self, rel_path: str) -> FileClassification:
        return FileClassification(rel_path, "other", "Philips-Datei (nur archiviert)")

    def plan(self, files: FileSet) -> list[NightPlan]:
        raise FormatNotSupported("Philips-Daten werden erkannt und archiviert, aber noch nicht ausgewertet.")

    def parse_night(self, files: FileSet, night: date) -> ParsedNight:
        raise FormatNotSupported("Philips-Daten werden erkannt und archiviert, aber noch nicht ausgewertet.")


PARSER = register(PhilipsParser())
