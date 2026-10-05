"""Command line administration: ``sleepy <command>``.

    sleepy serve                     start the web server
    sleepy init-db                   create / migrate the database
    sleepy create-user NAME [--admin] [--password PW]
    sleepy reset-password NAME [--password PW]
    sleepy list-users
    sleepy import-dir PATH [--user NAME]   import an SD card copy from a server directory
    sleepy reprocess [--user NAME]         rebuild all nights from the raw archive
    sleepy backup [--no-raw] [--dest DIR]
    sleepy restore FILE [--config PATH]    (stop the service first!)
    sleepy check                     configuration / environment diagnostics
    sleepy healthcheck               exit code 0 if the running server is healthy
"""

from __future__ import annotations

import argparse
import getpass
import json
import secrets
import sys
import urllib.request
from pathlib import Path


def _pw(args) -> str:
    if args.password:
        return args.password
    if not sys.stdin.isatty():
        return sys.stdin.readline().strip()
    p1 = getpass.getpass("Passwort: ")
    p2 = getpass.getpass("Passwort wiederholen: ")
    if p1 != p2:
        sys.exit("Passwörter stimmen nicht überein")
    return p1


def cmd_init_db(args) -> None:
    from .db import init_db

    init_db()
    print("Datenbank ist auf dem aktuellen Stand.")


def cmd_create_user(args) -> None:
    from sqlalchemy import func, select

    from .db import init_db, session_scope
    from .models import User
    from .security import hash_password, validate_password_strength

    init_db()
    pw = args.password or (secrets.token_urlsafe(12) if args.generate else _pw(args))
    err = validate_password_strength(pw)
    if err:
        sys.exit(err)
    with session_scope() as db:
        if db.scalar(select(User).where(func.lower(User.username) == args.username.lower())):
            sys.exit(f"Benutzer {args.username} existiert bereits")
        db.add(User(username=args.username, password_hash=hash_password(pw), role="admin" if args.admin else "user"))
    print(f"Benutzer '{args.username}' angelegt ({'admin' if args.admin else 'user'}).")
    if args.generate:
        print(f"Generiertes Passwort: {pw}")


def cmd_reset_password(args) -> None:
    from sqlalchemy import delete, func, select

    from .db import init_db, session_scope
    from .models import AuthSession, User
    from .security import hash_password, validate_password_strength

    init_db()
    pw = args.password or (secrets.token_urlsafe(12) if args.generate else _pw(args))
    err = validate_password_strength(pw)
    if err:
        sys.exit(err)
    with session_scope() as db:
        u = db.scalar(select(User).where(func.lower(User.username) == args.username.lower()))
        if u is None:
            sys.exit("Benutzer nicht gefunden")
        u.password_hash = hash_password(pw)
        u.is_active = True
        if args.disable_totp:
            u.totp_enabled = False
            u.totp_secret = None
        db.execute(delete(AuthSession).where(AuthSession.user_id == u.id))
    print("Passwort gesetzt." + (f" Neues Passwort: {pw}" if args.generate else ""))


def cmd_list_users(args) -> None:
    from sqlalchemy import select

    from .db import init_db, session_scope
    from .models import User

    init_db()
    with session_scope() as db:
        for u in db.scalars(select(User).order_by(User.id)):
            print(f"{u.id:4d}  {u.username:24s} {u.role:6s} {'aktiv' if u.is_active else 'inaktiv'}  2FA={'ja' if u.totp_enabled else 'nein'}")


def _user(db, name: str | None):
    from sqlalchemy import func, select

    from .models import User

    if name:
        u = db.scalar(select(User).where(func.lower(User.username) == name.lower()))
    else:
        u = db.scalar(select(User).where(User.role == "admin").order_by(User.id))
    if u is None:
        sys.exit("Benutzer nicht gefunden (zuerst 'sleepy create-user NAME --admin')")
    return u


def cmd_import_dir(args) -> None:
    from .db import init_db, session_scope
    from .importer.pipeline import Runner, create_import
    from .logging_setup import setup_logging
    from .models import Import

    setup_logging()
    init_db()
    path = Path(args.path).resolve()
    if not path.is_dir():
        sys.exit(f"{path} ist kein Verzeichnis")
    with session_scope() as db:
        u = _user(db, args.user)
        imp = create_import(db, u, "server_dir", str(path), {"path": str(path)})
        imp_id = imp.id
    Runner(imp_id).run()
    with session_scope() as db:
        imp = db.get(Import, imp_id)
        print(f"Status: {imp.status}\n{imp.message}")
        if imp.error:
            print(f"Fehler: {imp.error}")
        sys.exit(0 if imp.status.startswith("completed") else 1)


def cmd_reprocess(args) -> None:
    from .db import init_db, session_scope
    from .importer.pipeline import Runner, create_import
    from .logging_setup import setup_logging
    from .models import Import

    setup_logging()
    init_db()
    with session_scope() as db:
        u = _user(db, args.user)
        imp = create_import(db, u, "reprocess", "Neuberechnung (CLI)", {})
        imp_id = imp.id
    Runner(imp_id, mode="reprocess").run()
    with session_scope() as db:
        imp = db.get(Import, imp_id)
        print(f"Status: {imp.status}\n{imp.message}")


