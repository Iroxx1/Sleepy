import tarfile

from sleepy.backup import create_backup, list_backups, restore_backup


def test_backup_and_restore(api, imported, data_dir):
    r = api.post("/api/system/backups")
    assert r.status_code == 200
    name = r.json()["name"]
    assert any(b["name"] == name for b in api.get("/api/system/backups").json())
    dl = api.get(f"/api/system/backups/{name}")
    assert dl.status_code == 200 and dl.content[:2] == b"\x1f\x8b"
    path = data_dir / "backups" / name
    with tarfile.open(path) as t:
        names = t.getnames()
    assert "manifest.json" in names and "db/sleepy.db" in names
    assert any(n.startswith("raw/") for n in names) and any(n.startswith("signals/") for n in names)
    # destroy some data, then restore
    api.post("/api/system/reprocess")
    from sleepy import db

    db.reset_engine()
    res = restore_backup(path)
    assert (data_dir / "raw").exists() and res["previous_data"]
    db.reset_engine()
    assert api.get("/api/nights").json()["total"] == 4


def test_backup_path_traversal(api):
    assert api.get("/api/system/backups/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_backup_rotation(api, data_dir, monkeypatch):
    from sleepy import config

    monkeypatch.setenv("SLEEPY_BACKUP_KEEP", "2")
    config.reset_settings_cache()
    for _ in range(3):
        create_backup(include_raw=False)
        import time

        time.sleep(1.1)
    assert len(list_backups()) == 2
