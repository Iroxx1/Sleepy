from datetime import date, timedelta

from conftest import FIRST_DAY


def test_hardware_crud_and_due(api):
    start = date.today() - timedelta(days=360)
    r = api.post("/api/hardware", json={"category": "mask", "name": "AirFit F20", "size": "M",
                                        "started_on": start.isoformat(), "replace_after_days": 365})
    assert r.status_code == 200, r.text
    it = r.json()
    assert it["active"] and it["age_days"] == 360
    assert it["due"]["status"] == "soon" and it["due"]["days_left"] == 5
    r = api.patch(f"/api/hardware/{it['id']}", json={"notes": "Kissen gut"})
    assert r.json()["notes"] == "Kissen gut"
    assert api.post("/api/hardware", json={"category": "mask", "name": "x", "started_on": "2026-02-01",
                                           "ended_on": "2026-01-01"}).status_code == 400
    assert api.post("/api/hardware", json={"category": "spaceship", "name": "x"}).status_code == 422
    lst = api.get("/api/hardware").json()
    assert len(lst["items"]) == 1 and lst["categories"]["mask"] == "Maske"
    assert api.delete(f"/api/hardware/{it['id']}").status_code == 200
    assert api.get("/api/hardware").json()["items"] == []


def test_replace_mask(api):
    it = api.post("/api/hardware", json={"category": "mask", "name": "Maske 2025", "started_on": "2025-10-01",
                                         "replace_after_days": 365}).json()
    r = api.post(f"/api/hardware/{it['id']}/replace", json={"started_on": "2026-10-01", "name": "Maske 2026"})
    assert r.status_code == 200
    assert r.json()["old"]["ended_on"] == "2026-09-30" and not r.json()["old"]["active"]
    assert r.json()["new"]["started_on"] == "2026-10-01" and r.json()["new"]["replace_after_days"] == 365
    assert api.post(f"/api/hardware/{it['id']}/replace", json={"started_on": "2025-01-01"}).status_code == 400
    tl = api.get("/api/hardware/timeline", params={"from": "2026-09-01"}).json()
    assert [(t["kind"], t["date"]) for t in tl] == [("end", "2026-09-30"), ("start", "2026-10-01")]


def test_blower_hours(api):
    dev = api.post("/api/hardware", json={"category": "device", "name": "AirSense 10", "started_on": "2025-01-01",
                                          "expected_hours": 20000}).json()
    api.post(f"/api/hardware/{dev['id']}/readings", json={"read_on": "2026-01-01", "value": 2000})
    r = api.post(f"/api/hardware/{dev['id']}/readings", json={"read_on": "2026-04-11", "value": 2800, "note": "Info-Menü"})
    st = r.json()["reading_stats"]["blower_hours"]
    assert st["latest_value"] == 2800 and st["count"] == 2
    assert abs(st["per_day"] - 8.0) < 1e-9
    assert abs(st["projection"]["pct_used"] - 14.0) < 1e-9
    assert st["projection"]["estimated_date"] == (date(2026, 4, 11) + timedelta(days=17200 / 8)).isoformat()
    assert not st["decreasing"]
    rid = r.json()["readings"][0]["id"]
    assert api.delete(f"/api/hardware/{dev['id']}/readings/{rid}").status_code == 200


def test_usage_and_impact(api, imported):
    it = api.post("/api/hardware", json={"category": "mask", "name": "Neu",
                                         "started_on": (FIRST_DAY + timedelta(days=2)).isoformat()}).json()
    assert it["therapy_usage"]["nights"] == 2 and it["therapy_usage"]["hours"] > 1
    imp = api.get(f"/api/hardware/{it['id']}/impact", params={"days": 7}).json()
    ahi = next(m for m in imp["metrics"] if m["key"] == "ahi")
    assert ahi["before"]["n"] == 2 and ahi["after"]["n"] == 2 and ahi["diff_median"] is not None


def test_hardware_isolated_between_users(api):
    it = api.post("/api/hardware", json={"category": "tube", "name": "ClimateLine"}).json()
    api.post("/api/users", json={"username": "bob", "password": "bob-passwort-1"})
    api.post("/api/auth/logout")
    api.post("/api/auth/login", json={"username": "bob", "password": "bob-passwort-1"})
    assert api.get("/api/hardware").json()["items"] == []
    assert api.get(f"/api/hardware/{it['id']}").status_code == 404


def test_custom_css(api, client):
    assert api.put("/api/appearance/user", json={"css": ":root{--primary:#16a34a}"}).status_code == 200
    r = api.get("/api/appearance/user.css")
    assert r.headers["content-type"].startswith("text/css") and "--primary" in r.text
    assert api.put("/api/appearance/user", json={"css": "body{background:url(javascript:alert(1))}"}).status_code == 400
    assert api.put("/api/appearance/global", json={"css": "body{font-size:16px}"}).status_code == 200
    api.post("/api/auth/logout")
    assert "font-size" in client.get("/api/appearance/global.css").text  # public for login page
    assert client.get("/api/appearance/user.css").text == ""


def test_demo_import_and_device_delete(api, data_dir):
    r = api.post("/api/imports/demo", json={"nights": 5})
    res = api.get(f"/api/imports/{r.json()['id']}").json()
    assert res["status"] == "completed" and res["stats"]["nights_created"] >= 4
    dev = api.get("/api/devices").json()[0]
    assert dev["serial"] == "DEMO00000001" and "Demo" in dev["display_name"]
    assert api.delete(f"/api/devices/{dev['id']}", params={"confirm": "falsch"}).status_code == 400
    r = api.delete(f"/api/devices/{dev['id']}", params={"confirm": "DEMO00000001", "delete_raw": "true"})
    assert r.status_code == 200 and r.json()["raw_files_deleted"] > 0
    assert api.get("/api/devices").json() == [] and api.get("/api/nights").json()["total"] == 0
    assert not any((data_dir / "raw").rglob("*.*")) and not list((data_dir / "raw").glob("*/*/*"))
