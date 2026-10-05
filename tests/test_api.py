import io
import json
import zipfile

from conftest import FIRST_DAY


def _night(api, i=0):
    return sorted(api.get("/api/nights").json()["items"], key=lambda r: r["date"])[i]


def test_nights_list_and_detail(api, imported):
    rows = api.get("/api/nights").json()
    assert rows["total"] == 4
    r = _night(api)
    assert r["date"] == FIRST_DAY.isoformat() and r["status"] in ("green", "yellow", "red")
    d = api.get(f"/api/nights/{r['id']}").json()
    keys = {m["key"] for m in d["metrics"]}
    assert {"ahi", "usage_h", "leak.p95", "pressure.p95", "flow_limit.p95"} <= keys
    ahi = next(m for m in d["metrics"] if m["key"] == "ahi")
    assert ahi["source"] == "device" and ahi["device"] is not None and ahi["computed"] is not None
    assert abs(ahi["device"] - ahi["computed"]) < 0.6  # STR value is quantised, but must agree
    assert "spo2.median" not in keys  # no oximeter -> no fake zero values
    assert d["channels"] and {c["code"] for c in d["channels"]} >= {"flow", "pressure", "leak"}
    assert d["settings"] and d["source_files"] and d["source_files"][0]["sha256"]
    assert d["next_id"] and d["prev_id"] is None
    assert "ärztliche Beratung" in d["disclaimer"]


def test_events_with_context(api, imported):
    r = _night(api)
    ev = api.get(f"/api/nights/{r['id']}/events").json()
    assert ev["items"]
    e = ev["items"][0]
    assert e["end_ms"] >= e["start_ms"] and "pressure" in e["context"] and "leak" in e["context"]
    assert "OA" in ev["types"]


def test_timeseries_downsampling(api, imported):
    r = _night(api)
    d = api.get(f"/api/nights/{r['id']}").json()
    full = api.get(f"/api/nights/{r['id']}/timeseries", params={"channels": "flow,leak", "points": 500}).json()
    flow = full["channels"]["flow"]
    assert flow["downsampled"] and len(flow["t"]) <= 520 + 10
    # min/max envelope keeps the extreme values of the raw data
    ch = next(c for c in d["channels"] if c["code"] == "flow")
    vals = [v for v in flow["v"] if v is not None]
    assert abs(max(vals) - ch["max"]) < 0.01 and abs(min(vals) - ch["min"]) < 0.01
    # zoom: 30 s window returns raw 25 Hz samples
    t0 = d["night"]["start_ms"] + 600_000
    z = api.get(f"/api/nights/{r['id']}/timeseries", params={"channels": "flow", "start": t0, "end": t0 + 30_000}).json()
    zf = z["channels"]["flow"]
    assert not zf["downsampled"] and 740 <= len(zf["t"]) <= 760
    assert all(t0 - 100 <= t <= t0 + 30_100 for t in zf["t"])


def test_insights(api, imported):
    r = _night(api)
    ins = api.get(f"/api/nights/{r['id']}/insights").json()
    assert ins["summary"].startswith("Therapiedauer")
    assert "Diagnose" not in json.dumps(ins)
    assert isinstance(ins["hourly"], list) and ins["hourly"]


def test_search_language(api, imported):
    assert api.get("/api/nights", params={"q": "ahi>1000"}).json()["total"] == 0
    assert api.get("/api/nights", params={"q": "ahi>=0"}).json()["total"] == 4
    assert api.get("/api/nights", params={"q": FIRST_DAY.isoformat()}).json()["total"] == 1
    assert api.get("/api/nights", params={"q": "usage<100h 2026-09"}).json()["total"] == 4
    assert api.get("/api/nights", params={"q": "device:23000000001"}).json()["total"] == 4
    r = api.get("/api/nights", params={"q": "quatsch>1"})
    assert r.status_code == 400 and "Unbekannte Kennzahl" in r.json()["detail"]
    with_oa = api.get("/api/nights", params={"q": "event:OA"}).json()["total"]
    assert with_oa == api.get("/api/nights", params={"event": "OA"}).json()["total"]


