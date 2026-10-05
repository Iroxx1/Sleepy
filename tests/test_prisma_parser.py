"""Löwenstein prisma parser – tested with *synthetic* card data only."""

from __future__ import annotations

import numpy as np
import pytest

from conftest import FIRST_DAY, upload_zip, zip_dir
from cpap_parser import FileSet, detect, get_parser, setting_names, wall_ms
from cpap_parser.base import FormatNotSupported, ParserError
from cpap_parser.loewenstein.events import read_event_file
from cpap_parser.loewenstein.parser import HPA_TO_CMH2O
from cpap_parser.loewenstein.wmedf import read_wmedf
from cpap_parser.testing.synthetic_prisma import write_card


@pytest.fixture(scope="module")
def prisma(tmp_path_factory):
    root = tmp_path_factory.mktemp("prisma") / "cpap"
    truth = write_card(root, FIRST_DAY, nights=3, seed=3)
    return root, truth


def test_detect_and_identify(prisma):
    root, _ = prisma
    fs = FileSet.from_directory(root)
    parser, det = detect(fs)
    assert parser.name == "loewenstein" and det.supported
    info = parser.identify(fs)
    assert info.manufacturer == "Löwenstein Medical"
    assert info.serial == "12345678"  # config stores it hexadecimal
    assert info.model == "prisma SMART"
    assert info.firmware == "9.9.0001"
    assert info.device_type == "APAP"


def test_find_roots_nested():
    p = get_parser("loewenstein")
    assert p.find_roots(["cpap/config.pscfg", "cpap/0012345678/20260901/signal_1.wmedf"]) == ["cpap/"]
    assert p.find_roots(["a/b/0012345678/20260901/event_7.xml"]) == ["a/b/"]
    assert p.find_roots(["DATALOG/20260901/20260901_230000_BRP.edf"]) == []


def test_wmedf_mixed_sample_widths(prisma):
    root, truth = prisma
    s = truth[0]
    edf = read_wmedf(root / "0012345678" / f"{s.day:%Y%m%d}" / f"signal_{s.sid}.wmedf")
    assert edf.start == s.start
    assert edf.n_records == s.seconds
    sig = {x.label: x for x in edf.signals}
    assert len(sig["RespFlow"].digital) == s.seconds * 5
    assert len(sig["Pressure"].digital) == s.seconds * 2
    # 8 bit unsigned values above 127 must not turn negative
    assert sig["CPAPPressure"].digital.max() == 120 and sig["CPAPPressure"].digital.min() >= 40


def test_plan_and_parse(prisma):
    root, truth = prisma
    fs = FileSet.from_directory(root)
    p = get_parser("loewenstein")
    assert [pl.date for pl in p.plan(fs)] == [s.day for s in truth]
    for s in truth:
        night = p.parse_night(fs, s.day)
        assert len(night.sessions) == 1
        ses = night.sessions[0]
        assert ses.start_ms == wall_ms(s.start) and ses.duration_s == s.seconds
        chans = {x.channel: x for x in ses.signals}
        assert {"flow", "leak", "pressure", "mask_pressure", "obstruct_level"} <= set(chans)
        # IPAP/EPAP identical to the therapy pressure are dropped (CPAP/APAP)
        assert "ipap" not in chans and "epap" not in chans
        pr = chans["pressure"]
        assert pr.unit == "cmH2O" and pr.gain == pytest.approx(0.1 * HPA_TO_CMH2O)
        assert pr.physical()[-1] == pytest.approx(12.0 * HPA_TO_CMH2O)
        # events: end = start + EndTime/10 s, start = end - Duration/10 s
        start = wall_ms(s.start)
        expected = {101: "OA", 111: "H", 121: "RERA", 131: "VS", 2: "EPOCH_MO"}
        want = sorted((expected[e.event_id], start + e.end_ds * 100 - e.duration_ds * 100, start + e.end_ds * 100)
                      for e in s.events if e.event_id in expected)
        got = sorted((e.code, e.start_ms, e.end_ms) for e in night.events)
        assert got == want
        # undocumented codes are counted, not interpreted
        assert night.summary_raw["unknown_event_codes"] == {"1101": 1}
        assert night.summary_raw["unknown_parameters"] == {"14": 0}
        assert night.settings["mode_name"] == "APAP (Standard)"
        assert night.settings["Prisma.Pressure"] == 4.0 and night.settings["Prisma.PressureMax"] == 14.0
        assert night.settings["Prisma.SoftPAP"] == "Leicht"


def test_flow_reduced_inside_event_window(prisma):
    root, truth = prisma
    fs = FileSet.from_directory(root)
    night = get_parser("loewenstein").parse_night(fs, truth[0].day)
    flow = next(x for x in night.sessions[0].signals if x.channel == "flow")
    oa = next(e for e in night.events if e.code == "OA")
    a = (oa.start_ms - flow.start_ms) * 5 // 1000
    b = (oa.end_ms - flow.start_ms) * 5 // 1000
    v = flow.physical()
    assert np.ptp(v[a:b]) < 0.2 * np.ptp(v[max(0, a - 300):a])


def test_setting_names_cover_prisma_keys():
    names = setting_names()
    assert names["Prisma.PressureMax"].startswith("Maximaldruck")
    assert "S.EPR.Level" in names  # ResMed names are still there


def test_prisma_line_recognised_but_unsupported(tmp_path):
    (tmp_path / "config.pcfg").write_text("{}")
    (tmp_path / "therapy.pdat").write_bytes(b"PK")
    fs = FileSet.from_directory(tmp_path)
    parser, det = detect(fs)
    assert parser.name == "loewenstein" and not det.supported
    with pytest.raises(FormatNotSupported):
        parser.plan(fs)


def test_event_xml_with_doctype_is_rejected(tmp_path):
    f = tmp_path / "event_1.xml"
    f.write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><desc>&a;</desc>')
    with pytest.raises(ParserError):
        read_event_file(f)


def test_import_via_api(api, tmp_path):
    root = tmp_path / "card"
    truth = write_card(root, FIRST_DAY, nights=2, seed=9)
    res = upload_zip(api, zip_dir(root, "cpap/"), name="cpap.zip")
    assert res["status"] == "completed", res
    assert res["stats"]["nights_created"] == 2
    devs = api.get("/api/devices").json()
    dev = devs["items"][0] if isinstance(devs, dict) else devs[0]
    assert dev["manufacturer"] == "Löwenstein Medical" and dev["serial"] == "12345678"
    nights = api.get("/api/nights").json()["items"]
    detail = api.get(f"/api/nights/{nights[0]['id']}").json()
    labels = {s["key"]: s["label"] for s in detail["settings"]}
    assert labels["Prisma.PressureMax"] == "Maximaldruck (hPa)"
    assert detail["event_counts"]["OA"] == 1
    assert detail["event_counts"]["H"] == 2
    assert len(truth) == 2
