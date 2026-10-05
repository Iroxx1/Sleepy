import io
import os
import shutil
import stat
import zipfile

from conftest import FIRST_DAY, upload_zip, zip_dir
from cpap_parser.edf_writer import EDFSpec, WAnnotation, write_edf


def test_zip_import_creates_nights_and_archives(api, imported, data_dir):
    s = imported["stats"]
    assert s["nights_created"] == 4 and s["files_error"] == 0 and s["nights_failed"] == 0
    assert imported["devices"][0]["serial"] == "23000000001"
    files = api.get(f"/api/imports/{imported['id']}/files", params={"limit": 2000}).json()
    new = [f for f in files["items"] if f["status"] == "new"]
    assert len(new) == s["files_new"] > 0
    # archived originals are byte-identical and read-only
    from sleepy.storage import raw_abs_path, raw_rel_path, sha256_file

    for f in new[:10]:
        p = raw_abs_path(raw_rel_path(f["sha256"]))
        assert p.exists() and sha256_file(p) == f["sha256"]
        assert not (os.stat(p).st_mode & stat.S_IWUSR)
    assert f["sd_path"] and not f["sd_path"].startswith("CPAP_SD")  # path normalised to card root


def test_reimport_is_duplicate(api, imported, synthetic_card):
    res = upload_zip(api, zip_dir(synthetic_card))  # different folder prefix, same content
    assert res["status"] == "completed"
    s = res["stats"]
    assert s.get("files_new", 0) == 0 and s["files_duplicate"] == imported["stats"]["files_new"]
    assert s.get("nights_created", 0) == 0 and s.get("nights_updated", 0) == 0
    assert "0 neue Nächte importiert" in res["message"]
    assert api.get("/api/nights").json()["total"] == 4


def test_new_night_and_updated_file(api, imported, synthetic_card, tmp_path):
    from cpap_parser.testing.synthetic_resmed import write_card

    root = tmp_path / "SD"
    shutil.copytree(synthetic_card, root)
    # one additional night on a newer card copy (all other files identical)
    extra = tmp_path / "extra"
    write_card(extra, FIRST_DAY, nights=5, seed=7, hours=(1.0, 2.0), skip_probability=0)
    day5 = (FIRST_DAY.replace(day=FIRST_DAY.day + 4)).strftime("%Y%m%d")
    shutil.copytree(extra / "DATALOG" / day5, root / "DATALOG" / day5)
    shutil.copy(extra / "STR.edf", root / "STR.edf")
    # modify the event file of night 1 -> new version
    day1 = root / "DATALOG" / FIRST_DAY.strftime("%Y%m%d")
    eve = next(day1.glob("*_EVE.edf"))
    from datetime import datetime

    start = datetime.strptime(eve.name[:15], "%Y%m%d_%H%M%S")
    write_edf(eve, EDFSpec(start=start, record_duration=0, n_records=1, signals=[], edfplus="EDF+D",
                           annotations=[WAnnotation(600, 20, "Central Apnea")]))
    res = upload_zip(api, zip_dir(root))
    s = res["stats"]
    assert s["nights_created"] == 1
    assert s["files_updated"] >= 2  # EVE + STR.edf
    assert s["nights_updated"] >= 1
    n1 = api.get("/api/nights", params={"from": FIRST_DAY.isoformat(), "to": FIRST_DAY.isoformat()}).json()["items"][0]
    ev = api.get(f"/api/nights/{n1['id']}/events").json()["items"]
    assert [e["code"] for e in ev] == ["CA"]
    # the old version is still in the archive (never destroyed)
    files = api.get(f"/api/imports/{imported['id']}/files", params={"limit": 2000}).json()["items"]
    old_eve = [f for f in files if f["sd_path"].endswith(eve.name)][0]
    from sleepy.storage import raw_abs_path, raw_rel_path

    assert raw_abs_path(raw_rel_path(old_eve["sha256"])).exists()


def test_folder_upload(api, synthetic_card):
    r = api.post("/api/imports", json={"source": "folder", "name": "SD"})
    imp = r.json()
    paths = [p for p in sorted(synthetic_card.rglob("*")) if p.is_file()]
    for i in range(0, len(paths), 20):
        batch = paths[i: i + 20]
        files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in batch]
        data = {"paths": ["SD/" + p.relative_to(synthetic_card).as_posix() for p in batch]}
        r = api.post(f"/api/imports/{imp['id']}/files", files=files, data=data)
        assert r.status_code == 200, r.text
    r = api.post(f"/api/imports/{imp['id']}/start")
    res = api.get(f"/api/imports/{imp['id']}").json()
    assert res["status"] == "completed" and res["stats"]["nights_created"] == 4


