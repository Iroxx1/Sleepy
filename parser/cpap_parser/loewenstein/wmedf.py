"""Reader for Löwenstein "WMEDF" signal files (``signal_<n>.wmedf``).

WMEDF uses the EDF header layout (https://www.edfplus.info/) with two
differences found in real prisma SMART files:

* the version field is ``1`` instead of ``0``;
* every signal's *reserved* field states its sample width: ``#1`` = 8 bit,
  ``#2`` = 16 bit little endian.  8 bit channels are unsigned when the digital
  minimum is >= 0, otherwise signed.

The record count in the header is checked against the file size; the file
size wins (a file that is still being written may announce more records).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..edf import EDFError, EDFFile, _parse_header, _read_bytes, read_header_bytes

WMEDF_VERSIONS = ("0", "1")


def _dtype(edf: EDFFile) -> np.dtype:
    fields = []
    for s in edf.signals:
        width = s.reserved.strip()
        if width == "#1":
            base = "u1" if s.digital_min >= 0 else "i1"
        elif width == "#2":
            base = "<i2"
        else:
            raise EDFError(f"Signal {s.label!r}: unbekannte Sample-Breite {width!r} (erwartet #1 oder #2)")
        fields.append((f"s{s.index}", base, (s.samples_per_record,)))
    return np.dtype(fields)


def read_wmedf_header(path: str | Path) -> EDFFile:
    edf, _ = _parse_header(read_header_bytes(path), str(path), versions=WMEDF_VERSIONS)
    return edf


def read_wmedf(path: str | Path) -> EDFFile:
    """Read header and all samples; ``signal.digital`` is int16 for every channel."""
    raw = _read_bytes(path)
    edf, hb = _parse_header(raw, str(path), versions=WMEDF_VERSIONS)
    dt = _dtype(edf)
    if dt.itemsize <= 0:
        raise EDFError("record without samples")
    available = (len(raw) - hb) // dt.itemsize
    n = edf.n_records
    if n < 0 or n > available:
        if n > available:
            edf.warnings.append(f"Datei unvollständig: Header nennt {n} Datensätze, vorhanden sind {available}")
            edf.truncated = True
        n = available
    edf.n_records = n
    rec = np.frombuffer(raw, dtype=dt, count=n, offset=hb)
    for s in edf.signals:
        s.digital = rec[f"s{s.index}"].reshape(-1).astype(np.int16)
    return edf
