"""ResMed Identification.tgt (S9/AirSense 10/AirCurve 10) and
Identification.json (AirSense 11) parsing."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..model import DeviceInfo

# Known keys in Identification.tgt (as documented by OSCAR's reverse engineering)
TGT_KEYS = {
    "SRN": "serial",
    "PNA": "model",
    "PCD": "product_code",
}


def parse_tgt(text: str) -> dict[str, str]:
    """``#KEY value`` lines -> dict."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("#"):
            continue
        parts = line[1:].split(None, 1)
        if not parts:
            continue
        key = parts[0]
        value = parts[1].strip() if len(parts) > 1 else ""
        out[key] = value
    return out


def _walk(obj: Any, prefix: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


_FW_RE = re.compile(r"(firmware|software).*(version|identifier|id)$", re.I)


def series_from_model(model: str | None) -> str | None:
    if not model:
        return None
    m = model.lower()
    if "airsense" in m and "11" in m:
        return "AirSense 11"
    if "airsense" in m and "10" in m:
        return "AirSense 10"
    if "aircurve" in m and "11" in m:
        return "AirCurve 11"
    if "aircurve" in m and "10" in m:
        return "AirCurve 10"
    if m.startswith("s9") or " s9" in m:
        return "S9"
    return None


def device_type_from_model(model: str | None) -> str | None:
    """Only obvious cases; otherwise determined from the therapy mode."""
    if not model:
        return None
    m = model.lower()
    if "asv" in m:
        return "ASV"
    if "aircurve" in m or "vpap" in m:
        return "BiLevel"
    if "elite" in m or "cpap" in m:
        return "CPAP"
    if "autoset" in m or "auto" in m:
        return "APAP"
    return None


def identify(tgt_path: Path | None, json_path: Path | None) -> DeviceInfo:
    info = DeviceInfo(manufacturer="ResMed", data_format="ResMed EDF (SD-Karte)")
    if json_path is not None:
        try:
            data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            info.identification = {"source": "Identification.json", "data": data}
            product = (
                data.get("FlowGenerator", {})
                .get("IdentificationProfiles", {})
                .get("Product", {})
                if isinstance(data.get("FlowGenerator"), dict)
                else {}
            )
            if isinstance(product, dict):
                info.serial = _s(product.get("SerialNumber"))
                info.product_code = _s(product.get("ProductCode"))
                info.model = _s(product.get("ProductName"))
            fw = []
            for path, val in _walk(data):
                last = path.split(".")[-1]
                if _FW_RE.search(last) and isinstance(val, (str, int, float)):
                    fw.append(f"{path}={val}")
            if fw:
                # Exact semantics unverified -> keep the raw key path visible.
                info.firmware = "; ".join(fw[:3])
    if info.serial is None and tgt_path is not None:
        try:
            kv = parse_tgt(tgt_path.read_text(encoding="latin-1"))
        except OSError:
            kv = {}
        info.identification = {"source": "Identification.tgt", "data": kv}
        info.serial = kv.get("SRN") or None
        info.product_code = kv.get("PCD") or None
        pna = kv.get("PNA")
        if pna:
            info.model = pna.replace("_", " ").strip()
    if info.model:
        info.series = series_from_model(info.model)
        info.device_type = device_type_from_model(info.model)
    return info


def _s(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


_SRN_RE = re.compile(r"SRN=(\S+)")


def serial_from_recording_field(recording: str) -> str | None:
    """ResMed writes ``SRN=<serial>`` into the EDF recording identification."""
    m = _SRN_RE.search(recording or "")
    return m.group(1) if m else None
