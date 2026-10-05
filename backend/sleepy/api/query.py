"""Tiny search language for nights.

Examples::

    ahi>5                    nights with AHI above 5
    ahi>=2 leak>20           both conditions
    usage<4h                 less than 4 hours of usage
    event:CA                 at least one central apnea
    event:OA>=5              at least five obstructive apneas
    2026-09                  September 2026
    2026-09-01..2026-09-15   date range
    device:23000000001       device by serial number (or id)
    notizen                  nights with notes
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date

from cpap_parser.channels import EVENTS

from ..repo import FILTER_KEYS

_COND = re.compile(r"^([a-z_0-9]+)(<=|>=|=|<|>)(-?\d+(?:[.,]\d+)?)(h|min)?$", re.I)
_EVENT = re.compile(r"^(?:event|ereignis):([a-z]+)(?:(>=|>|=)(\d+))?$", re.I)


class QueryError(ValueError):
    pass


@dataclass
class ParsedQuery:
    date_from: date | None = None
    date_to: date | None = None
    ranges: dict[str, list] = field(default_factory=dict)
    event_codes: list[str] = field(default_factory=list)
    event_min: int = 1
    device: str | None = None
    has_notes: bool | None = None


def _month_range(y: int, m: int) -> tuple[date, date]:
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _parse_date_token(tok: str) -> tuple[date, date] | None:
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", tok):
            d = date.fromisoformat(tok)
            return d, d
        if re.fullmatch(r"\d{4}-\d{2}", tok):
            y, m = map(int, tok.split("-"))
            return _month_range(y, m)
        if re.fullmatch(r"\d{4}", tok):
            y = int(tok)
            return date(y, 1, 1), date(y, 12, 31)
        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}", tok):
            d, m, y = map(int, tok.split("."))
            dd = date(y, m, d)
            return dd, dd
    except ValueError:
        return None
    return None


def parse_query(q: str) -> ParsedQuery:
    pq = ParsedQuery()
    for tok in q.strip().split():
        low = tok.lower()
        if low in ("notizen", "notes", "notiz"):
            pq.has_notes = True
            continue
        if ".." in tok:
            a, b = tok.split("..", 1)
            ra, rb = _parse_date_token(a), _parse_date_token(b)
            if not ra or not rb:
                raise QueryError(f"Ungültiger Zeitraum: {tok}")
            pq.date_from, pq.date_to = ra[0], rb[1]
            continue
        dr = _parse_date_token(tok)
        if dr:
            pq.date_from, pq.date_to = dr
            continue
        m = _EVENT.match(tok)
        if m:
            code = m.group(1).upper()
            if code == "RE":
                code = "RERA"
            if code not in EVENTS:
                raise QueryError(f"Unbekannter Ereignistyp: {m.group(1)} (bekannt: {', '.join(EVENTS)})")
            pq.event_codes.append(code)
            if m.group(3):
                n = int(m.group(3))
                pq.event_min = n + 1 if m.group(2) == ">" else n
            continue
        if low.startswith(("device:", "gerät:", "geraet:")):
            pq.device = tok.split(":", 1)[1]
            continue
        m = _COND.match(tok)
        if m:
            name, op, num, unit = m.groups()
            name = name.lower()
            key = FILTER_KEYS.get(name)
            if key is None:
                raise QueryError(f"Unbekannte Kennzahl '{name}'. Bekannt: {', '.join(FILTER_KEYS)}")
            v = float(num.replace(",", "."))
            if unit and unit.lower() == "min":
                v /= 60
            lo, hi = pq.ranges.get(key, [None, None])
            eps = 1e-9
            if op == ">":
                lo = v + eps
            elif op == ">=":
                lo = v
            elif op == "<":
                hi = v - eps
            elif op == "<=":
                hi = v
            else:
                lo = hi = v
            pq.ranges[key] = [lo, hi]
            continue
        raise QueryError(f"Suchbegriff nicht verstanden: '{tok}'")
    return pq
