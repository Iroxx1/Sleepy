from datetime import date

import numpy as np
import pytest

from sleepy.analysis import insights as ins
from sleepy.analysis.metrics import describe, detect_desaturations, union_seconds
from sleepy.analysis.stats import describe_values, linear_trend, robust_z
from sleepy.api.query import QueryError, parse_query


def test_union_seconds():
    assert union_seconds([(0, 1000), (500, 2000), (3000, 4000)]) == 3.0
    assert union_seconds([]) == 0


def test_describe_ignores_nan():
    d = describe(np.array([1.0, 2.0, np.nan, 3.0]))
    assert d["median"] == 2.0 and d["max"] == 3.0
    assert describe(np.array([np.nan])) == {}


def test_describe_values_and_trend():
    s = describe_values([1, 2, 3, None, 4])
    assert s["n"] == 4 and s["mean"] == 2.5
    t = linear_trend(range(20), [x * 0.5 for x in range(20)])
    assert t["direction"] == "steigend" and abs(t["slope_per_30d"] - 15) < 1e-6
    flat = linear_trend(range(20), [5 + (x % 2) * 0.1 for x in range(20)])
    assert flat["direction"] == "stabil"
    assert linear_trend([1, 2], [1, 2]) is None


def test_robust_z():
    z, med, _ = robust_z(10, [2, 2.1, 1.9, 2.2, 2.0, 1.8, 2.05])
    assert z > 3 and med == pytest.approx(2.0, abs=0.06)
    assert robust_z(1, [1, 2]) is None


def test_anomalies_only_meaningful():
    hist = {"ahi": [2, 2.1, 1.9, 2.2, 2.0, 1.8, 2.05, 2.1], "usage_h": [7, 7.2, 6.9, 7.1, 7.0, 7.3, 6.8, 7.0]}
    a = ins.anomalies({"ahi": 8.0, "usage_h": 3.0}, hist, {"ahi": "/h", "usage_h": "h"})
    keys = {x["key"] for x in a}
    assert keys == {"ahi", "usage_h"}
    assert all("statistisch auffällig" in x["text"] for x in a)
    assert ins.anomalies({"ahi": 2.3}, hist, {}) == []
    assert ins.anomalies({"usage_h": 9.0}, hist, {}) == []  # longer usage is not flagged


def test_clusters():
    evs = [ins.Ev("OA", t * 1000, t * 1000 + 10000, 10) for t in (0, 60, 120, 180, 5000, 9000)]
    c = ins.find_clusters(evs)
    assert len(c) == 1 and c[0]["count"] == 4


def test_desaturation_detector():
    spo2 = np.full(600, 96.0)
    spo2[300:320] = 91.0
    spo2[450:470] = 94.0  # only 2 % drop -> no event
    assert len(detect_desaturations(spo2, 1.0)) == 1


def test_status():
    assert ins.night_status({"ahi": 12, "usage_h": 7}, True) == "red"
    assert ins.night_status({"ahi": 6, "usage_h": 7}, True) == "yellow"
    assert ins.night_status({"ahi": 1, "usage_h": 2}, True) == "yellow"
    assert ins.night_status({"ahi": 1, "usage_h": 7, "leak.p95": 30}, True) == "yellow"
    assert ins.night_status({"ahi": 1, "usage_h": 7}, True) == "green"
    assert ins.night_status({}, False) == "none"


def test_summary_text_never_invents():
    t = ins.summary_text({"usage_h": 7.5}, {}, 0, 1, [], 24, None, None)
    assert t == "Therapiedauer 7:30 h."
    t2 = ins.summary_text({"usage_h": 7.5, "ahi": 2.0}, {}, 0, 1, [], 24, None, None)
    assert "keine Apnoen" not in t2  # AHI 2 but no event list -> must not claim "no events"


def test_query_parser():
    q = parse_query("ahi>5 leak<=20 usage<4h event:CA>=2 2026-09")
    assert q.ranges["ahi"][0] > 5 and q.ranges["leak.p95"][1] == 20 and q.ranges["usage_h"][1] < 4
    assert q.event_codes == ["CA"] and q.event_min == 2
    assert q.date_from == date(2026, 9, 1) and q.date_to == date(2026, 9, 30)
    q2 = parse_query("01.09.2026..2026-09-15 usage>=90min")
    assert q2.date_from == date(2026, 9, 1) and q2.ranges["usage_h"][0] == 1.5
    with pytest.raises(QueryError):
        parse_query("event:XYZ")
    with pytest.raises(QueryError):
        parse_query("hallo")


def _row(d, usage, ahi, leak=3.0, status="green"):
    return {"date": d, "usage_h": usage, "status": status, "metrics": {"ahi": ahi, "leak.p95": leak}}


def test_short_summary():
    th = {"leak_p95_max": 24, "usage_min_h": 4}
    rows = [_row(f"2026-09-{d:02d}", 7.5, 2.0) for d in range(24, 31)]
    rows += [_row(f"2026-09-{d:02d}", 7.0, 4.0) for d in range(17, 24)]
    t = ins.short_summary(rows, date(2026, 9, 30), th)
    assert t.startswith("Letzte 7 Tage: 7 Nächte, Ø 7:30 h, AHI Ø 2,0 (Vorwoche 4,0).")
    assert "Alle Nächte im grünen Bereich." in t and "Leckage unauffällig." in t
    assert len(t) <= 200
    rows2 = [_row("2026-09-30", 3.0, 12.0, leak=30, status="red"), _row("2026-09-29", 6.0, 6.0, status="yellow")]
    t2 = ins.short_summary(rows2, date(2026, 9, 30), th)
    assert "Ampel: 1 rot, 1 gelb." in t2 and "Leckage in 1 Nacht erhöht." in t2
    assert "1× unter 4 h genutzt." in t2 and "5 Tage ohne Daten." in t2 and len(t2) <= 200
    assert "keine Therapiedaten" in ins.short_summary([], date(2026, 9, 30), th)
    assert "Diagnose" not in t + t2
