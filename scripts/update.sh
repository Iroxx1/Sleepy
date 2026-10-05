#!/usr/bin/env bash
# Sleepy aktualisieren: im Quellverzeichnis (git pull) ausführen:
#   git pull && sudo ./scripts/update.sh
# Ablauf: Sicherheits-Backup (ohne Originaldaten) -> Code kopieren -> Abhängigkeiten
# -> Frontend bauen -> Datenbank migrieren -> Neustart -> Healthcheck.
. "$(dirname "$0")/common.sh"
need_root
[ -f "$ENV_FILE" ] || die "Keine Installation gefunden ($ENV_FILE fehlt) – zuerst install.sh ausführen."

info "Sicherheits-Backup der Datenbank"
sleepy_cli backup --no-raw | sed 's/^/    /' || warn "Backup fehlgeschlagen – Update wird trotzdem fortgesetzt"

svc stop sleepy.service || true
sync_app
install_python
build_frontend
chown -R root:root "$PREFIX"; chmod -R go-w "$PREFIX"
install -m 644 "$APP_DIR/deploy/sleepy.service" /etc/systemd/system/sleepy.service.new
if ! cmp -s /etc/systemd/system/sleepy.service.new /etc/systemd/system/sleepy.service; then
  warn "Neue Version der systemd-Unit unter /etc/systemd/system/sleepy.service.new – bitte bei Bedarf übernehmen."
else
  rm -f /etc/systemd/system/sleepy.service.new
fi
info "Datenbank-Migration"
sleepy_cli init-db
svc daemon-reload
svc start sleepy.service
wait_healthy
ok "Update abgeschlossen. Hinweis: Nach Parser-Updates können alle Nächte unter Einstellungen → System neu berechnet werden."
