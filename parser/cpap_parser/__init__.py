"""Modular CPAP/PAP data parsers.

Importing this package registers all available parsers::

    from cpap_parser import detect, FileSet
    fs = FileSet.from_directory("/media/sdcard")
    parser, detection = detect(fs)
"""

from . import loewenstein, philips, resmed  # noqa: F401  (registration side effect)
from .base import (
    CPAPParser,
    Detection,
    FileSet,
    FormatNotSupported,
    ParserError,
    detect,
    get_parser,
    parsers,
    setting_names,
)
from .model import (
    DeviceInfo,
    NightPlan,
    ParsedEvent,
    ParsedNight,
    ParsedSession,
    ParsedSignal,
    from_wall_ms,
    wall_ms,
)

__version__ = "1.0.0"

__all__ = [
    "CPAPParser",
    "Detection",
    "DeviceInfo",
    "FileSet",
    "FormatNotSupported",
    "NightPlan",
    "ParsedEvent",
    "ParsedNight",
    "ParsedSession",
    "ParsedSignal",
    "ParserError",
    "detect",
    "from_wall_ms",
    "get_parser",
    "parsers",
    "setting_names",
    "wall_ms",
]
