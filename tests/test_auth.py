import pyotp

from conftest import Api


def test_setup_only_once(client):
    a = Api(client)
    assert a.get("/api/auth/setup-status").json()["needs_setup"]
    r = a.post("/api/auth/setup", json={"username": "admin", "password": "kurz"})
    assert r.status_code == 400
    assert a.post("/api/auth/setup", json={"username": "admin", "password": "sehr-geheim-123"}).status_code == 200
    assert a.post("/api/auth/setup", json={"username": "xyz", "password": "sehr-geheim-123"}).status_code == 403


def test_requires_login(client):
    assert client.get("/api/nights").status_code == 401
    assert client.get("/api/dashboard").status_code == 401
    assert client.get("/api/openapi.json").status_code == 401
    assert client.get("/api/health").status_code == 200


def test_login_logout_and_cookie_flags(api, client):
    api.post("/api/auth/logout")
    r = api.post("/api/auth/login", json={"username": "ADMIN", "password": "sehr-geheim-123"})
    assert r.status_code == 200
    cookie = [h for h in r.headers.get_list("set-cookie") if h.startswith("sleepy_session=")][0].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert api.get("/api/auth/me").json()["user"]["username"] == "admin"
    api.post("/api/auth/logout")
    assert api.get("/api/nights").status_code == 401


def test_wrong_password_and_rate_limit(api):
    api.post("/api/auth/logout")
    for _ in range(10):
        assert api.post("/api/auth/login", json={"username": "admin", "password": "falsch-falsch"}).status_code == 401
    r = api.post("/api/auth/login", json={"username": "admin", "password": "sehr-geheim-123"})
    assert r.status_code == 429


def test_csrf_required(api, client):
    r = client.post("/api/imports", json={"source": "zip"})  # no header
    assert r.status_code == 403
    r = client.post("/api/imports", json={"source": "zip"}, headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403
    assert api.post("/api/imports", json={"source": "zip"}).status_code == 200


def test_foreign_origin_rejected(api):
    r = api.post("/api/imports", json={"source": "zip"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_security_headers(client):
    r = client.get("/api/health")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_totp_flow(api):
    setup = api.post("/api/auth/totp/setup").json()
    assert setup["qr_svg"].startswith("<?xml") or "<svg" in setup["qr_svg"]
    code = pyotp.TOTP(setup["secret"]).now()
    assert api.post("/api/auth/totp/enable", json={"code": "000000"}).status_code == 400
    assert api.post("/api/auth/totp/enable", json={"code": code}).status_code == 200
    api.post("/api/auth/logout")
    r = api.post("/api/auth/login", json={"username": "admin", "password": "sehr-geheim-123"})
    assert r.json()["mfa_required"] is True
    assert api.get("/api/nights").status_code == 401  # MFA pending
    assert api.post("/api/auth/totp/verify", json={"code": "123456"}).status_code == 401
    assert api.post("/api/auth/totp/verify", json={"code": pyotp.TOTP(setup["secret"]).now()}).status_code == 200
    assert api.get("/api/nights").status_code == 200


def test_password_change(api):
    r = api.post("/api/auth/password", json={"current_password": "falsch", "new_password": "neues-passwort-1"})
    assert r.status_code == 400
    r = api.post("/api/auth/password", json={"current_password": "sehr-geheim-123", "new_password": "neues-passwort-1"})
    assert r.status_code == 200
    api.post("/api/auth/logout")
    assert api.post("/api/auth/login", json={"username": "admin", "password": "neues-passwort-1"}).status_code == 200


def test_session_idle_timeout(api, monkeypatch):
    from datetime import timedelta

    from sleepy.db import SessionLocal
    from sleepy.models import AuthSession

    with SessionLocal() as db:
        for s in db.query(AuthSession):
            s.last_seen_at = s.last_seen_at - timedelta(days=2)
        db.commit()
    assert api.get("/api/nights").status_code == 401


def test_user_admin_and_isolation(api, client, imported):
    assert api.post("/api/users", json={"username": "bob", "password": "bob-passwort-1", "role": "user"}).status_code == 200
    users = api.get("/api/users").json()
    assert {u["username"] for u in users} == {"admin", "bob"}
    api.post("/api/auth/logout")
    assert api.post("/api/auth/login", json={"username": "bob", "password": "bob-passwort-1"}).status_code == 200
    assert api.get("/api/nights").json()["total"] == 0  # bob sees nothing of admin's data
    nid = imported and 1
    assert api.get(f"/api/nights/{nid}").status_code == 404
    assert api.get("/api/users").status_code == 403
    assert api.get("/api/system/diagnostics").status_code == 403
    assert api.get(f"/api/imports/{imported['id']}").status_code == 404


def test_admin_cannot_demote_self(api):
    me = api.get("/api/auth/me").json()["user"]
    assert api.patch(f"/api/users/{me['id']}", json={"role": "user"}).status_code == 400
    assert api.delete(f"/api/users/{me['id']}").status_code == 400


def test_audit_log(api):
    api.post("/api/auth/logout")
    api.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    api.post("/api/auth/login", json={"username": "admin", "password": "sehr-geheim-123"})
    actions = [a["action"] for a in api.get("/api/system/audit").json()]
    assert "login_failed" in actions and "login" in actions
