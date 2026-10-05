# REST-API

Interaktive Dokumentation (Swagger UI, ohne CDN): `/api/docs` · Schema: `/api/openapi.json` (beide nach Login).

## Authentifizierung

Sleepy verwendet serverseitige Sessions per Cookie (`sleepy_session`, HttpOnly). Schreibende Anfragen (POST/PUT/PATCH/DELETE) benötigen zusätzlich den Header `X-CSRF-Token` mit dem Wert des Cookies `sleepy_csrf` (bzw. `csrf_token` aus `/api/auth/me`).

```bash
B=http://lxc:8000
curl -c jar -H 'Content-Type: application/json' -d '{"username":"admin","password":"…"}' $B/api/auth/login
CSRF=$(awk '$6=="sleepy_csrf"{print $7}' jar)
curl -b jar $B/api/nights?q=ahi%3E5
# ZIP importieren
ID=$(curl -s -b jar -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' -d '{"source":"zip"}' $B/api/imports | jq -r .id)
curl -b jar -H "X-CSRF-Token: $CSRF" -T CPAP_SD.zip "$B/api/imports/$ID/upload?filename=CPAP_SD.zip"
curl -b jar -H "X-CSRF-Token: $CSRF" -X POST $B/api/imports/$ID/start
curl -b jar $B/api/imports/$ID      # Status/Fortschritt
```

Zeitstempel (`*_ms`) sind Gerätezeit als „Wall-Clock-Millisekunden“ (lokale Zeit als UTC kodiert).

## Endpunkte

| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/api/auth/setup-status` | Setup Status |
| POST | `/api/auth/setup` | Create the first administrator.  Only possible while no user exists. |
| POST | `/api/auth/login` | Login |
| POST | `/api/auth/totp/verify` | Totp Verify |
| POST | `/api/auth/logout` | Logout |
| GET | `/api/auth/me` | Me |
| POST | `/api/auth/password` | Change Password |
| POST | `/api/auth/totp/setup` | Totp Setup |
| POST | `/api/auth/totp/enable` | Totp Enable |
| POST | `/api/auth/totp/disable` | Totp Disable |
| GET | `/api/auth/preferences` | Get Preferences |
| PUT | `/api/auth/preferences` | Put Preferences |
| GET | `/api/imports` | List Imports |
| POST | `/api/imports` | Create |
| POST | `/api/imports/demo` | Generate and import a SYNTHETIC ResMed card (device serial DEMO00000001). |
| PUT | `/api/imports/{import_id}/upload` | Stream a ZIP file as raw request body (supports multi-GB uploads). |
| POST | `/api/imports/{import_id}/files` | Upload a batch of files of a folder (relative paths in *paths*). |
| GET | `/api/imports/{import_id}/files` | Import Files |
| POST | `/api/imports/{import_id}/start` | Start |
| GET | `/api/imports/server-info` | Server Info |
| POST | `/api/imports/server-scan` | Server Scan |
| GET | `/api/imports/{import_id}` | Get Import |
| DELETE | `/api/imports/{import_id}` | Delete Draft |
| POST | `/api/imports/{import_id}/retry` | Retry |
| GET | `/api/nights` | List Nights |
| GET | `/api/nights/calendar` | Calendar |
| GET | `/api/nights/by-date/{day}` | By Date |
| GET | `/api/nights/compare` | Compare |
| GET | `/api/nights/{night_id}` | Night Detail |
| PATCH | `/api/nights/{night_id}` | Update Night |
| GET | `/api/nights/{night_id}/events` | Night Events |
| GET | `/api/nights/{night_id}/timeseries` | Night Timeseries |
| GET | `/api/nights/{night_id}/insights` | Night Insights |
| GET | `/api/events` | Search Events |
| GET | `/api/events/types` | Event Types |
| GET | `/api/statistics/summary` | Statistics Summary |
| GET | `/api/statistics/trends` | Trends |
| GET | `/api/statistics/events` | Event Distribution |
| GET | `/api/dashboard` | Dashboard |
| GET | `/api/reports/{kind}` | Report |
| GET | `/api/export/nights.{fmt}` | Export Nights |
| GET | `/api/export/events.{fmt}` | Export Events |
| GET | `/api/export/nights/{night_id}/timeseries.{fmt}` | Export Night Timeseries |
| GET | `/api/export/archive.zip` | Analysed data as ZIP: nights, events, settings and optionally all time series. |
| GET | `/api/export/raw.zip` | Original files as imported (unchanged bytes, original directory layout). |
| GET | `/api/export/formats` | Formats |
| GET | `/api/devices` | Devices |
| GET | `/api/devices/{device_id}` | Device |
| PATCH | `/api/devices/{device_id}` | Update Device |
| DELETE | `/api/devices/{device_id}` | Delete a device with all its nights.  Original files stay in the archive |
| GET | `/api/devices/{device_id}/settings-history` | Periods with identical device settings (changes over time). |
| GET | `/api/users` | Users |
| POST | `/api/users` | Create User |
| PATCH | `/api/users/{user_id}` | Patch User |
| DELETE | `/api/users/{user_id}` | Delete User |
| GET | `/api/health` | Unauthenticated health check for monitoring / reverse proxies. |
| GET | `/api/system/info` | Info |
| GET | `/api/system/diagnostics` | Diagnostics |
| POST | `/api/system/reprocess` | Rebuild all nights (or of one device) from the raw archive. |
| GET | `/api/system/backups` | Backups |
| POST | `/api/system/backups` | Make Backup |
| GET | `/api/system/backups/{name}` | Download Backup |
| GET | `/api/system/audit` | Audit Log |
| GET | `/api/hardware` | List Items |
| POST | `/api/hardware` | Create Item |
| GET | `/api/hardware/timeline` | Start/end dates of equipment, e.g. as markers in trend charts. |
| GET | `/api/hardware/{item_id}` | Get Item |
| PATCH | `/api/hardware/{item_id}` | Update Item |
| DELETE | `/api/hardware/{item_id}` | Delete Item |
| POST | `/api/hardware/{item_id}/replace` | Retire an item and create its successor (e.g. the yearly new mask). |
| POST | `/api/hardware/{item_id}/readings` | Add Reading |
| DELETE | `/api/hardware/{item_id}/readings/{reading_id}` | Delete Reading |
| GET | `/api/hardware/{item_id}/impact` | Statistical comparison of key metrics before vs. after the start date. |
| GET | `/api/appearance` | Get Appearance |
| PUT | `/api/appearance/user` | Put User Css |
| PUT | `/api/appearance/global` | Put Global Css |
| GET | `/api/channels` | Channel Registry |
