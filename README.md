# Sleepy – self-hosted CPAP-Datenanalyse

![Version](https://img.shields.io/badge/version-1.1.0-blue) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Self-hosted](https://img.shields.io/badge/self--hosted-100%25%20lokal-green)

Sleepy ist eine vollständig lokal laufende Webanwendung, die die SD-Karten-Daten von PAP-Geräten importiert, unverändert archiviert, normalisiert und – ähnlich SleepHQ/OSCAR – detailliert auswertet: Nachtanalyse mit hochaufgelöstem Flow, synchronisierten Diagrammen und Ereignisnavigation, Kalender, Langzeittrends, Vergleiche, Berichte und Export.

> **Hinweis:** Die dargestellten Informationen dienen ausschließlich der technischen Analyse der PAP-Therapiedaten und ersetzen keine ärztliche Beratung. Sleepy ist kein Medizinprodukt, stellt keine Diagnosen und gibt keine Therapieempfehlungen.

**Ablauf:** SD-Karte entnehmen → Inhalt als ZIP kopieren (oder Ordner wählen) → Weboberfläche → Import → fertig.

## Funktionsumfang

| Bereich | Inhalt |
|---|---|
| Import | ZIP-Upload (Streaming, mehrere GB), Ordner-Upload, Server-Importverzeichnis (manuell oder automatisch), Fortschrittsanzeige je Phase, Duplikaterkennung per SHA-256, Versionierung geänderter Dateien, Retry, Protokoll je Datei |
| Archiv | jede Originaldatei unverändert, schreibgeschützt, inhaltsadressiert; Herkunft jeder Nacht bis zur Rohdatei nachvollziehbar; Export der Originaldaten |
| Geräteerkennung | Hersteller, Modell, Produktcode, Seriennummer, Serie, Gerätetyp, Datenformat, vorhandene Kanäle, Einstellungsverlauf |
| Nachtanalyse | Nutzung, AHI/AI/HI/OAI/CAI/UAI/RERA/RDI, ODI (mit Oximeter), Leckage (Median/95 %/Max, Zeit über Schwelle), Druck/EPAP/IPAP (Median/95 %/Max), Flusslimitierung, Atemfrequenz, Atemzug-/Minutenvolumen, Schnarchen, SpO2/Puls – jeweils nur wenn vorhanden; Gerätewert **und** unabhängig berechneter Wert |
| Diagramme | Flow (25 Hz), Druck, Leckage mit Schwelle, Ereignisspuren, Flusslimitierung, Schnarchen, Atmung, SpO2/Puls, weitere Kanäle; **synchronisierter Zoom/Pan**, Mausrad-Zoom, Bereichsauswahl, gemeinsamer Cursor mit Tooltip, Übersichtsleiste, Nachladen in voller Auflösung beim Zoomen |
| Ereignisse | Liste mit Druck/Leck/FL zum Ereignis, Klick zoomt alle Diagramme, Cluster („Zwischen 02:15 und 02:40 …“), Ereignisse pro Stunde, ereignisbezogene Mittelung von Druck/Leck/FL |
| Auswertung | Kurz-Zusammenfassung der letzten 7 Tage auf der Startseite (max. 200 Zeichen), Zusammenfassungstext je Nacht, statistische Auffälligkeiten (robuste Abweichung vom persönlichen 30-Nächte-Median), Kalender mit Ampel (Schwellen einstellbar), Trends (7/30/90/180/365 Tage, alle, frei) mit Mittel/Median/Min/Max/Perzentilen/Std.-Abw./linearem Trend, Vergleich mehrerer Nächte inkl. Überlagerung, Suche (`ahi>5 event:CA 2026-09`) und Filter |
| Hardware | Gerät, Masken, Polster, Schläuche, Filter, Wasserkammer mit Startdatum; eigenes Austauschintervall mit Erinnerung im Dashboard; „Ersetzen“ mit einem Klick (z. B. jährliche neue Maske); Turbinen-/Laufzeitstunden als Ablesungen mit Verlauf, Ø Stunden/Tag und optionaler Hochrechnung; Therapiestunden seit Start aus den Daten; Vorher/Nachher-Vergleich (Leckage, AHI …); Wechsel als Markierung in den Trends |
| Darstellung | Hell/Dunkel/System (Mond-/Sonnen-Symbol oben rechts), eigenes CSS pro Benutzer und globales CSS (Admin) mit Beispielen und Variablenliste |
| Hilfe | „Hilfe & Legende“: alle Abkürzungen (AHI, CAI, RERA, EPR, P95 …) auf Deutsch, durchsuchbar; Tooltips an den Kennzahlen; Bedienung der Diagramme und Suchsyntax |
| Berichte & Export | Wochen-/Monats-/Zeitraumberichte als HTML, PDF, CSV, JSON; Export Nächte/Ereignisse (CSV, JSON, optional Parquet), Komplett-ZIP inkl. aller Zeitreihen, Originaldaten-ZIP |
| Sicherheit | Login (Argon2id), serverseitige Sessions, CSRF, Rate Limiting, optionale TOTP-2FA, mehrere Benutzer mit Datentrennung, Admin-Rolle, Audit-Log, CSP & Sicherheitsheader, keine Telemetrie/CDNs/Webfonts |
| Betrieb | `install.sh` für Debian-LXC, `update.sh`, Backup/Restore (inkl. täglichem Timer), Healthcheck, Diagnose, Logging, OpenAPI/Swagger offline, optional Docker/Podman |

**Unterstützte Geräte:** ResMed S9, AirSense/AirCurve 10, AirSense/AirCurve 11 (EDF/EDF+). Philips-Karten werden erkannt und archiviert, aber (noch) nicht ausgewertet. Details und offene Punkte: [docs/RESEARCH.md](docs/RESEARCH.md).

## Ehrlicher Stand / Einschränkungen

* Der ResMed-Parser wurde mit **synthetischen** Dateien entwickelt, die die dokumentierte Struktur nachbilden. Eine Prüfung mit einer echten SD-Karte steht aus – Anleitung: [docs/VALIDATION.md](docs/VALIDATION.md). Wichtigste offene Annahme: Lage der ResMed-Ereignismarkierung (Ende des Ereignisses).
* Nicht implementiert: eigene Ereigniserkennung aus dem Flow, Atemzug-für-Atemzug-Analyse, Import externer Oximeter/Wearables, Philips-/Löwenstein-Parser, Unterpfad-Betrieb hinter Reverse Proxy.
* ODI und Entsättigungen sind ein vereinfachter, nicht klinisch validierter Algorithmus.
* Firmware ist bei AirSense 10 nicht eindeutig aus den Dateien ablesbar und wird dann als „nicht ermittelbar“ angezeigt.

## Voraussetzungen

* Debian 12/13 (x86-64), z. B. als Proxmox-LXC; Python ≥ 3.11
* Zur Installation Internetzugang (Pakete); Node.js ≥ 20.19 wird bei Bedarf automatisch installiert
* Laufzeit: kein Internet nötig

## Installation

```bash
git clone <REPO-URL> sleepy && cd sleepy
sudo ./install.sh --admin admin        # Passwort wird generiert und ausgegeben
# → http://<LXC-IP>:8000
```

Ausführlich inkl. LXC-Erstellung und Reverse Proxy: [docs/PROXMOX.md](docs/PROXMOX.md). Container-Variante: `docker compose -f deploy/docker-compose.yml up -d --build`.

## Konfiguration

`/etc/sleepy/sleepy.env` (Vorlage: [.env.example](.env.example)). Wichtig:

| Variable | Standard | Bedeutung |
|---|---|---|
| `SLEEPY_DATA_DIR` | `/var/lib/sleepy` | Datenbank, Rohdatenarchiv, Signale, Backups, Logs |
| `SLEEPY_DATABASE_URL` | SQLite | z. B. `postgresql+psycopg://user:pw@host/sleepy` |
| `SLEEPY_PORT` / `SLEEPY_HOST` | `8000` / `0.0.0.0` | |
| `SLEEPY_TRUSTED_PROXIES` | `127.0.0.1` | Proxys, deren `X-Forwarded-*` vertraut wird |
| `SLEEPY_COOKIE_SECURE` | `auto` | `true` hinter HTTPS-Proxy |
| `SLEEPY_IMPORT_DIR` / `SLEEPY_IMPORT_SCAN_INTERVAL_MINUTES` | – / `0` | Server-Import |
| `SLEEPY_MAX_UPLOAD_MB` | `8192` | |
| `SLEEPY_LEAK_THRESHOLD` | `24` | Leckage-Schwelle (L/min) |
| `SLEEPY_SESSION_IDLE_MINUTES` / `SLEEPY_SESSION_MAX_DAYS` | `480` / `7` | Session-Timeout |

Nach Änderungen: `sudo systemctl restart sleepy`.

## Start, Update, Backup, Restore

```bash
sudo systemctl start|stop|restart|status sleepy
git pull && sudo ./scripts/update.sh                      # Backup → Code → Migration → Neustart → Healthcheck
sudo ./scripts/backup.sh [--no-raw] [--dest /mnt/nas]     # DB + Konfiguration + Originaldaten + Signale
sudo ./scripts/restore.sh <backup.tar.gz> [--with-config] # alte Daten werden nach pre-restore-*/ verschoben
```

Backups lassen sich auch unter *Einstellungen → System* erstellen und herunterladen. Ein täglicher Backup-Timer (03:30, 10 Versionen) ist aktiv.

## Import

1. *Import* → **ZIP-Datei auswählen** (Inhalt der SD-Karte, Unterordner im ZIP sind egal) oder **Ordner auswählen**.
2. Phasen: Upload → Prüfung → Erkennung → Archivierung → Parsing & Speicherung → Analyse → Fertig.
3. Ergebnis z. B. „14 neue Nächte importiert. 3 Dateien bereits vorhanden. 0 Fehler.“ – Details je Datei und Protokoll unter *Details*.

Einfach immer die komplette Karte importieren: bekannte Dateien werden erkannt, neue Versionen (z. B. `STR.edf`) versioniert, betroffene Nächte neu berechnet. Kommandozeile: `sleepy import-dir /pfad/zur/kopie`.

**Ohne eigene Daten ausprobieren:** *Import → „Beispieldaten laden (synthetisch)“* erzeugt 60 künstliche Nächte als eigenes „Demo-Gerät“ (Seriennummer `DEMO00000001`). Später unter *Geräte → Gerät löschen* (Seriennummer zur Bestätigung eingeben, optional inkl. Originaldateien) wieder vollständig entfernen – danach die echte SD-Karte importieren. Alternativ als ZIP: `./scripts/generate-demo-data.sh 30 demo.zip`.

## Architektur & API

* [ARCHITECTURE.md](ARCHITECTURE.md) – Komponenten, Datenschichten, Datenflüsse, Sicherheit
* [docs/API.md](docs/API.md) – REST-API; interaktiv unter `/api/docs` (Swagger, offline), Schema `/api/openapi.json` (nach Login)
* [docs/PARSERS.md](docs/PARSERS.md) – Parser-Architektur, neue Hersteller

```
parser/    cpap_parser – EDF/EDF+, ResMed-Parser, Testdaten-Generator
backend/   sleepy – FastAPI, Datenmodell, Import, Analyse, Reports, CLI
frontend/  React/TypeScript/Vite/ECharts
tests/     pytest (Parser, Import, Duplikate, DB, API, Auth, Charts, Statistik, Backup)
scripts/   install/update/backup/restore/healthcheck/diagnose/dev
deploy/    systemd, Nginx/Caddy/Traefik, Docker
docs/      Recherche, Validierung, Proxmox, API, Parser
```

## Entwicklung

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
./scripts/dev.sh                 # Backend :8000 mit Reload + Vite :5173
pytest                           # Backend-/Parser-Tests
ruff check parser backend tests
cd frontend && npm ci && npm test && npm run build
```

Datenbankschema ändern: Modell in `backend/sleepy/models.py` anpassen, dann

```bash
python -c "from alembic import command; from sleepy.db import get_engine; from sleepy.migrations import alembic_config; command.revision(alembic_config(get_engine()), message='…', autogenerate=True)"
```

Keine echten Gesundheitsdaten einchecken – Tests verwenden ausschließlich synthetische Daten.

## Troubleshooting

| Problem | Lösung |
|---|---|
| Seite nicht erreichbar | `systemctl status sleepy`, `journalctl -u sleepy -n 100`, `./scripts/healthcheck.sh` |
| „Frontend wurde noch nicht gebaut“ | `./scripts/update.sh` (baut das Frontend) |
| Login klappt hinter HTTPS-Proxy nicht / sofort abgemeldet | `SLEEPY_TRUSTED_PROXIES` auf Proxy-IP, `SLEEPY_COOKIE_SECURE=true`, Proxy muss `Host` und `X-Forwarded-Proto` setzen |
| „Ungültiger Origin“ (403) | Proxy setzt falschen `Host`-Header – `proxy_set_header Host $host;` bzw. `SLEEPY_ALLOWED_ORIGINS` |
| Upload bricht bei großen ZIPs ab | Proxy: `client_max_body_size`, Timeouts; `SLEEPY_MAX_UPLOAD_MB`; freien Speicher prüfen |
| „Keine bekannten CPAP-Daten erkannt“ | ZIP muss `STR.edf`/`Identification.*`/`DATALOG/` enthalten (nicht nur einen Unterordner) |
| Werte wirken falsch | Abgleich nach [docs/VALIDATION.md](docs/VALIDATION.md); nach Parser-Fix *Einstellungen → System → Alle Nächte neu berechnen* |
| Passwort vergessen | siehe [docs/PROXMOX.md](docs/PROXMOX.md#5-betrieb) (`sleepy reset-password`) |
| Zu viele Login-Versuche (429) | 15 Minuten warten oder Dienst neu starten |
| Diagnose für Support | `sudo ./scripts/diagnose.sh > diagnose.txt` (enthält keine Gesundheitsdaten) |

## Lizenz

Noch keine Lizenz festgelegt (bitte durch den Projektinhaber ergänzen). Sleepy enthält keinen Code aus OSCAR (GPL-3.0); OSCAR wurde ausschließlich als technische Referenz für das Dateiformat genutzt.
