import json
import shutil
from datetime import date, datetime, time, timedelta

import numpy as np

from conftest import FIRST_DAY
from cpap_parser import FileSet, detect, get_parser, wall_ms
from cpap_parser.resmed.labels import BRP_LABELS, PLD_LABELS, match_event, match_label, unit_conversion
from cpap_parser.testing.synthetic_resmed import generate_nights, write_card


def test_detect_and_identify(synthetic_card):
    fs = FileSet.from_directory(synthetic_card)
    parser, det = detect(fs)
    assert parser.name == "resmed" and det.supported and det.confidence >= 0.9
    info = parser.identify(fs)
    assert info.manufacturer == "ResMed"
    assert info.serial == "23000000001"
    assert info.model == "AirSense 10 AutoSet"
    assert info.product_code == "37028"
    assert info.series == "AirSense 10"
    assert info.device_type == "APAP"
    assert info.identification["data"]["PNA"] == "AirSense_10_AutoSet"


def test_identify_as11_json(synthetic_card_oxi):
    fs = FileSet.from_directory(synthetic_card_oxi)
    info = get_parser("resmed").identify(fs)
    assert info.serial == "22000000002"
    assert info.model == "AirSense 11 AutoSet"
    assert info.series == "AirSense 11"


def test_find_roots_nested():
    p = get_parser("resmed")
    paths = ["backup/CARD/STR.edf", "backup/CARD/DATALOG/20260901/20260901_223000_BRP.edf", "other/readme.txt"]
    assert p.find_roots(paths) == ["backup/CARD/"]


def test_plan_and_parse_matches_ground_truth(tmp_path):
    root = tmp_path / "SD"
    truth = write_card(root, FIRST_DAY, nights=3, seed=5, hours=(1.0, 1.5), skip_probability=0)
    fs = FileSet.from_directory(root)
    p = get_parser("resmed")
    plans = p.plan(fs)
    assert [pl.date for pl in plans] == [FIRST_DAY + timedelta(days=i) for i in range(3)]
    for night in truth:
        parsed = p.parse_night(fs, night.day)
        assert len([s for s in parsed.sessions if s.source == "detail"]) == len(night.sessions)
        for ps, ts in zip(parsed.sessions, night.sessions, strict=True):
            assert ps.start_ms == wall_ms(ts.start)
            assert ps.duration_s == ts.seconds
        expected = sorted((e.code, wall_ms(s.start) + int(e.end_s * 1000), e.duration) for s in night.sessions for e in s.events)
        got = sorted((e.code, e.onset_ms, e.duration_s) for e in parsed.events if e.code != "CSR")
        assert got == expected
        # ResMed convention: onset marks the end of the event
        for e in parsed.events:
            if e.code != "CSR" and e.duration_s:
                assert e.end_ms == e.onset_ms and e.start_ms == e.onset_ms - int(e.duration_s * 1000)


def test_units_converted(synthetic_card):
    fs = FileSet.from_directory(synthetic_card)
    parsed = get_parser("resmed").parse_night(fs, FIRST_DAY)
    sig = {s.channel: s for s in parsed.sessions[0].signals}
    assert sig["flow"].unit == "L/min" and sig["flow"].sample_rate == 25
    assert sig["leak"].unit == "L/min" and sig["leak"].sample_rate == 0.5
    assert sig["tidal_volume"].unit == "mL"
    # synthetic flow amplitude ~0.42 L/s -> roughly 25 L/min
    assert 15 < np.nanmax(sig["flow"].physical()) < 60
    assert 300 < np.nanmedian(sig["tidal_volume"].physical()) < 600
    # SAD file without oximeter (-1 everywhere) must not produce channels
    assert "spo2" not in sig and "pulse" not in sig
    assert "x_crc16" not in sig


def test_oximetry_channels(synthetic_card_oxi):
    fs = FileSet.from_directory(synthetic_card_oxi)
    parsed = get_parser("resmed").parse_night(fs, FIRST_DAY)
    chans = {s.channel for s in parsed.sessions[0].signals}
    assert {"spo2", "pulse"} <= chans


def test_str_summary_metrics_and_settings(synthetic_card):
    fs = FileSet.from_directory(synthetic_card)
    parsed = get_parser("resmed").parse_night(fs, FIRST_DAY)
    m = parsed.device_metrics
    assert {"ahi", "oai", "cai", "hi", "usage_h", "leak.p95"} <= set(m)
    assert "spo2.median" not in m  # -1 means not available
    assert parsed.settings["S.EPR.Level"] == 2
    assert parsed.settings["mode_name"] == "AutoSet (APAP)"
    assert parsed.mask_intervals
    noon = wall_ms(datetime.combine(FIRST_DAY, time(12)))
    assert all(noon < a < b <= noon + 86400000 for a, b in parsed.mask_intervals)