def test_folder_upload_rejects_traversal(api):
    imp = api.post("/api/imports", json={"source": "folder"}).json()
    r = api.post(f"/api/imports/{imp['id']}/files", files=[("files", ("x", b"x"))], data={"paths": ["../../etc/passwd"]})
    assert r.status_code == 400


def test_server_dir_import(api, synthetic_card, monkeypatch, tmp_path):
    from sleepy import config

    d = tmp_path / "import"
    shutil.copytree(synthetic_card, d / "card")
    monkeypatch.setenv("SLEEPY_IMPORT_DIR", str(d))
    config.reset_settings_cache()
    info = api.get("/api/imports/server-info").json()
    assert info["configured"] and info["exists"]
    res = api.post("/api/imports/server-scan").json()
    res = api.get(f"/api/imports/{res['id']}").json()
    assert res["status"] == "completed" and res["stats"]["nights_created"] == 4
    # source directory untouched
    assert (d / "card" / "STR.edf").exists()
    res2 = api.get(f"/api/imports/{api.post('/api/imports/server-scan').json()['id']}").json()
    assert res2["stats"]["files_duplicate"] > 0 and res2["stats"].get("nights_created", 0) == 0


def test_junk_files_ignored(api, synthetic_card):
    data = zip_dir(synthetic_card)
    buf = io.BytesIO(data)
    with zipfile.ZipFile(buf, "a") as zf:
        zf.writestr("__MACOSX/._STR.edf", b"junk")
        zf.writestr(".DS_Store", b"junk")
    res = upload_zip(api, buf.getvalue())
    assert res["status"] == "completed" and res["stats"]["files_ignored"] == 2


def test_not_a_zip(api):
    res = upload_zip(api, b"definitely not a zip file")
    assert res["status"] == "failed"
    assert "kein gültiges ZIP" in res["error"]


def test_zip_without_cpap_data(api):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("photos/img1.jpg", b"123")
    res = upload_zip(api, buf.getvalue())
    assert res["status"] == "failed"
    assert "Keine bekannten CPAP-Daten" in res["error"]
    assert res["can_retry"]


def test_zip_slip_rejected(api):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", b"x")
    res = upload_zip(api, buf.getvalue())
    assert res["status"] == "failed" and "Unsicherer Pfad" in res["error"]


def test_corrupt_night_does_not_abort_import(api, synthetic_card, tmp_path):
    root = tmp_path / "SD"
    shutil.copytree(synthetic_card, root)
    day = root / "DATALOG" / FIRST_DAY.strftime("%Y%m%d")
    for f in day.glob("*.edf"):
        f.write_bytes(b"garbage")
    # also break STR so the night has no usable data at all
    res = upload_zip(api, zip_dir(root))
    assert res["status"] in ("completed", "completed_with_errors")
    assert res["stats"]["nights_created"] >= 3
    assert any("konnte nicht gelesen werden" in (entry["text"]) for entry in res["log"])


def test_retry_after_failure(api, synthetic_card):
    imp = api.post("/api/imports", json={"source": "zip", "name": "x.zip"}).json()
    api.put(f"/api/imports/{imp['id']}/upload", params={"filename": "x.zip"}, content=b"broken")
    api.post(f"/api/imports/{imp['id']}/start")
    assert api.get(f"/api/imports/{imp['id']}").json()["status"] == "failed"
    # replace the staged file with a valid zip and retry
    from sleepy.importer.pipeline import staging_path

    (staging_path(imp["id"]) / "upload" / "x.zip").write_bytes(zip_dir(synthetic_card))
    r = api.post(f"/api/imports/{imp['id']}/retry")
    assert r.status_code == 200
    assert api.get(f"/api/imports/{imp['id']}").json()["status"] == "completed"


def test_unsupported_manufacturer_archived(api):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("P-Series/P1234/prop.txt", b"x")
        zf.writestr("P-Series/P1234/p0/00000001.001", b"y")
    res = upload_zip(api, buf.getvalue())
    assert res["status"] == "completed"
    assert any("nicht unterstützt" in entry["text"] for entry in res["log"])
    files = api.get(f"/api/imports/{res['id']}/files").json()["items"]
    assert all(f["sha256"] for f in files)  # archived anyway


def test_reprocess(api, imported):
    r = api.post("/api/system/reprocess")
    res = api.get(f"/api/imports/{r.json()['import_id']}").json()
    assert res["status"] == "completed" and res["stats"]["nights_updated"] == 4
