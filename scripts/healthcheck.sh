#!/usr/bin/env bash
# Healthcheck für Monitoring (Exit-Code 0 = gesund): ./scripts/healthcheck.sh [URL]
URL="${1:-http://127.0.0.1:${SLEEPY_PORT:-8000}/api/health}"
OUT="$(curl -fsS --max-time 5 "$URL")" || { echo "UNHEALTHY: keine Antwort von $URL"; exit 2; }
echo "$OUT"
echo "$OUT" | grep -q '"status":"ok"' || exit 1
