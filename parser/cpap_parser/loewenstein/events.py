"""Event files of Löwenstein prisma devices (``event_<n>.xml``).

Structure (as found on a prisma SMART card)::

    <!-- started 1791114372 -->            Unix time of the session start (UTC)
    <desc>
      <DeviceEvent DeviceEventID="0" Time="0" ParameterID="9" NewValue="400"/>
      <RespEvent RespEventID="101" EndTime="1317" Duration="41" Pressure="400" Strength="4"/>
    </desc>

* ``DeviceEvent`` with ``DeviceEventID="0"`` lists therapy parameters
  (ParameterID -> value).
* ``RespEvent``: ``EndTime`` is the end of the event in 1/10 s after the start
  of the matching ``signal_<n>.wmedf``; ``Duration`` is in 1/10 s, the event
  starts at ``EndTime - Duration``.  Verified against real data: the flow
  amplitude collapses exactly in that window for apnoeas (docs/PARSERS.md).
* ``Pressure`` is in 1/100 hPa.  ``Strength`` is stored unchanged.

Event ids and parameter ids follow the publicly documented reverse
engineering of the OSCAR project (prisma loader); codes that are not
documented there are *not* interpreted but counted (``unknown``).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from ..base import ParserError

#: RespEventID -> (canonical event code, German label)
EVENT_CODES: dict[int, tuple[str, str]] = {
    1: ("EPOCH_SO", "Epoche mit schwerer Obstruktion"),
    2: ("EPOCH_MO", "Epoche mit leichter Obstruktion"),
    3: ("EPOCH_FL", "Epoche mit Flusslimitierung"),
    4: ("EPOCH_SN", "Epoche mit Schnarchen"),
    5: ("EPOCH_PB", "Epoche mit periodischer Atmung"),
    101: ("OA", "Obstruktive Apnoe"),
    102: ("CA", "Zentrale Apnoe"),
    103: ("UA", "Apnoe bei Leckage"),
    105: ("UA", "Apnoe bei hohem Druck"),
    106: ("UA", "Apnoe bei Bewegung"),
    111: ("H", "Obstruktive Hypopnoe"),
    112: ("H", "Zentrale Hypopnoe"),
    113: ("H", "Hypopnoe bei Leckage"),
    121: ("RERA", "RERA"),
    131: ("VS", "Schnarchen"),
    141: ("ARTIFACT", "Artefakt"),
    151: ("FL", "Flusslimitierung"),
    161: ("LL", "Kritische Leckage"),
    181: ("CSR", "Cheyne-Stokes-Atmung"),
    221: ("TB", "Gerätegetriggerter Atemzug"),
    261: ("DEEP", "Tiefschlaf-Epoche (Geräteschätzung)"),
}

#: ParameterID -> (settings key, German label, divisor or None for raw value)
PARAMETERS: dict[int, tuple[str, str, float | None]] = {
    6: ("Prisma.Mode", "Modus (Gerätecode)", None),
    9: ("Prisma.Pressure", "Druck / Mindestdruck (hPa)", 100.0),
    10: ("Prisma.PressureMax", "Maximaldruck (hPa)", 100.0),
    11: ("Prisma.PSoftMin", "Softstart-Mindestdruck (hPa)", 100.0),
    12: ("Prisma.PSoft", "Softstart-Druck (hPa)", 100.0),
    13: ("Prisma.SoftPAP", "softPAP-Stufe", None),
    15: ("Prisma.APAPDynamic", "APAP-Regelung (Gerätecode)", None),
    16: ("Prisma.HumidLevel", "Befeuchterstufe", None),
    17: ("Prisma.AutoStart", "Autostart", None),
    18: ("Prisma.SoftStartTimeMax", "Softstart-Zeit maximal (Gerätewert)", None),
    19: ("Prisma.SoftStartTime", "Softstart-Zeit (Gerätewert)", None),
    21: ("Prisma.TubeType", "Schlauchtyp (Gerätewert)", None),
    38: ("Prisma.PMaxOA", "PMaxOA (hPa)", 100.0),
}

MODES = {1: ("CPAP", "CPAP"), 2: ("APAP", "APAP")}
APAP_MODES = {1: "Standard", 2: "Dynamisch"}
SOFTPAP = {0: "Aus", 1: "Leicht", 2: "Standard"}
ON_OFF = {0: "Aus", 1: "Ein"}

_STARTED_RE = re.compile(rb"<!--\s*started\s+(\d+)\s*-->")


@dataclass
class RespEvent:
    event_id: int
    end_ds: int  # 1/10 s after file start
    duration_ds: int  # 1/10 s
    pressure: int  # 1/100 hPa
    strength: int


@dataclass
class EventFile:
    started_unix: int | None
    parameters: dict[int, int] = field(default_factory=dict)
    events: list[RespEvent] = field(default_factory=list)


def _int(el: ET.Element, name: str) -> int:
    v = el.get(name)
    if v is None:
        raise ParserError(f"Attribut {name} fehlt in <{el.tag}>")
    try:
        return int(v.strip())
    except ValueError as exc:
        raise ParserError(f"Attribut {name}={v!r} ist keine Zahl") from exc


def read_event_file(path: str | Path) -> EventFile:
    raw = Path(path).read_bytes()
    head = raw[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise ParserError("XML mit DOCTYPE/ENTITY wird aus Sicherheitsgründen nicht gelesen")
    m = _STARTED_RE.search(raw[:512])
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ParserError(f"Ungültiges XML: {exc}") from exc
    out = EventFile(started_unix=int(m.group(1)) if m else None)
    for el in root.iter("DeviceEvent"):
        if _int(el, "DeviceEventID") == 0:
            out.parameters[_int(el, "ParameterID")] = _int(el, "NewValue")
    for el in root.iter("RespEvent"):
        out.events.append(
            RespEvent(
                event_id=_int(el, "RespEventID"),
                end_ds=_int(el, "EndTime"),
                duration_ds=max(0, _int(el, "Duration")),
                pressure=_int(el, "Pressure"),
                strength=_int(el, "Strength"),
            )
        )
    return out


def settings_from_parameters(params: dict[int, int]) -> tuple[dict, dict]:
    """Return (settings for display, raw values of parameters without known meaning)."""
    settings: dict = {}
    unknown: dict = {}
    for pid, value in sorted(params.items()):
        spec = PARAMETERS.get(pid)
        if spec is None:
            unknown[str(pid)] = value
            continue
        key, _label, div = spec
        settings[key] = round(value / div, 2) if div else value
    mode = params.get(6)
    if mode in MODES:
        kind, name = MODES[mode]
        if kind == "APAP" and params.get(15) in APAP_MODES:
            name = f"APAP ({APAP_MODES[params[15]]})"
        settings["mode_kind"] = kind
        settings["mode_name"] = name
    if 13 in params and params[13] in SOFTPAP:
        settings["Prisma.SoftPAP"] = SOFTPAP[params[13]]
    if 17 in params and params[17] in ON_OFF:
        settings["Prisma.AutoStart"] = ON_OFF[params[17]]
    return settings, unknown


SETTING_NAMES: dict[str, str] = {key: label for key, label, _div in PARAMETERS.values()}
SETTING_NAMES["Prisma.Mode"] = "Modus (Gerätecode)"