def test_summary_only_night(tmp_path, synthetic_card):
    root = tmp_path / "SD"
    shutil.copytree(synthetic_card, root)
    shutil.rmtree(root / "DATALOG" / FIRST_DAY.strftime("%Y%m%d"))
    fs = FileSet.from_directory(root)
    p = get_parser("resmed")
    assert FIRST_DAY in [pl.date for pl in p.plan(fs)]
    parsed = p.parse_night(fs, FIRST_DAY)
    assert not parsed.has_detail
    assert parsed.sessions and all(s.source == "summary" for s in parsed.sessions)
    assert parsed.device_metrics["ahi"] >= 0


def test_s9_flat_datalog(tmp_path, synthetic_card):
    """S9 cards keep EDF files directly in DATALOG; the day is derived noon-to-noon."""
    root = tmp_path / "SD"
    shutil.copytree(synthetic_card, root)
    for d in (root / "DATALOG").iterdir():
        for f in d.iterdir():
            f.rename(root / "DATALOG" / f.name)
        d.rmdir()
    fs = FileSet.from_directory(root)
    days = {pl.date for pl in get_parser("resmed").plan(fs) if pl.files}
    assert days == {FIRST_DAY + timedelta(days=i) for i in range(4)}


def test_label_matching_rules():
    assert match_label("Press.2s", PLD_LABELS) == "pressure"
    assert match_label("MaskPress.2s", PLD_LABELS) == "mask_pressure"
    assert match_label("EprPress.2s", PLD_LABELS) == "epap"
    assert match_label("TidVol.2s", PLD_LABELS) == "tidal_volume"
    assert match_label("Ti", PLD_LABELS) == "ti"
    assert match_label("TidalSomething", PLD_LABELS) is None  # "Ti" must not swallow it
    assert match_label("Leak 2s", PLD_LABELS) == "leak"
    assert match_label("Flow.40ms", BRP_LABELS) == "flow"
    assert match_event("Obstructive Apnea") == "OA"
    assert match_event("Central apnea") == "CA"
    assert match_event("Apnea") == "UA"
    assert match_event("Arousal") == "RERA"
    assert match_event("Something new") == "OTHER"
    assert unit_conversion("flow", "L/s")[0] == 60
    assert unit_conversion("flow", "L/min")[0] == 1
    assert unit_conversion("tidal_volume", "mL")[0] == 1


def test_unknown_annotation_kept(tmp_path, synthetic_card):
    from cpap_parser.edf_writer import EDFSpec, WAnnotation, write_edf

    root = tmp_path / "SD"
    shutil.copytree(synthetic_card, root)
    day = root / "DATALOG" / FIRST_DAY.strftime("%Y%m%d")
    eve = next(day.glob("*_EVE.edf"))
    start = datetime.strptime(eve.name[:15], "%Y%m%d_%H%M%S")
    write_edf(eve, EDFSpec(start=start, record_duration=0, n_records=1, signals=[], edfplus="EDF+D",
                           annotations=[WAnnotation(60, 12, "Mystery Event")]))
    parsed = get_parser("resmed").parse_night(FileSet.from_directory(root), FIRST_DAY)
    other = [e for e in parsed.events if e.code == "OTHER"]
    assert other and other[0].label == "Mystery Event"
    assert any("Mystery Event" in w for w in parsed.warnings)


def test_philips_detected_not_supported(tmp_path):
    (tmp_path / "P-Series" / "P123").mkdir(parents=True)
    (tmp_path / "P-Series" / "P123" / "prop.txt").write_text("x")
    parser, det = detect(FileSet.from_directory(tmp_path))
    assert parser.name == "philips" and not det.supported


def test_generator_is_deterministic():
    a = generate_nights(date(2026, 1, 1), 3, seed=1, hours=(1, 1.2))
    b = generate_nights(date(2026, 1, 1), 3, seed=1, hours=(1, 1.2))
    assert json.dumps([[e.__dict__ for s in n.sessions for e in s.events] for n in a]) == json.dumps(
        [[e.__dict__ for s in n.sessions for e in s.events] for n in b]
    )
