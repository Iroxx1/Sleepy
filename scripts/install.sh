#!/usr/bin/env bash
# Sleepy – Installation auf Debian 12/13 (z. B. Proxmox-LXC).
#   sudo ./install.sh                 interaktiv
#   sudo ./install.sh --admin NAME    Admin-Benutzer anlegen (Passwort wird generiert)
#   Optionen: --port 8000  --data-dir /var/lib/sleepy  --import-dir /var/lib/sleepy/import  --no-start
. "$(dirname "$0")/common.sh"

ADMIN=""; PORT=""; DATA=""; IMPORT=""; START=1
while [ $# -gt 0 ]; do
  case "$1" in
    --admin) ADMIN="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --data-dir) DATA="$2"; shift 2;;
    --import-dir) IMPORT="$2"; shift 2;;
    --no-start) START=0; shift;;
    -h|--help) sed -n '2,6p' "$0"; exit 0;;
    *) die "Unbekannte Option $1";;
  esac
done

need_root
. /etc/os-release 2>/dev/null || true
[ "${ID:-}" = "debian" ] || [[ "${ID_LIKE:-}" == *debian* ]] || warn "Getestet für Debian 12/13 – erkannt: ${PRETTY_NAME:-unbekannt}"

info "Installiere Systempakete"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl ca-certificates rsync xz-utils tar sqlite3 >/dev/null
PYV="$(python3 -c 'import sys; print(sys.version_info >= (3, 11))')"
[ "$PYV" = "True" ] || die "Python 3.11 oder neuer erforderlich (Debian 12+)."
ok "Systempakete installiert"

if ! id "$SLEEPY_USER" >/dev/null 2>&1; then
  info "Lege Systembenutzer $SLEEPY_USER an"
  useradd --system --home-dir "${DATA:-$DATA_DIR_DEFAULT}" --shell /usr/sbin/nologin "$SLEEPY_USER"
fi

mkdir -p "$CONF_DIR"
if [ ! -f "$ENV_FILE" ]; then
  info "Erzeuge Konfiguration $ENV_FILE"
  cp "$SRC_DIR/.env.example" "$ENV_FILE"
  [ -n "$DATA" ] && sed -i "s#^SLEEPY_DATA_DIR=.*#SLEEPY_DATA_DIR=$DATA#" "$ENV_FILE"
  [ -n "$PORT" ] && sed -i "s#^SLEEPY_PORT=.*#SLEEPY_PORT=$PORT#" "$ENV_FILE"
  if [ -n "$IMPORT" ]; then echo "SLEEPY_IMPORT_DIR=$IMPORT" >> "$ENV_FILE"; fi
else
  ok "Konfiguration vorhanden ($ENV_FILE) – wird nicht verändert"
fi
chown root:"$SLEEPY_USER" "$CONF_DIR" "$ENV_FILE"; chmod 750 "$CONF_DIR"; chmod 640 "$ENV_FILE"

DD="$(data_dir)"
info "Datenverzeichnis $DD"
mkdir -p "$DD"/{db,raw,signals,staging,logs,backups,exports,tmp}
IMP="$(grep -E '^SLEEPY_IMPORT_DIR=' "$ENV_FILE" | cut -d= -f2- || true)"
[ -n "$IMP" ] && mkdir -p "$IMP" && chown "$SLEEPY_USER:$SLEEPY_USER" "$IMP"
chown -R "$SLEEPY_USER:$SLEEPY_USER" "$DD"; chmod 750 "$DD"

sync_app
install_python
build_frontend
chown -R root:root "$PREFIX"; chmod -R go-w "$PREFIX"

info "Initialisiere Datenbank"
sleepy_cli init-db

if ! sleepy_cli list-users | grep -q .; then
  if [ -z "$ADMIN" ] && [ -t 0 ]; then read -r -p "Benutzername des Administrators [admin]: " ADMIN; fi
  ADMIN="${ADMIN:-admin}"
  info "Lege Administrator '$ADMIN' an"
  sleepy_cli create-user "$ADMIN" --admin --generate | sed 's/^/    /'
  warn "Bitte das generierte Passwort notieren und nach dem ersten Login ändern."
fi

info "Installiere systemd-Dienst"
install -m 644 "$APP_DIR/deploy/sleepy.service" /etc/systemd/system/sleepy.service
install -m 644 "$APP_DIR/deploy/sleepy-backup.service" /etc/systemd/system/sleepy-backup.service
install -m 644 "$APP_DIR/deploy/sleepy-backup.timer" /etc/systemd/system/sleepy-backup.timer
if [ "$DD" != "$DATA_DIR_DEFAULT" ]; then
  sed -i "s#/var/lib/sleepy#$DD#g" /etc/systemd/system/sleepy.service /etc/systemd/system/sleepy-backup.service
fi
if [ -n "$IMP" ] && [[ "$IMP" != "$DD"* ]]; then
  sed -i "s|^# ReadOnlyPaths=.*|ReadWritePaths=$IMP|" /etc/systemd/system/sleepy.service
fi
svc daemon-reload
svc enable sleepy.service sleepy-backup.timer >/dev/null

if [ "$START" = "1" ]; then
  if has_systemd; then
    svc restart sleepy.service sleepy-backup.timer
    wait_healthy || true
  else
    warn "Ohne systemd bitte manuell starten: runuser -u $SLEEPY_USER -- bash -c 'set -a; . $ENV_FILE; exec $VENV/bin/sleepy serve'"
  fi
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
PORT_EFF="$(grep -E '^SLEEPY_PORT=' "$ENV_FILE" | cut -d= -f2)"
echo
ok "Sleepy ist installiert: http://${IP:-<LXC-IP>}:${PORT_EFF:-8000}"
echo "    Konfiguration: $ENV_FILE   Daten: $DD"
echo "    Logs: journalctl -u sleepy -f   Diagnose: $APP_DIR/scripts/diagnose.sh"
