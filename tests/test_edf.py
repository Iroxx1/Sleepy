import gzip
from datetime import datetime

import numpy as np
import pytest

from cpap_parser.edf import EDFError, parse_edf_datetime, parse_tal, read_edf, read_edf_header
from cpap_parser.edf_writer import EDFSpec, WAnnotation, WSignal, write_edf


def _spec(**kw):
    vals = np.sin(np.linspace(0, 20, 250)) * 1.5
    return EDFSpec(
        start=datetime(2026, 9, 1, 22, 30, 5),
        record_duration=10,
        n_records=1,
        signals=[WSignal("Flow.40ms", "L/s", -2, 2, -32768, 32767, 250, values=vals)],
        **kw,
    )


def test_roundtrip_values_and_header(tmp_path):
    p = tmp_path / "a.edf"
    write_edf(p, _spec())
    edf = read_edf(p)
    assert edf.start == datetime(2026, 9, 1, 22, 30, 5)
    assert edf.n_records == 1 and edf.record_duration == 10
    s = edf.signal("Flow.40ms")
    assert s.dimension == "L/s"
    assert edf.sample_rate(s) == 25
    expected = np.sin(np.linspace(0, 20, 250)) * 1.5
    assert np.allclose(s.physical(), expected, atol=4 / 65535 + 1e-9)


def test_header_only(tmp_path):
    p = tmp_path / "a.edf"
    write_edf(p, _spec())
    h = read_edf_header(p)
    assert h.signals[0].samples_per_record == 250
    assert h.signals[0].digital is None


def test_gzip_transparent(tmp_path):
    p = tmp_path / "a.edf"
    write_edf(p, _spec())
    gz = tmp_path / "a.edf.gz"
    gz.write_bytes(gzip.compress(p.read_bytes()))
    assert np.array_equal(read_edf(gz).signals[0].digital, read_edf(p).signals[0].digital)


def test_truncated_file_warns(tmp_path):
    spec = _spec()
    spec.n_records = 3
    spec.signals[0].values = np.zeros(750)
    p = tmp_path / "t.edf"
    write_edf(p, spec)
    data = p.read_bytes()
    p.write_bytes(data[: len(data) - 300])
    edf = read_edf(p)
    assert edf.truncated and edf.n_records == 2
    assert any("truncated" in w for w in edf.warnings)


def test_annotations_edfplus(tmp_path):
    spec = EDFSpec(
        start=datetime(2026, 9, 1, 23, 0, 0), record_duration=0, n_records=1, signals=[], edfplus="EDF+D",
        annotations=[WAnnotation(0, None, "Recording starts"), WAnnotation(120.5, 14.0, "Obstructive Apnea"),
                     WAnnotation(300, None, "Hypopnea")],
    )
    p = tmp_path / "e.edf"
    write_edf(p, spec)
    edf = read_edf(p)
    assert edf.is_edfplus and edf.is_discontinuous
    texts = [(a.onset, a.duration, a.text) for a in edf.annotations]
    assert (120.5, 14.0, "Obstructive Apnea") in texts
    assert (300.0, None, "Hypopnea") in texts


def test_parse_tal_multiple_texts_and_negative():
    buf = b"+0\x14\x14\x00-1.5\x150.5\x14A\x14B\x14\x00" + b"\x00" * 10
    anns = parse_tal(buf)
    assert [(a.onset, a.duration, a.text) for a in anns] == [(-1.5, 0.5, "A"), (-1.5, 0.5, "B")]


@pytest.mark.parametrize("yy,year", [("85", 1985), ("99", 1999), ("00", 2000), ("26", 2026), ("84", 2084)])
def test_year_clipping(yy, year):
    assert parse_edf_datetime(f"01.02.{yy}", "03.04.05").year == year


def test_invalid_file(tmp_path):
    p = tmp_path / "x.edf"
    p.write_bytes(b"not an edf" * 10)
    with pytest.raises(EDFError):
        read_edf(p)