def test_filters_and_sort(api, imported):
    rows = api.get("/api/nights", params={"sort": "ahi", "order": "asc"}).json()["items"]
    ahis = [r["metrics"]["ahi"] for r in rows]
    assert ahis == sorted(ahis)
    lim = ahis[1]
    assert api.get("/api/nights", params={"ahi_min": lim}).json()["total"] == sum(1 for a in ahis if a >= lim)


def test_calendar_and_by_date(api, imported):
    cal = api.get("/api/nights/calendar", params={"from": "2026-09-01", "to": "2026-09-30"}).json()
    assert len(cal["days"]) == 4 and cal["thresholds"]["ahi_yellow"] == 5
    r = api.get(f"/api/nights/by-date/{FIRST_DAY.isoformat()}")
    assert r.status_code == 200
    assert api.get("/api/nights/by-date/2020-01-01").status_code == 404


def test_compare(api, imported):
    ids = [r["id"] for r in api.get("/api/nights").json()["items"]][:3]
    c = api.get("/api/nights/compare", params={"ids": ",".join(map(str, ids))}).json()
    assert len(c["items"]) == 3 and any(m["key"] == "ahi" for m in c["metrics"])


def test_statistics(api, imported):
    s = api.get("/api/statistics/summary", params={"from": "2026-09-01", "to": "2026-09-04"}).json()
    assert s["compliance"]["nights_with_data"] == 4 and s["compliance"]["days"] == 4
    st = s["stats"]["ahi"]
    assert st["n"] == 4 and st["min"] <= st["median"] <= st["max"]
    assert s["best"]["ahi"] <= s["worst"]["ahi"]
    assert sum(s["event_totals"].values()) > 0
    t = api.get("/api/statistics/trends", params={"from": "2026-09-01", "to": "2026-09-07", "metrics": "ahi,usage_h"}).json()
    assert len(t["series"]["ahi"]["x"]) == 7 and t["series"]["ahi"]["y"][-1] is None  # gaps stay empty
    w = api.get("/api/statistics/trends", params={"preset": "all", "metrics": "ahi", "bucket": "week"}).json()
    assert w["series"]["ahi"]["n"]
    assert api.get("/api/statistics/events", params={"preset": "30"}).status_code == 200


def test_dashboard(api, imported):
    d = api.get("/api/dashboard").json()
    assert not d["empty"] and d["last_night"]["date"] == "2026-09-04"
    assert d["agg7"]["nights"] == 4 and len(d["recent"]) == 4


def test_dashboard_empty(api):
    assert api.get("/api/dashboard").json()["empty"] is True


def test_notes(api, imported):
    r = _night(api)
    assert api.patch(f"/api/nights/{r['id']}", json={"notes": "Neue Maske"}).status_code == 200
    assert api.get(f"/api/nights/{r['id']}").json()["night"]["notes_text"] == "Neue Maske"
    assert api.get("/api/nights", params={"q": "notizen"}).json()["total"] == 1


def test_reports(api, imported):
    j = api.get("/api/reports/week", params={"start": "2026-09-01"}).json()
    assert j["from"] == "2026-08-31" and j["to"] == "2026-09-06"
    assert j["summary"]["compliance"]["nights_with_data"] == 4 and j["highlights"]
    m = api.get("/api/reports/month", params={"month": "2026-09", "format": "html"})
    assert m.status_code == 200 and "Monatsbericht September 2026" in m.text and "<svg" in m.text
    pdf = api.get("/api/reports/month", params={"month": "2026-09", "format": "pdf"})
    assert pdf.content[:4] == b"%PDF"
    csv = api.get("/api/reports/custom", params={"start": "2026-09-01", "end": "2026-09-04", "format": "csv"})
    assert csv.text.splitlines()[0].startswith("Datum") and len(csv.text.splitlines()) == 5


