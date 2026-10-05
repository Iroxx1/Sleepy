#!/usr/bin/env bash
# Backup erstellen: sudo ./scripts/backup.sh [--no-raw] [--dest /pfad]
# Enthält Datenbank, Konfiguration, Originaldaten (raw/) und Analyse-/Signaldaten.
. "$(dirname "$0")/common.sh"
need_root
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --no-raw) ARGS+=(--no-raw); shift;;
    --dest) mkdir -p "$2"; chown "$SLEEPY_USER:$SLEEPY_USER" "$2"; ARGS+=(--dest "$2"); shift 2;;
    *) die "Unbekannte Option $1";;
  esac
done
info "Erstelle Backup"
OUT="$(sleepy_cli backup "${ARGS[@]}")"
ok "Backup: $OUT ($(du -h "$OUT" | cut -f1))"
