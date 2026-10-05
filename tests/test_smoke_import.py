def test_import_end_to_end(api, imported):
    assert imported["stats"]["nights_created"] == 4
    r = api.get("/api/nights")
    assert r.status_code == 200
    assert r.json()["total"] == 4
