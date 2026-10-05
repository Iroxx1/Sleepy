"""Shared fixtures.  All test data is *synthetic* (see cpap_parser.testing)."""

from __future__ import annotations

import io
import sys
import zipfile
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "parser"), str(ROOT / "backend")]

from cpap_parser.testing.synthetic_resmed import write_card  # noqa: E402

FIRST_DAY = date(2026, 9, 1)


@pytest.fixture(scope="session")
def synthetic_card(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("card") / "SD"
    write_card(root, FIRST_DAY, nights=4, seed=7, hours=(1.0, 2.0), skip_probability=0.0)
    return root


@pytest.fixture(scope="session")
def synthetic_card_oxi(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("card_oxi") / "SD"
    write_card(root, FIRST_DAY, nights=2, seed=11, hours=(1.0, 1.5), skip_probability=0.0, oximetry=True,
               as11=True, model="AirSense_11_AutoSet", serial="22000000002", product_code="39000")
    return root


def zip_dir(root: Path, prefix: str = "") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                zf.write(p, prefix + p.relative_to(root).as_posix())
    return buf.getvalue()


@pytest.fixture()
def data_dir(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "data"
    monkeypatch.setenv("SLEEPY_DATA_DIR", str(d))
    monkeypatch.setenv("SLEEPY_FRONTEND_DIST", str(tmp_path / "no-frontend"))
    monkeypatch.delenv("SLEEPY_DATABASE_URL", raising=False)
    monkeypatch.delenv("SLEEPY_IMPORT_DIR", raising=False)
    from sleepy import config, db
    from sleepy.security import login_limiter

    config.reset_settings_cache()
    db.reset_engine()
    login_limiter.clear()
    yield d
    db.reset_engine()
    config.reset_settings_cache()


@pytest.fixture()
def app(data_dir):
    from sleepy.importer.worker import worker
    from sleepy.main import create_app

    worker.synchronous = True
    return create_app()


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://testserver") as c:
        yield c


class Api:
    """Small helper adding the CSRF header automatically."""

    def __init__(self, client):
        self.c = client

    @property
    def csrf(self) -> str:
        return self.c.cookies.get("sleepy_csrf", "")

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def _w(self, method, url, **kw):
        headers = kw.pop("headers", {}) or {}
        headers.setdefault("X-CSRF-Token", self.csrf)
        return getattr(self.c, method)(url, headers=headers, **kw)

    def post(self, url, **kw):
        return self._w("post", url, **kw)

    def put(self, url, **kw):
        return self._w("put", url, **kw)

    def patch(self, url, **kw):
        return self._w("patch", url, **kw)

    def delete(self, url, **kw):
        return self._w("delete", url, **kw)


@pytest.fixture()
def api(client) -> Api:
    a = Api(client)
    r = a.post("/api/auth/setup", json={"username": "admin", "password": "sehr-geheim-123"})
    assert r.status_code == 200, r.text
    return a


def upload_zip(api: Api, data: bytes, name: str = "CPAP_SD.zip") -> dict:
    r = api.post("/api/imports", json={"source": "zip", "name": name})
    assert r.status_code == 200, r.text
    imp = r.json()
    r = api.put(f"/api/imports/{imp['id']}/upload", params={"filename": name}, content=data)
    assert r.status_code == 200, r.text
    r = api.post(f"/api/imports/{imp['id']}/start")
    assert r.status_code == 200, r.text
    r = api.get(f"/api/imports/{imp['id']}")
    return r.json()


@pytest.fixture()
def imported(api, synthetic_card):
    res = upload_zip(api, zip_dir(synthetic_card, "CPAP_SD_2026-09-05/"))
    assert res["status"] == "completed", res
    return res
