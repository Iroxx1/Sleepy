# Architektur

## Überblick

```
 Browser (React/TypeScript, ECharts)            Proxmox-LXC (Debian)
 ┌──────────────────────────────┐   HTTPS   ┌────────────────────────────────────────────────────────┐
 │ Dashboard · Nächte · Kalender│◀────────▶ │ Reverse Proxy (optional: Nginx/Caddy/Traefik)          │
 │ Trends · Vergleich · Import  │           │        │                                               │
 │ Reports · Einstellungen      │           │        ▼                                               │
 └──────────────────────────────┘           │ uvicorn + FastAPI  (sleepy.main)  :8000                │
                                            │  ├─ /api/auth      Sessions, Argon2, CSRF, TOTP        │
                                            │  ├─ /api/imports   Upload → Import-Worker (Thread)     │
                                            │  ├─ /api/nights    Detail, Events, Zeitreihen, Analyse │
                                            │  ├─ /api/statistics, /api/dashboard, /api/reports      │
                                            │  ├─ /api/export    CSV/JSON/ZIP/Parquet, Originaldaten │
                                            │  └─ statisches Frontend (frontend/dist)                │
                                            │                                                        │
                                            │ cpap_parser  (EDF/EDF+, ResMed, Registry)               │
                                            │                                                        │
                                            │ /var/lib/sleepy                                        │
                                            │  ├─ raw/      Originaldateien (SHA-256, schreibgeschützt)│
                                            │  ├─ signals/  normalisierte Signale (.npy, int16)       │
                                            │  ├─ db/       SQLite (oder PostgreSQL extern)           │
                                            │  ├─ staging/  Upload-Zwischenablage                     │
                                            │  ├─ backups/  logs/  exports/  tmp/                     │
                                            └────────────────────────────────────────────────────────┘
```

**Technologie-Entscheidung:** Python/FastAPI (Typisierung, OpenAPI automatisch, NumPy für die Signalverarbeitung), SQLAlchemy 2 + Alembic (SQLite als Standard, PostgreSQL optional), React + TypeScript + Vite im Frontend, Apache ECharts für alle Diagramme (Zeitachsen, Custom-Series für Ereignisspuren, Kalender, Verbindung mehrerer Charts für gemeinsamen Cursor). Pandas/SciPy werden nicht benötigt – NumPy reicht für Perzentile, Downsampling und Statistik; Pandas/PyArrow sind nur optional für den Parquet-Export. Kein Docker-Zwang, keine externen Dienste, keine CDNs, keine Webfonts.

## Datenschichten

| Schicht | Speicherort | Inhalt | Neu erzeugbar aus |
|---|---|---|---|
| 1. Originaldaten | `raw/` + Tabelle `raw_files` | unveränderte Bytes jeder hochgeladenen Datei, inhaltsadressiert (SHA-256), Rechte 0440 | – (Quelle der Wahrheit) |
| 2. Importierte Rohdaten | `imports`, `import_files`, `device_files` | wer hat wann welche Datei geliefert, Status je Datei (neu / neue Version / Duplikat / ignoriert / Fehler), Versionsgeschichte je Kartenpfad | 1 + Importprotokoll |
| 3. Normalisierte Daten | `nights`, `therapy_sessions`, `events`, `signal_segments` + `signals/*.npy`, `night_source_files` | Nächte, Masken-Sitzungen, Ereignisse (Rohzeitpunkt + Interpretation), Signale als int16 mit Skalierung | 1 (Parser) |
| 4. Aggregate | `night_metrics` (Quelle `device` oder `computed`) | AHI & Co., Perzentile je Kanal, Leckzeit, ODI … | 3 |
| 5. Analyse | on demand (`analysis/insights.py`, `stats.py`, Reports) | Zusammenfassungstext, Cluster, Auffälligkeiten, Trends | 3 + 4 |

Weil Schicht 1 vollständig erhalten bleibt, kann nach jeder Parser-Verbesserung „Alle Nächte neu berechnen“ ausgeführt werden (Einstellungen → System oder `sleepy reprocess`), ohne dass die SD-Karte erneut hochgeladen werden muss.

## Datenmodell (Kurzfassung)

