"""ResMed specific label tables.

Sources (used as *technical reference only*, no code copied):
  * OSCAR ``resmed_loader.cpp`` (GPL-3.0) – signal label variants of S9,
    AirSense/AirCurve 10 and AirSense 11 devices, unit conventions.
  * Inspection of the EDF headers which carry label, physical dimension and
    scaling for every signal.

Everything here is about *names*; the numeric scaling is always taken from the
EDF header of the actual file.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Waveform / low-rate signals (BRP, PLD, SAD files)
# ---------------------------------------------------------------------------
# (label, canonical code).  Matching: exact (case-insensitive) first, then
# "label starts with" as ResMed truncates labels inconsistently.
# File type specific tables are needed because S9 uses "Mask Pres" in both BRP
# (high-rate) and PLD (low-rate) files.

BRP_LABELS: list[tuple[str, str]] = [
    ("Flow.40ms", "flow"),
    ("Press.40ms", "mask_pressure_hi"),
    ("TrigCycEvt.40ms", "trig_cycle_event"),
    ("Flow", "flow"),  # S9
    ("Mask Pres", "mask_pressure_hi"),  # S9
    ("Resp Event", "trig_cycle_event"),  # S9 VPAP
]

PLD_LABELS: list[tuple[str, str]] = [
    ("MaskPress.2s", "mask_pressure"),
    ("Press.2s", "pressure"),
    ("EprPress.2s", "epap"),
    ("EPRPress.2s", "epap"),
    ("IPAP", "ipap"),
    ("EPAP", "epap"),
    ("Leak.2s", "leak"),
    ("RespRate.2s", "resp_rate"),
    ("TidVol.2s", "tidal_volume"),
    ("MinVent.2s", "minute_vent"),
    ("Snore.2s", "snore"),
    ("FlowLim.2s", "flow_limit"),
    ("IERatio.2s", "ie_ratio"),
    ("B5ITime.2s", "ti"),
    ("B5ETime.2s", "te"),
    ("TgtVent.2s", "target_vent"),
    # S9 / localised labels
    ("Mask Pres", "mask_pressure"),
    ("Therapy Pres", "pressure"),
    ("Insp Pres", "ipap"),
    ("Exp Pres", "epap"),
    ("Leak", "leak"),
    ("Leck", "leak"),
    ("Fuite", "leak"),
    ("Fuga", "leak"),
    ("RR", "resp_rate"),
    ("AF", "resp_rate"),
    ("FR", "resp_rate"),
    ("Vt", "tidal_volume"),
    ("VC", "tidal_volume"),
    ("MV", "minute_vent"),
    ("VM", "minute_vent"),
    ("Snore", "snore"),
    ("FFL Index", "flow_limit"),
    ("I:E", "ie_ratio"),
    ("Ti", "ti"),
    ("Te", "te"),
    ("TgMV", "target_vent"),
]

SAD_LABELS: list[tuple[str, str]] = [
    ("SpO2.1s", "spo2"),
    ("Pulse.1s", "pulse"),
    ("SpO2", "spo2"),
    ("Pulse", "pulse"),
    ("Puls", "pulse"),
    ("Pouls", "pulse"),
]

#: Labels that are checksums or otherwise not data
IGNORED_SIGNAL_LABELS = {"crc16"}

#: Some channels use -1 (digital) as "no data" (OSCAR checks this for SAD).
INVALID_MINUS_ONE = {"spo2", "pulse"}


def match_label(label: str, table: list[tuple[str, str]]) -> str | None:
    low = label.strip().lower()
    for lab, code in table:
        if low == lab.lower():
            return code
    # Prefix match (ResMed truncates/extends labels, e.g. "Leak" vs "Leak 2s").
    # The character following the prefix must not be a letter, so that "Ti"
    # does not swallow "TidVol".  Longest prefix wins.
    best: tuple[int, str] | None = None
    for lab, code in table:
        ll = lab.lower()
        if low.startswith(ll) and len(low) > len(ll) and not low[len(ll)].isalpha():
            if best is None or len(ll) > best[0]:
                best = (len(ll), code)
    return best[1] if best else None


# ---------------------------------------------------------------------------
# Unit conversion by (canonical code, EDF physical dimension)
# ---------------------------------------------------------------------------
# ResMed stores flow and leak in L/s and tidal volume in L.  Convention in
# PAP software (OSCAR, SleepHQ, ResMed myAir) is L/min and mL.

def unit_conversion(code: str, dimension: str) -> tuple[float, str, str | None]:
    """Return (factor, target unit, note)."""
    dim = dimension.strip().lower().replace(" ", "")
    if code in ("flow", "leak"):
        if dim in ("l/s", "ls", "l/sec", ""):
            note = "L/s × 60 → L/min" + (" (Einheit fehlte im Header, ResMed-Konvention angenommen)" if not dim else "")
            return 60.0, "L/min", note
        if dim in ("l/min", "l/m", "lpm"):
            return 1.0, "L/min", None
    if code == "tidal_volume":
        if dim in ("l", ""):
            note = "L × 1000 → mL" + (" (Einheit fehlte im Header, ResMed-Konvention angenommen)" if not dim else "")
            return 1000.0, "mL", note
        if dim == "ml":
            return 1.0, "mL", None
    if code in ("pressure", "ipap", "epap", "mask_pressure", "mask_pressure_hi"):
        return 1.0, "cmH2O", None
    if code in ("resp_rate", "pulse"):
        return 1.0, "/min", None
    if code == "minute_vent":
        return 1.0, "L/min", None
    if code == "spo2":
        return 1.0, "%", None
    return 1.0, dimension.strip(), None


# ---------------------------------------------------------------------------
# Event annotations (EVE / CSL / AEV files)
# ---------------------------------------------------------------------------
EVENT_LABELS: list[tuple[str, str]] = [
    ("Obstructive Apnea", "OA"),
    ("Central Apnea", "CA"),
    ("Hypopnea", "H"),
    ("Apnea", "UA"),
    ("Arousal", "RERA"),
    ("SpO2 Desaturation", "DESAT"),
]

#: annotation texts that carry no event information
NON_EVENT_ANNOTATIONS = {"recording starts", "recording ends"}

CSR_START = "csr start"
CSR_END = "csr end"


def match_event(text: str) -> str:
    low = text.strip().lower()
    for lab, code in EVENT_LABELS:
        if low == lab.lower():
            return code
    for lab, code in EVENT_LABELS:
        if low.startswith(lab.lower()):
            return code
    return "OTHER"


# ---------------------------------------------------------------------------
# STR.edf (daily summary) -> canonical metric keys
# ---------------------------------------------------------------------------
# label -> (metric key, kind) ; kind selects unit conversion
STR_METRICS: dict[str, tuple[str, str]] = {
    "AHI": ("ahi", "index"),
    "AI": ("ai", "index"),
    "HI": ("hi", "index"),
    "OAI": ("oai", "index"),
    "CAI": ("cai", "index"),
    "UAI": ("uai", "index"),
    "RIN": ("rera_index", "index"),
    "CSR": ("csr_device", "raw"),
    "Leak.50": ("leak.median", "leak"),
    "Leak.70": ("leak.p70", "leak"),
    "Leak.95": ("leak.p95", "leak"),
    "Leak.Max": ("leak.max", "leak"),
    "Leak Med": ("leak.median", "leak"),
    "Leak 95": ("leak.p95", "leak"),
    "Leak Max": ("leak.max", "leak"),
    "MaskPress.50": ("mask_pressure.median", "raw"),
    "MaskPress.95": ("mask_pressure.p95", "raw"),
    "MaskPress.Max": ("mask_pressure.max", "raw"),
    "Mask Pres Med": ("mask_pressure.median", "raw"),
    "Mask Pres 95": ("mask_pressure.p95", "raw"),
    "Mask Pres Max": ("mask_pressure.max", "raw"),
    "TgtIPAP.50": ("target_ipap.median", "raw"),
    "TgtIPAP.95": ("target_ipap.p95", "raw"),
    "TgtIPAP.Max": ("target_ipap.max", "raw"),
    "TgtEPAP.50": ("target_epap.median", "raw"),
    "TgtEPAP.95": ("target_epap.p95", "raw"),
    "TgtEPAP.Max": ("target_epap.max", "raw"),
    "RespRate.50": ("resp_rate.median", "raw"),
    "RespRate.95": ("resp_rate.p95", "raw"),
    "RespRate.Max": ("resp_rate.max", "raw"),
    "TidVol.50": ("tidal_volume.median", "volume"),
    "TidVol.95": ("tidal_volume.p95", "volume"),
    "TidVol.Max": ("tidal_volume.max", "volume"),
    "MinVent.50": ("minute_vent.median", "raw"),
    "MinVent.95": ("minute_vent.p95", "raw"),
    "MinVent.Max": ("minute_vent.max", "raw"),
    "SpO2.50": ("spo2.median", "raw"),
    "SpO2.95": ("spo2.p95", "raw"),
    "SpO2.Max": ("spo2.max", "raw"),
}

STR_DURATION_LABELS = ("Duration", "Mask Dur")
STR_MASKON_LABELS = ("MaskOn", "Mask On")
STR_MASKOFF_LABELS = ("MaskOff", "Mask Off")
STR_MASKEVENTS_LABELS = ("MaskEvents", "Mask Events")
STR_MODE_LABELS = ("Mode", "Modus", "Funktion", "Mod")

# Friendly German names for well known settings.  Unknown settings are shown
# with their raw label.
SETTING_NAMES: dict[str, str] = {
    "Mode": "Therapiemodus (Rohwert)",
    "S.RampEnable": "Rampe aktiviert",
    "S.RampTime": "Rampenzeit (min)",
    "S.C.StartPress": "Startdruck CPAP (cmH2O)",
    "S.C.Press": "Druck CPAP (cmH2O)",
    "S.AS.StartPress": "Startdruck AutoSet (cmH2O)",
    "S.AS.MinPress": "Minimaldruck AutoSet (cmH2O)",
    "S.AS.MaxPress": "Maximaldruck AutoSet (cmH2O)",
    "S.AS.Comfort": "AutoSet Comfort",
    "S.A.StartPress": "Startdruck Auto (cmH2O)",
    "S.A.MinPress": "Minimaldruck Auto (cmH2O)",
    "S.A.MaxPress": "Maximaldruck Auto (cmH2O)",
    "S.AFH.StartPress": "Startdruck AutoSet for Her (cmH2O)",
    "S.AFH.MinPress": "Minimaldruck AutoSet for Her (cmH2O)",
    "S.AFH.MaxPress": "Maximaldruck AutoSet for Her (cmH2O)",
    "S.EPR.ClinEnable": "EPR klinisch freigegeben",
    "S.EPR.EPREnable": "EPR aktiviert",
    "S.EPR.Level": "EPR-Stufe",
    "S.EPR.EPRType": "EPR-Typ",
    "S.SmartStart": "SmartStart",
    "S.SmartStop": "SmartStop",
    "S.PtAccess": "Patientenzugriff",
    "S.PtView": "Patientenansicht",
    "S.ABFilter": "Antibakterieller Filter",
    "S.Mask": "Maskentyp",
    "S.Tube": "Schlauchtyp",
    "S.ClimateControl": "Climate Control",
    "S.HumEnable": "Befeuchter aktiviert",
    "S.HumLevel": "Befeuchterstufe",
    "S.TempEnable": "Schlauchheizung aktiviert",
    "S.Temp": "Schlauchtemperatur",
    "S.BL.StartPress": "Startdruck Bilevel (cmH2O)",
    "S.BL.IPAP": "IPAP (cmH2O)",
    "S.BL.EPAP": "EPAP (cmH2O)",
    "S.VA.StartPress": "Startdruck VAuto/ASV (cmH2O)",
    "S.VA.MinEPAP": "Min. EPAP (cmH2O)",
    "S.VA.MaxIPAP": "Max. IPAP (cmH2O)",
    "S.VA.PS": "Druckunterstützung (cmH2O)",
    "S.Trigger": "Trigger",
    "S.Cycle": "Cycle",
    "S.TiMax": "Ti max (s)",
    "S.TiMin": "Ti min (s)",
    "S.RiseEnable": "Rise aktiviert",
    "S.RiseTime": "Rise-Zeit",
    "S.EasyBreathe": "EasyBreathe",
}

# Mode values.  AirSense/AirCurve 10 & S9 numbering per OSCAR's reverse
# engineering.  AirSense 11 uses a different numbering which OSCAR translates.
MODES_10: dict[int, tuple[str, str]] = {
    0: ("CPAP", "CPAP"),
    1: ("APAP", "AutoSet (APAP)"),
    2: ("BILEVEL", "Bilevel (S)"),
    3: ("BILEVEL", "Bilevel (fix)"),
    4: ("BILEVEL", "Bilevel (ST)"),
    5: ("BILEVEL", "Bilevel (T)"),
    6: ("BILEVEL_AUTO", "VAuto"),
    7: ("ASV", "ASV"),
    8: ("ASV_AUTO", "ASVAuto"),
    9: ("AVAPS", "iVAPS"),
    10: ("UNKNOWN", "PAC"),
    11: ("APAP", "AutoSet for Her"),
}
MODES_11: dict[int, tuple[str, str]] = {
    1: ("APAP", "AutoSet (APAP)"),
    2: ("APAP", "AutoSet for Her"),
    3: ("CPAP", "CPAP"),
    7: ("ASV", "ASV"),
    8: ("ASV_AUTO", "ASVAuto"),
}