def cmd_backup(args) -> None:
    from .backup import create_backup

    p = create_backup(Path(args.dest) if args.dest else None, include_raw=not args.no_raw)
    print(p)


def cmd_restore(args) -> None:
    from .backup import restore_backup

    res = restore_backup(Path(args.file), Path(args.config) if args.config else None)
    print(f"Wiederhergestellt: Backup vom {res['manifest']['created']}")
    print(f"Vorherige Daten gesichert in: {res['previous_data']}")


def cmd_check(args) -> None:
    import shutil

    from .config import get_settings
    from .importer.pipeline import disk_free

    st = get_settings()
    ok = True
    print(f"Datenverzeichnis: {st.data_dir}")
    for p in (st.data_dir, st.raw_dir, st.signals_dir, st.staging_dir, st.logs_dir, st.backups_dir):
        exists = p.exists()
        writable = exists and _writable(p)
        print(f"  {'OK ' if writable else 'FEHLER'} {p} {'(fehlt)' if not exists else '' if writable else '(nicht schreibbar)'}")
        ok &= writable
    print(f"Datenbank: {st.db_url.split('@')[-1]}")
    try:
        from sqlalchemy import text

        from .db import get_engine

        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        print("  OK  Verbindung")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"  FEHLER {exc}")
    free = disk_free(st.data_dir)
    print(f"Freier Speicher: {free / 1e9:.1f} GB")
    fe = st.frontend_path / "index.html"
    print(f"Frontend: {'OK' if fe.exists() else 'FEHLT'} ({fe})")
    if st.import_dir:
        print(f"Server-Import: {st.import_dir} ({'vorhanden' if Path(st.import_dir).is_dir() else 'FEHLT'})")
    print(f"Cookie secure: {st.cookie_secure}; vertrauenswürdige Proxies: {st.trusted_proxies}")
    if shutil.which("pg_dump") is None and st.db_url.startswith("postgres"):
        print("WARNUNG: pg_dump nicht gefunden (Backups mit PostgreSQL)")
    sys.exit(0 if ok else 1)


def _writable(p: Path) -> bool:
    try:
        t = p / ".write-test"
        t.write_text("x")
        t.unlink()
        return True
    except OSError:
        return False


def cmd_healthcheck(args) -> None:
    from .config import get_settings

    st = get_settings()
    host = "127.0.0.1" if st.host in ("0.0.0.0", "::") else st.host
    url = args.url or f"http://{host}:{st.port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
    except Exception as exc:  # noqa: BLE001
        print(f"UNHEALTHY: {exc}")
        sys.exit(1)
    print(json.dumps(data))
    sys.exit(0 if data.get("status") == "ok" else 1)


def cmd_serve(args) -> None:
    from .main import run

    run()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="sleepy", description="Sleepy CPAP-Datenanalyse – Verwaltung")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="Webserver starten").set_defaults(fn=cmd_serve)
    sub.add_parser("init-db", help="Datenbank anlegen/migrieren").set_defaults(fn=cmd_init_db)
    p = sub.add_parser("create-user", help="Benutzer anlegen")
    p.add_argument("username")
    p.add_argument("--admin", action="store_true")
    p.add_argument("--password")
    p.add_argument("--generate", action="store_true", help="zufälliges Passwort erzeugen und ausgeben")
    p.set_defaults(fn=cmd_create_user)
    p = sub.add_parser("reset-password", help="Passwort zurücksetzen")
    p.add_argument("username")
    p.add_argument("--password")
    p.add_argument("--generate", action="store_true")
    p.add_argument("--disable-totp", action="store_true")
    p.set_defaults(fn=cmd_reset_password)
    sub.add_parser("list-users").set_defaults(fn=cmd_list_users)
    p = sub.add_parser("import-dir", help="SD-Karten-Kopie aus Serververzeichnis importieren")
    p.add_argument("path")
    p.add_argument("--user")
    p.set_defaults(fn=cmd_import_dir)
    p = sub.add_parser("reprocess", help="Alle Nächte aus dem Rohdatenarchiv neu berechnen")
    p.add_argument("--user")
    p.set_defaults(fn=cmd_reprocess)
    p = sub.add_parser("backup", help="Backup erstellen")
    p.add_argument("--dest")
    p.add_argument("--no-raw", action="store_true")
    p.set_defaults(fn=cmd_backup)
    p = sub.add_parser("restore", help="Backup wiederherstellen (Dienst vorher stoppen!)")
    p.add_argument("file")
    p.add_argument("--config", help="Pfad, an den die gesicherte Konfiguration geschrieben wird")
    p.set_defaults(fn=cmd_restore)
    sub.add_parser("check", help="Konfiguration prüfen").set_defaults(fn=cmd_check)
    p = sub.add_parser("healthcheck", help="Laufenden Server prüfen")
    p.add_argument("--url")
    p.set_defaults(fn=cmd_healthcheck)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
