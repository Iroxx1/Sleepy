"""Parser abstraction.

Parsers never touch the user's original files directly.  The backend hands them
a :class:`FileSet` – a mapping from the path *relative to the SD card root* to a
readable local file (usually inside the immutable raw archive).  This allows
re-parsing any time from the archive, e.g. after a parser improvement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .model import DeviceInfo, FileClassification, NightPlan, ParsedNight


class ParserError(Exception):
    """A file or data set could not be interpreted."""


class FormatNotSupported(ParserError):
    """The format was recognised but is not (yet) supported."""


@dataclass
class FileSet:
    """Relative path (POSIX, as on the SD card) -> local file path."""

    files: dict[str, Path] = field(default_factory=dict)
    #: older versions of a path (oldest first), e.g. previous STR.edf copies
    history: dict[str, list[Path]] = field(default_factory=dict)

    @classmethod
    def from_directory(cls, root: str | Path) -> FileSet:
        root = Path(root)
        files: dict[str, Path] = {}
        for p in sorted(root.rglob("*")):
            if p.is_file() and not p.is_symlink():
                files[p.relative_to(root).as_posix()] = p
        return cls(files)

    def __contains__(self, rel: str) -> bool:
        return self.find(rel) is not None

    def find(self, rel: str) -> str | None:
        """Case-insensitive lookup (FAT file systems are case-insensitive)."""
        if rel in self.files:
            return rel
        low = rel.lower()
        for k in self.files:
            if k.lower() == low:
                return k
        return None

    def path(self, rel: str) -> Path:
        k = self.find(rel)
        if k is None:
            raise KeyError(rel)
        return self.files[k]

    def names(self) -> list[str]:
        return list(self.files.keys())

    def versions(self, rel: str) -> list[Path]:
        """All known versions of a path, oldest first, current last."""
        k = self.find(rel)
        if k is None:
            return []
        return [*self.history.get(k, []), self.files[k]]

    def subset(self, rels: Iterable[str]) -> FileSet:
        rels = list(rels)
        return FileSet(
            {r: self.files[r] for r in rels if r in self.files},
            {r: self.history[r] for r in rels if r in self.history},
        )


@dataclass
class Detection:
    parser: str
    confidence: float  # 0..1
    supported: bool = True
    reason: str = ""


class CPAPParser(ABC):
    """Base class for all manufacturer specific parsers."""

    #: unique id, e.g. "resmed"
    name: str = ""
    manufacturer: str = ""
    #: bump whenever interpretation changes so nights can be re-processed
    version: str = "1"

    @abstractmethod
    def detect(self, files: FileSet) -> Detection | None:
        """Return a detection result if the file set looks like this format."""

    @abstractmethod
    def identify(self, files: FileSet) -> DeviceInfo:
        """Extract device information (manufacturer, model, serial, ...)."""

    @abstractmethod
    def classify(self, rel_path: str) -> FileClassification:
        """Describe what a single file is (for the import report)."""

    @abstractmethod
    def plan(self, files: FileSet) -> list[NightPlan]:
        """List the nights contained in the file set and their files."""

    @abstractmethod
    def parse_night(self, files: FileSet, night: date) -> ParsedNight:
        """Parse one night completely."""

    def summaries(self, files: FileSet) -> dict[date, dict]:
        """Raw daily summary records (used to detect changed summary data)."""
        return {}

    def find_roots(self, rel_paths: Iterable[str]) -> list[str]:
        """Return path prefixes ("" or "dir/sub/") that look like data roots."""
        return []


_REGISTRY: list[CPAPParser] = []


def register(parser: CPAPParser) -> CPAPParser:
    _REGISTRY.append(parser)
    return parser


def parsers() -> list[CPAPParser]:
    return list(_REGISTRY)


def get_parser(name: str) -> CPAPParser:
    for p in _REGISTRY:
        if p.name == name:
            return p
    raise KeyError(name)


def detect(files: FileSet | Mapping[str, Path]) -> tuple[CPAPParser, Detection] | None:
    fs = files if isinstance(files, FileSet) else FileSet(dict(files))
    best: tuple[CPAPParser, Detection] | None = None
    for p in _REGISTRY:
        d = p.detect(fs)
        if d and (best is None or d.confidence > best[1].confidence):
            best = (p, d)
    return best
