#!/usr/bin/env bash
# Sammelt Diagnoseinformationen (keine Gesundheitsdaten, keine Passwörter).
#   sudo ./scripts/diagnose.sh > sleepy-diagnose.txt
. "$(dirname "$0")/common.sh"
echo "=== Sleepy Diagnose $(date -Is) ==="
echo "--- System"; uname -a; . /etc/os-release 2>/dev/null && echo "$PRETTY_NAME"
echo "--- Version"; cat "$APP_DIR/VERSION_COMMIT" 2>/dev/null || echo "(kein Commit-Info)"; "$VENV/bin/python" --version 2>&1 || true
echo "--- Dienst"; systemctl --no-pager status sleepy.service 2>&1 | head -15 || true
echo "--- Konfiguration (ohne Passwörter)"; grep -E '^SLEEPY_' "$ENV_FILE" 2>/dev/null | sed -E 's#(PASSWORD|DATABASE_URL)=.*#\1=***#' || true
echo "--- Prüfung"; sleepy_cli check || true
echo "--- Healthcheck"; "$(dirname "$0")/healthcheck.sh" || true
echo "--- Speicher"; df -h "$(data_dir)" 2>/dev/null; du -sh "$(data_dir)"/* 2>/dev/null || true
echo "--- Letzte Logeinträge"; journalctl -u sleepy.service -n 80 --no-pager 2>/dev/null || tail -n 80 "$(data_dir)/logs/sleepy.log" 2>/dev/null || true
