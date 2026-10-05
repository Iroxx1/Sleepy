import pyotp

from conftest import Api


def _app_login(client, **kw):
    body = {"username": "admin", "password": "sehr-geheim-123", "device_name": "Pixel 8", **kw}
    return client.post("/api/auth/app-login", json=body)


def test_app_token_login_and_use(api, client, imported):
    client.cookies.clear()
    r = _app_login(client)
    assert r.status_code == 200 and r.json()["token"] and r.json()["user"]["username"] == "admin"
    assert "sleepy_session" not in r.headers.get("set-cookie", "")
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/api/dashboard", headers=h).json()["short_summary"]
    # no CSRF header needed and foreign Origin of the WebView is fine for bearer requests
    w = client.patch(f"/api/nights/{client.get('/api/nights', headers=h).json()['items'][0]['id']}",
                     json={"notes": "vom Handy"}, headers={**h, "Origin": "https://localhost"})
    assert w.status_code == 200
    assert client.get("/api/nights").status_code == 401  # without token / cookie
    assert client.get("/api/nights", headers={"Authorization": "Bearer falsch"}).status_code == 401


def test_bearer_cannot_use_web_session_token(api, client):
    token = client.cookies.get("sleepy_session")
    client.cookies.clear()
    assert client.get("/api/nights", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_app_login_wrong_password_and_rate_limit(client, api):
    client.cookies.clear()
    for _ in range(10):
        assert _app_login(client, password="falsch-falsch").status_code == 401
    assert _app_login(client).status_code == 429


def test_app_login_totp(api, client):
    setup = api.post("/api/auth/totp/setup").json()
    api.post("/api/auth/totp/enable", json={"code": pyotp.TOTP(setup["secret"]).now()})
    client.cookies.clear()
    r = _app_login(client)
    assert r.status_code == 200 and r.json()["mfa_required"] and r.json()["token"] is None
    assert _app_login(client, code="000000").status_code == 401
    r = _app_login(client, code=pyotp.TOTP(setup["secret"]).now())
    assert r.json()["token"]


def test_app_sessions_list_revoke_logout(api, client):
    tok = _app_login(client).json()["token"]
    sessions = api.get("/api/auth/app-sessions").json()
    assert len(sessions) == 1 and sessions[0]["device_name"] == "Pixel 8"
    assert api.delete(f"/api/auth/app-sessions/{sessions[0]['id']}").status_code == 200
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/nights", headers=h).status_code == 401
    tok2 = _app_login(client).json()["token"]
    h2 = {"Authorization": f"Bearer {tok2}"}
    assert Api(client).c.post("/api/auth/app-logout", headers=h2).status_code == 200
    assert client.get("/api/nights", headers=h2).status_code == 401
