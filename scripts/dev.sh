#!/usr/bin/env bash
# Entwicklungsmodus: Backend (Port 8000) + Vite-Dev-Server (Port 5173, Proxy auf /api).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -e ./parser -e "./backend[dev]"
export SLEEPY_DATA_DIR="${SLEEPY_DATA_DIR:-$ROOT/data}" SLEEPY_LOG_LEVEL=DEBUG
mkdir -p "$SLEEPY_DATA_DIR"
uvicorn --factory sleepy.main:create_app --reload --reload-dir backend --reload-dir parser --port 8000 &
BACK=$!
trap 'kill $BACK' EXIT
cd frontend && npm install --no-audit --no-fund && npm run dev