def test_exports(api, imported):
    n = api.get("/api/export/nights.csv")
    assert n.status_code == 200 and n.text.splitlines()[0].startswith("date,") and len(n.text.splitlines()) == 5
    semi = api.get("/api/export/nights.csv", params={"sep": "semicolon"})
    assert semi.text.splitlines()[0].startswith("date;")
    assert len(api.get("/api/export/nights.json").json()) == 4
    ev = api.get("/api/export/events.csv")
    assert "OA" in ev.text or "H" in ev.text
    r = _night(api)
    ts = api.get(f"/api/export/nights/{r['id']}/timeseries.csv", params={"channels": "leak"})
    lines = ts.text.splitlines()
    assert lines[0] == "timestamp,channel,value,unit" and lines[1].split(",")[1] == "leak"
    z = api.get("/api/export/archive.zip", params={"timeseries": "true", "to": FIRST_DAY.isoformat()})
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert {"naechte.csv", "ereignisse.csv", "einstellungen.json", "geraete.json"} <= set(names)
    assert any(x.startswith("zeitreihen/") for x in names)
    raw = api.get("/api/export/raw.zip")
    rn = zipfile.ZipFile(io.BytesIO(raw.content)).namelist()
    assert "STR.edf" in rn and any(x.startswith("DATALOG/") for x in rn)
    rawimp = api.get("/api/export/raw.zip", params={"import_id": imported["id"]})
    assert any("CPAP_SD_2026-09-05/STR.edf" in x for x in zipfile.ZipFile(io.BytesIO(rawimp.content)).namelist())


def test_raw_export_is_bit_identical(api, imported, synthetic_card):
    raw = api.get("/api/export/raw.zip")
    zf = zipfile.ZipFile(io.BytesIO(raw.content))
    for name in zf.namelist():
        assert zf.read(name) == (synthetic_card / name).read_bytes()


def test_devices_and_settings_history(api, imported):
    devs = api.get("/api/devices").json()
    assert len(devs) == 1 and devs[0]["nights"] == 4 and "flow" in devs[0]["channels"]
    h = api.get(f"/api/devices/{devs[0]['id']}/settings-history").json()
    assert h["periods"] and h["periods"][0]["settings"]["S.EPR.Level"] == 2
    r = api.patch(f"/api/devices/{devs[0]['id']}", json={"display_name": "Schlafzimmer"})
    assert r.json()["display_name"] == "Schlafzimmer"


def test_preferences_thresholds_change_status(api, imported):
    api.put("/api/auth/preferences", json={"thresholds": {"ahi_yellow": 0.0, "ahi_red": 0.0}})
    statuses = {r["status"] for r in api.get("/api/nights").json()["items"]}
    assert statuses == {"red"}


def test_health_and_diagnostics(api, imported):
    assert api.get("/api/health").json()["status"] == "ok"
    d = api.get("/api/system/diagnostics").json()
    assert d["counts"]["nights"] == 4 and d["storage"]["raw_bytes"] > 0
    assert "password" not in json.dumps(d).lower()


def test_openapi_and_channels(api):
    spec = api.get("/api/openapi.json").json()
    assert "/api/nights/{night_id}/timeseries" in spec["paths"]
    ch = api.get("/api/channels").json()
    assert ch["channels"]["flow"]["unit"] == "L/min"


def test_oximetry_import(api, synthetic_card_oxi):
    from conftest import upload_zip, zip_dir

    res = upload_zip(api, zip_dir(synthetic_card_oxi))
    assert res["status"] == "completed"
    r = api.get("/api/nights").json()["items"][0]
    d = api.get(f"/api/nights/{r['id']}").json()
    keys = {m["key"] for m in d["metrics"]}
    assert {"spo2.median", "pulse.mean", "odi", "spo2.time_below_90_pct"} <= keys
    dev = api.get("/api/devices").json()[0]
    assert dev["series"] == "AirSense 11"
