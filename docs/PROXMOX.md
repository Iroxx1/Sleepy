# Installation im Proxmox-LXC und Reverse Proxy

## 1. Container anlegen

Proxmox-Weboberfläche → *Create CT* (oder Shell):

```bash
pveam update && pveam available | grep debian-12      # bzw. debian-13
pveam download local debian-12-standard_12.7-1_amd64.tar.zst
pct create 120 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname sleepy --cores 2 --memory 2048 --swap 512 \
  --rootfs local-lvm:16 --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 --features nesting=1 --onboot 1
pct start 120 && pct enter 120
```

Empfehlung: 2 Kerne, 2 GB RAM, Speicher ≈ 2 × Größe der SD-Kartendaten + Reserve (ein Jahr ResMed ≈ 1–2 GB Rohdaten, gleiche Größenordnung für Signaldaten). Datenverzeichnis optional als separates Volume (Mountpoint `mp0` auf `/var/lib/sleepy`) – erleichtert Backups/Snapshots.

## 2. Sleepy installieren

```bash
apt-get update && apt-get install -y git
git clone <REPO-URL> /root/sleepy && cd /root/sleepy
./install.sh --admin admin          # druckt das generierte Admin-Passwort
```

Danach erreichbar unter `http://<LXC-IP>:8000`. Das Skript installiert Python-venv, baut das Frontend (Node.js wird bei Bedarf nach `/opt/sleepy/node` geladen und per SHA-256 geprüft), legt Benutzer `sleepy`, `/etc/sleepy/sleepy.env`, `/var/lib/sleepy`, den systemd-Dienst und einen täglichen Backup-Timer an.

Internet wird **nur bei der Installation/Updates** benötigt (Debian-Pakete, PyPI, npm). Zur Laufzeit lädt Sleepy nichts von außen.

## 3. Server-Importverzeichnis (optional)

```bash
echo "SLEEPY_IMPORT_DIR=/var/lib/sleepy/import" >> /etc/sleepy/sleepy.env
echo "SLEEPY_IMPORT_SCAN_INTERVAL_MINUTES=30" >> /etc/sleepy/sleepy.env   # 0 = nur per Button
mkdir -p /var/lib/sleepy/import && chown sleepy: /var/lib/sleepy/import
systemctl restart sleepy
```

SD-Karten-Inhalt z. B. per SMB/SCP/`pct push` in einen Unterordner legen. Bereits importierte Dateien werden am Hash erkannt; die Quelldateien werden nie verändert. Liegt das Verzeichnis außerhalb von `/var/lib/sleepy` (z. B. Bind-Mount `/srv/cpap-import`), in `/etc/systemd/system/sleepy.service` `ReadOnlyPaths=/srv/cpap-import` ergänzen.

## 4. Reverse Proxy

In `/etc/sleepy/sleepy.env`:

```
SLEEPY_TRUSTED_PROXIES=<IP des Proxys>    # damit X-Forwarded-For/-Proto übernommen werden
SLEEPY_COOKIE_SECURE=true                 # Cookies nur über HTTPS
```

Beispiele: [`deploy/nginx.conf`](../deploy/nginx.conf), [`deploy/Caddyfile`](../deploy/Caddyfile), [`deploy/traefik-dynamic.yml`](../deploy/traefik-dynamic.yml). Wichtig: große Uploads erlauben (`client_max_body_size 8g`, `proxy_request_buffering off`) und lange Timeouts. Sleepy unterstützt **keinen Unterpfad** (`/sleepy/`) – bitte eine eigene (Sub-)Domain oder einen eigenen Port verwenden.

## 5. Betrieb

| Aufgabe | Befehl |
|---|---|
| Status / Logs | `systemctl status sleepy` · `journalctl -u sleepy -f` · `/var/lib/sleepy/logs/sleepy.log` |
| Healthcheck | `/opt/sleepy/scripts/healthcheck.sh` (oder `GET /api/health`) |
| Update | `cd /root/sleepy && git pull && ./scripts/update.sh` |
| Backup | `./scripts/backup.sh [--no-raw] [--dest /mnt/nas]` – täglich automatisch via `sleepy-backup.timer` |
| Restore | `./scripts/restore.sh /var/lib/sleepy/backups/sleepy-backup-….tar.gz [--with-config]` |
| Diagnose | `./scripts/diagnose.sh > diagnose.txt` |
| Passwort vergessen | `runuser -u sleepy -- bash -c 'set -a; . /etc/sleepy/sleepy.env; /opt/sleepy/venv/bin/sleepy reset-password admin --generate --disable-totp'` |

Backups zusätzlich außerhalb des Containers ablegen (Proxmox-Backup des CT, NAS-Mount als `--dest`).
