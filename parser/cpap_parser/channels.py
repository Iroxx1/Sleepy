"""Canonical channel and event registry shared by parsers, backend and UI."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ChannelDef:
    code: str
    name: str  # German display name
    unit: str
    group: str  # chart group in the UI
    description: str = ""
    #: channel values are statistically summarised (median/p95/max...)
    summarise: bool = True


CHANNELS: dict[str, ChannelDef] = {
    c.code: c
    for c in [
        ChannelDef("flow", "Flow (Atemfluss)", "L/min", "flow", "Hochaufgelöster Atemfluss", summarise=False),
        ChannelDef("mask_pressure_hi", "Maskendruck (hochaufgelöst)", "cmH2O", "pressure", summarise=False),
        ChannelDef("trig_cycle_event", "Trigger/Cycle-Ereignis", "", "other", summarise=False),
        ChannelDef("pressure", "Druck", "cmH2O", "pressure", "Therapiedruck (bei Bilevel: IPAP)"),
        ChannelDef("ipap", "IPAP", "cmH2O", "pressure"),
        ChannelDef("epap", "EPAP / EPR-Druck", "cmH2O", "pressure", "Exspiratorischer Druck"),
        ChannelDef("mask_pressure", "Maskendruck", "cmH2O", "pressure"),
        ChannelDef("leak", "Leckage", "L/min", "leak"),
        ChannelDef("resp_rate", "Atemfrequenz", "/min", "breathing"),
        ChannelDef("tidal_volume", "Atemzugvolumen", "mL", "breathing"),
        ChannelDef("minute_vent", "Atemminutenvolumen", "L/min", "breathing"),
        ChannelDef("target_vent", "Ziel-Ventilation", "L/min", "breathing"),
        ChannelDef("ie_ratio", "I:E-Verhältnis (Rohwert)", "", "breathing"),
        ChannelDef("ti", "Inspirationszeit", "s", "breathing"),
        ChannelDef("te", "Exspirationszeit", "s", "breathing"),
        ChannelDef("flow_limit", "Flusslimitierung", "", "flow_limit"),
        ChannelDef("snore", "Schnarchen", "", "snore"),
        ChannelDef("spo2", "SpO2", "%", "oximetry"),
        ChannelDef("pulse", "Puls", "/min", "oximetry"),
    ]
}


@dataclass(frozen=True)
class EventDef:
    code: str
    name: str
    short: str
    color: str
    #: counts towards AHI
    apnea_hypopnea: bool = False
    #: counts towards RDI
    respiratory: bool = False
    #: span event (duration meaningful, e.g. CSR periods)
    span: bool = False


EVENTS: dict[str, EventDef] = {
    e.code: e
    for e in [
        EventDef("OA", "Obstruktive Apnoe", "OA", "#2563eb", True, True),
        EventDef("CA", "Zentrale Apnoe (Clear Airway)", "CA", "#7c3aed", True, True),
        EventDef("UA", "Nicht klassifizierte Apnoe", "UA", "#64748b", True, True),
        EventDef("H", "Hypopnoe", "H", "#f59e0b", True, True),
        EventDef("RERA", "RERA (Arousal)", "RE", "#db2777", False, True),
        EventDef("FL", "Flusslimitierung (Ereignis)", "FL", "#0891b2"),
        EventDef("VS", "Vibratory Snore", "VS", "#65a30d"),
        EventDef("PB", "Periodische Atmung", "PB", "#0d9488", span=True),
        EventDef("CSR", "Cheyne-Stokes-Atmung", "CSR", "#16a34a", span=True),
        EventDef("LL", "Große Leckage", "LL", "#dc2626", span=True),
        EventDef("DESAT", "SpO2-Entsättigung (Gerät)", "DS", "#e11d48"),
        EventDef("OTHER", "Sonstiges Ereignis", "?", "#475569"),
    ]
}

AHI_EVENTS = [c for c, e in EVENTS.items() if e.apnea_hypopnea]
APNEA_EVENTS = ["OA", "CA", "UA"]
RDI_EVENTS = [c for c, e in EVENTS.items() if e.respiratory]


def slugify(label: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", label.strip().lower()).strip("_")
    return s or "unnamed"


def channel_def(code: str) -> ChannelDef:
    if code in CHANNELS:
        return CHANNELS[code]
    return ChannelDef(code, code[2:] if code.startswith("x_") else code, "", "other")
