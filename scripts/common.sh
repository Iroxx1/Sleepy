# shellcheck shell=bash
# Gemeinsame Einstellungen der Sleepy-Verwaltungsskripte.
set -euo pipefail

SLEEPY_USER="${SLEEPY_USER:-sleepy}"
PREFIX="${SLEEPY_PREFIX:-/opt/sleepy}"
APP_DIR="$PREFIX/app"
VENV="$PREFIX/venv"
NODE_DIR="$PREFIX/node"
CONF_DIR="${SLEEPY_CONF_DIR:-/etc/sleepy}"
ENV_FILE="$CONF_DIR/sleepy.env"
DATA_DIR_DEFAULT="/var/lib/sleepy"
SERVICE="sleepy"
NODE_VERSION="${SLEEPY_NODE_VERSION:-22.20.0}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m ✓\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m !\033[0m %s\n' "$*" >&2; }
die()   { printf '\033[1;31m ✗ %s\033[0m\n' "$*" >&2; exit 1; }

has_systemd() { [ -d /run/systemd/system ]; }

svc() {
  if has_systemd; then systemctl "$@"; else warn "systemd läuft nicht – übersprungen: systemctl $*"; fi
}

need_root() { [ "$(id -u)" -eq 0 ] || die "Bitte als root ausführen (z. B. mit sudo)."; }

data_dir() {
  local d=""
  if [ -f "$ENV_FILE" ]; then d="$(grep -E '^SLEEPY_DATA_DIR=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"; fi
  echo "${d:-$DATA_DIR_DEFAULT}"
}

# Run a sleepy CLI command as the service user with the service environment.
sleepy_cli() {
  local dd; dd="$(data_dir)"
  mkdir -p "$dd/tmp" && chown "$SLEEPY_USER:$SLEEPY_USER" "$dd/tmp"
  runuser -u "$SLEEPY_USER" -- env -i PATH="$VENV/bin:/usr/bin:/bin" HOME="$dd" TMPDIR="$dd/tmp" \
    bash -c "set -a; . '$ENV_FILE'; set +a; exec '$VENV/bin/sleepy' \"\$@\"" sleepy "$@"
}

node_ok() {
  command -v node >/dev/null 2>&1 || return 1
  node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit((a===20&&b>=19)||a>=22?0:1)'
}

ensure_node() {
  if node_ok; then ok "Node.js $(node -v) vorhanden"; return; fi
  if [ -x "$NODE_DIR/bin/node" ]; then export PATH="$NODE_DIR/bin:$PATH"; node_ok && { ok "Node.js $(node -v) ($NODE_DIR)"; return; }; fi
  info "Installiere Node.js $NODE_VERSION nach $NODE_DIR (nur für den Frontend-Build)"
  local arch tmp base
  case "$(uname -m)" in x86_64) arch=x64 ;; aarch64) arch=arm64 ;; *) die "Nicht unterstützte Architektur $(uname -m)";; esac
  tmp="$(mktemp -d)"; base="node-v$NODE_VERSION-linux-$arch"
  curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/$base.tar.xz" -o "$tmp/$base.tar.xz"
  curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/SHASUMS256.txt" -o "$tmp/SHASUMS256.txt"
  (cd "$tmp" && grep " $base.tar.xz\$" SHASUMS256.txt | sha256sum -c -) || die "Prüfsumme von Node.js stimmt nicht"
  rm -rf "$NODE_DIR"; mkdir -p "$NODE_DIR"
  tar -xJf "$tmp/$base.tar.xz" -C "$NODE_DIR" --strip-components=1
  rm -rf "$tmp"
  export PATH="$NODE_DIR/bin:$PATH"
  ok "Node.js $(node -v) installiert"
}

sync_app() {
  info "Kopiere Anwendung nach $APP_DIR"
  mkdir -p "$APP_DIR"
  rsync -a --delete \
    --exclude '.git' --exclude '.venv' --exclude 'node_modules' --exclude 'frontend/dist' \
    --exclude '__pycache__' --exclude '.pytest_cache' --exclude '.ruff_cache' \
    "$SRC_DIR/" "$APP_DIR/"
  if [ -d "$SRC_DIR/.git" ]; then
    (cd "$SRC_DIR" && git rev-parse --short HEAD 2>/dev/null || true) > "$APP_DIR/VERSION_COMMIT"
  fi
}

install_python() {
  info "Python-Umgebung $VENV"
  [ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip wheel
  "$VENV/bin/pip" install --quiet "$APP_DIR/parser" "$APP_DIR/backend"
  if grep -qE '^SLEEPY_DATABASE_URL=postgres' "$ENV_FILE" 2>/dev/null; then
    "$VENV/bin/pip" install --quiet "psycopg[binary]>=3.1"
  fi
  ok "Python-Pakete installiert ($("$VENV/bin/python" --version))"
}

build_frontend() {
  if [ -f "$SRC_DIR/frontend/dist/index.html" ] && [ "${SLEEPY_PREBUILT_FRONTEND:-0}" = "1" ]; then
    info "Verwende vorgebautes Frontend"
    rsync -a --delete "$SRC_DIR/frontend/dist/" "$APP_DIR/frontend/dist/"
    return
  fi
  ensure_node
  info "Baue Frontend"
  (cd "$APP_DIR/frontend" && npm ci --no-audit --no-fund --loglevel=error && npm run build --silent)
  rm -rf "$APP_DIR/frontend/node_modules"
  [ -f "$APP_DIR/frontend/dist/index.html" ] || die "Frontend-Build fehlgeschlagen"
  ok "Frontend gebaut"
}

wait_healthy() {
  local port url i
  port="$(grep -E '^SLEEPY_PORT=' "$ENV_FILE" | cut -d= -f2 || true)"; port="${port:-8000}"
  url="http://127.0.0.1:$port/api/health"
  for i in $(seq 1 30); do
    if curl -fsS "$url" >/dev/null 2>&1; then ok "Healthcheck OK ($url)"; return 0; fi
    sleep 1
  done
  warn "Healthcheck fehlgeschlagen – siehe: journalctl -u $SERVICE -n 100"
  return 1
}