* `users` (Argon2id-Hash, Rolle, TOTP, Präferenzen) · `auth_sessions` (gehashter Token, CSRF-Token, Ablauf) · `audit_log`
* `devices` (Besitzer, Hersteller, Modell, Produktcode, Seriennummer, Firmware, Typ, Rohidentifikation) – eindeutig je (Besitzer, Hersteller, Seriennummer)
* `raw_files` (sha256, Größe, Archivpfad) · `imports` (Quelle, Status, Phase, Fortschritt, Statistik, Protokoll) · `import_files` · `device_files`
* `nights` (Gerät, Therapietag, Start/Ende, Nutzungsdauer, Einstellungen, Tageszusammenfassung roh, Masken-Intervalle, Kanäle, Warnungen, Notizen)
* `therapy_sessions` · `signal_segments` (Kanal, Label, Einheit, Abtastrate, Start, Samples, gain/offset, Ungültig-Wert, Min/Max/Mittel, Datei, Quelldatei) · `events` (Code, Originaltext, Roh-Onset, Start, Ende, Dauer, Quelldatei)
* `hardware_items` (Kategorie, Bezeichnung, Hersteller/Modell/Größe/Seriennr., Startdatum, Enddatum, Austauschintervall, erwartete Laufzeit, optional verknüpftes Gerät) · `hardware_readings` (Datum, Art z. B. Turbinenstunden, Wert)
* `app_settings` (u. a. globales CSS); persönliches CSS in den Benutzerpräferenzen
* `night_metrics` (Schlüssel, Wert, Quelle) – Schlüsselschema `ahi`, `count.OA`, `<kanal>.<statistik>` (z. B. `leak.p95`)

Zeitstempel sind „Wall-Clock-Millisekunden“: die lokale Gerätezeit, als UTC kodiert. Das Frontend formatiert konsequent in UTC und zeigt so exakt die Gerätezeit (Sommer-/Winterzeitwechsel werden nicht umgerechnet).

## Importablauf

```
Upload (ZIP-Stream / Ordner in Batches / Serververzeichnis)
  → Prüfung      sichere ZIP-Extraktion (Zip-Slip, Symlinks, Zip-Bomben, Größenlimits), Systemdateien ignorieren
  → Erkennung    Parser.find_roots() je Hersteller → Karten-Wurzel(n); detect(); identify() → Gerät anlegen/aktualisieren
  → Archivierung SHA-256 → raw/ (einmalig je Inhalt) → device_files-Version: neu / neue Version / Duplikat
  → Parsing      betroffene Nächte bestimmen (geänderte Dateien, neue Nächte, geänderte Tageszusammenfassung)
                 je Nacht: parse_night → Kennzahlen → Signale in neue Generation schreiben → DB in einer Transaktion ersetzen
  → Analyse      Statistik/Status on demand
```

* Fehler in einer Nacht brechen den Import nicht ab („abgeschlossen mit Fehlern“, Protokoll nennt Nacht und Dateien).
* Bei Fehlern bleibt der vorherige Stand einer Nacht unverändert (neue Signale in neuer Generation, alte erst nach Commit gelöscht).
* Imports laufen nacheinander in einem Hintergrund-Thread; der Fortschritt wird in der DB gespeichert und vom Frontend abgefragt. Nach einem Neustart werden unterbrochene Imports als fehlgeschlagen markiert und können wiederholt werden.

## Diagrammdaten / Performance

* Einmaliges Parsen beim Import; danach nur noch `.npy`-Dateien per Memory-Mapping lesen.
* `GET /api/nights/{id}/timeseries?channels=…&start=…&end=…&points=…` liefert für das sichtbare Zeitfenster höchstens `points` Punkte: Min/Max-Hüllkurve je Bucket (Spitzen gehen nie verloren). Beim Hineinzoomen werden automatisch die Rohsamples (25 Hz) geladen.
* Langzeit-Diagramme nutzen ausschließlich `night_metrics` (Tageswerte; ab 190 Tagen Wochen-, ab 400 Tagen Monatsaggregation).
* Indizes auf Nacht/Datum, Ereignis (Nacht, Start), Metrik (Schlüssel, Wert).

## Sicherheit

Argon2id-Passwörter, serverseitige Sessions (nur Hash des Tokens in der DB), Cookies `HttpOnly`, `SameSite=Strict`, `Secure` bei HTTPS, Idle- und Maximal-Timeout, CSRF-Token (Double Submit über Header) plus Origin-Prüfung, Login-Rate-Limit, optionale TOTP-2FA, strikte CSP (`default-src 'self'`), `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, Audit-Log, Datentrennung je Benutzer, keine Telemetrie, keine externen Ressourcen. systemd-Unit mit `ProtectSystem=strict` u. a.

## Erweiterbarkeit

Weitere Hersteller → neues Parser-Modul ([docs/PARSERS.md](docs/PARSERS.md)). Weitere Datenquellen (Oximeter, Wearables) passen in dasselbe Modell (`ParsedNight` mit eigenen Kanälen `spo2`, `pulse`, …). Automatische Importüberwachung existiert bereits für ein Serververzeichnis (`SLEEPY_IMPORT_SCAN_INTERVAL_MINUTES`).
