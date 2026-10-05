"""FastAPI application factory."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from cpap_parser.channels import CHANNELS, EVENTS

from . import __version__
from .api import admin, appearance, auth, exports, hardware, imports, nights, reports, statistics
from .api.deps import UNSAFE, current_user
from .config import get_settings
from .db import init_db
from .importer.worker import worker
from .logging_setup import setup_logging

log = logging.getLogger("sleepy")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; "
    "object-src 'none'"
)


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Origin check for state changing requests (CSRF defence in depth)
        if request.method in UNSAFE:
            origin = request.headers.get("origin")
            if origin and origin != "null":
                host = request.headers.get("host", "")
                allowed = {o.strip() for o in get_settings().allowed_origins.split(",") if o.strip()}
                if urlparse(origin).netloc != host and origin not in allowed:
                    return JSONResponse({"detail": "Ungültiger Origin"}, status_code=403)
        request.state.request_id = uuid.uuid4().hex[:10]
        response = await call_next(request)
        h = response.headers
        h.setdefault("Content-Security-Policy", CSP)
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), interest-cohort=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.url.scheme == "https":
            h.setdefault("Strict-Transport-Security", "max-age=31536000")
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        return response


def ensure_initial_admin() -> None:
    """Optionally create an admin from SLEEPY_INITIAL_ADMIN_USER/_PASSWORD."""
    import os

    from sqlalchemy import func, select

    from .db import session_scope
    from .models import User
    from .security import hash_password

    user = os.environ.get("SLEEPY_INITIAL_ADMIN_USER")
    pw = os.environ.get("SLEEPY_INITIAL_ADMIN_PASSWORD")
    if not user or not pw:
        return
    with session_scope() as db:
        if (db.scalar(select(func.count()).select_from(User)) or 0) == 0:
            db.add(User(username=user, password_hash=hash_password(pw), role="admin"))
            log.info("Initialer Administrator '%s' angelegt", user)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    ensure_initial_admin()
    worker.start()
    log.info("Sleepy %s gestartet, Daten in %s", __version__, get_settings().data_dir)
    yield
    worker.stop()


def create_app() -> FastAPI:
    st = get_settings()
    app = FastAPI(
        title="Sleepy – CPAP-Datenanalyse API",
        version=__version__,
        description="Lokale REST-API für Import, Analyse und Export von CPAP/PAP-Therapiedaten. "
        "Authentifizierung über Session-Cookie; schreibende Anfragen benötigen den Header X-CSRF-Token.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(SecurityMiddleware)

    for r in (auth, imports, nights, statistics, reports, exports, admin, hardware, appearance):
        app.include_router(r.router)

    @app.get("/api/channels", tags=["nights"])
    def channel_registry(user=Depends(current_user)):
        return {
            "channels": {c: {"name": d.name, "unit": d.unit, "group": d.group} for c, d in CHANNELS.items()},
            "events": {c: {"name": e.name, "short": e.short, "color": e.color, "span": e.span} for c, e in EVENTS.items()},
        }

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        errs = []
        for e in exc.errors():
            loc = ".".join(str(x) for x in e.get("loc", []) if x not in ("body", "query"))
            errs.append(f"{loc}: {e.get('msg')}")
        return JSONResponse({"detail": "Ungültige Eingabe – " + "; ".join(errs)}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        ref = getattr(request.state, "request_id", uuid.uuid4().hex[:10])
        log.exception("Unbehandelter Fehler (Referenz %s) bei %s %s", ref, request.method, request.url.path)
        return JSONResponse(
            {"detail": f"Interner Fehler. Bitte Protokoll prüfen (Referenz {ref})."}, status_code=500
        )

    # ---------------------------------------------------- API documentation
    if st.enable_api_docs:

        @app.get("/api/openapi.json", include_in_schema=False)
        def openapi(user=Depends(current_user)):
            return app.openapi()

        @app.get("/api/docs", include_in_schema=False)
        def docs(request: Request):
            dist = st.frontend_path / "swagger"
            if not (dist / "swagger-ui-bundle.js").exists():
                return HTMLResponse(
                    "<p>Swagger-UI-Dateien fehlen (Frontend-Build). Schema: <a href='/api/openapi.json'>/api/openapi.json</a></p>"
                )
            return HTMLResponse(
                """<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Sleepy API</title>
<link rel="stylesheet" href="/swagger/swagger-ui.css"></head><body><div id="swagger-ui"></div>
<script src="/swagger/swagger-ui-bundle.js"></script><script src="/swagger/init.js"></script></body></html>"""
            )

    # ------------------------------------------------------ frontend (SPA)
    dist = st.frontend_path

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Nicht gefunden")
        if not dist.exists():
            return HTMLResponse(
                "<h1>Sleepy</h1><p>Das Frontend wurde noch nicht gebaut (<code>cd frontend && npm ci && npm run build</code>). "
                "Die API läuft unter <code>/api</code>.</p>",
                status_code=503,
            )
        target = (dist / full_path).resolve()
        if full_path and str(target).startswith(str(dist.resolve())) and target.is_file():
            headers = {}
            if "/assets/" in f"/{full_path}":
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return FileResponse(target, headers=headers)
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def run() -> None:  # pragma: no cover - entry point
    import uvicorn

    st = get_settings()
    uvicorn.run(
        "sleepy.main:create_app",
        factory=True,
        host=st.host,
        port=st.port,
        proxy_headers=True,
        forwarded_allow_ips=st.trusted_proxies,
        log_level=st.log_level.lower(),
        access_log=False,
    )

