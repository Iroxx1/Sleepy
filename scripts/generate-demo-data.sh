#!/usr/bin/env bash
# Erzeugt eine SYNTHETISCHE ResMed-SD-Karte als ZIP zum Ausprobieren (keine echten Daten!).
#   ./scripts/generate-demo-data.sh [Nächte=30] [Ziel=demo-sdcard.zip] [--oximetry]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
N="${1:-30}"; OUT="${2:-demo-sdcard.zip}"; shift $(( $# > 2 ? 2 : $# )) || true
PY="${PYTHON:-python3}"; [ -x "$ROOT/.venv/bin/python" ] && PY="$ROOT/.venv/bin/python"
[ -x /opt/sleepy/venv/bin/python ] && [ ! -x "$ROOT/.venv/bin/python" ] && PY=/opt/sleepy/venv/bin/python
TMP="$(mktemp -d)"
PYTHONPATH="$ROOT/parser" "$PY" -m cpap_parser.testing.synthetic_resmed "$TMP/SD" --nights "$N" "$@"
"$PY" - "$TMP/SD" "$OUT" <<'PYEOF'
import sys, zipfile, pathlib
root, out = pathlib.Path(sys.argv[1]), sys.argv[2]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(root.rglob("*")):
        if p.is_file():
            z.write(p, p.relative_to(root).as_posix())
print(f"Synthetische Demo-Daten: {out}")
PYEOF
rm -rf "$TMP"
