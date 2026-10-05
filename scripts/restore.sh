#!/usr/bin/env bash
# Backup wiederherstellen: sudo ./scripts/restore.sh /var/lib/sleepy/backups/sleepy-backup-....tar.gz [--with-config]
# Der Dienst wird dafür gestoppt. Vorhandene Daten werden NICHT gelöscht, sondern nach
# <Datenverzeichnis>/pre-restore-<Zeitstempel>/ verschoben.
. "$(dirname "$0")/common.sh"
need_root
FILE="${1:-}"; [ -n "$FILE" ] && [ -f "$FILE" ] || die "Aufruf: $0 <backup.tar.gz> [--with-config]"
WITH_CONFIG="${2:-}"
FILE="$(readlink -f "$FILE")"
DD="$(data_dir)"
read -r -p "Daten aus $FILE wiederherstellen? Der Dienst wird kurz gestoppt. [j/N] " a
[[ "$a" =~ ^[jJyY]$ ]] || die "Abgebrochen"
svc stop sleepy.service || true
# make the archive readable for the service user
TMPF="$DD/tmp/restore-$(date +%s).tar.gz"; cp "$FILE" "$TMPF"; chown "$SLEEPY_USER:$SLEEPY_USER" "$TMPF"
if [ "$WITH_CONFIG" = "--with-config" ]; then
  CFG_TMP="$DD/tmp/restored.env"
  sleepy_cli restore "$TMPF" --config "$CFG_TMP"
  if [ -f "$CFG_TMP" ]; then cp "$ENV_FILE" "$ENV_FILE.bak-$(date +%s)"; install -m 640 -o root -g "$SLEEPY_USER" "$CFG_TMP" "$ENV_FILE"; rm -f "$CFG_TMP"; fi
else
  sleepy_cli restore "$TMPF"
fi
rm -f "$TMPF"
chown -R "$SLEEPY_USER:$SLEEPY_USER" "$DD"
sleepy_cli init-db
svc start sleepy.service
wait_healthy
ok "Wiederherstellung abgeschlossen."
