# Sleepy Android-App

Die App zeigt die wichtigsten Daten deines Sleepy-Servers auf dem Handy – optimiert für den Handybildschirm:

* **Übersicht:** Kurz-Zusammenfassung, letzte Nacht (Nutzung, AHI, CAI/OAI/HI, Leckage, Druck, Flusslimitierung, SpO2), Auffälligkeiten, Hardware-Hinweise, 7-/30-Tage-Durchschnitt, AHI-/Nutzungsdiagramm, letzte Nächte
* **Nächte:** Liste mit Schnellfiltern (AHI > 5, Leck > 24, < 4 h, mit CA)
* **Nacht:** alle Kennzahlen, Zusammenfassung, Beobachtungen, synchronisierte Diagramme (Ereignisse, Flow, Druck, Leckage, Flusslimitierung, Atmung, SpO2/Puls), Ereignisliste (antippen = hinzoomen)
* **Kalender** mit Ampelfarben, **Trends** (7 Tage bis 1 Jahr), **Mehr:** Hardware inkl. Turbinenstunden, Hell/Dunkel, Abmelden

Bewusst **nicht** in der App: Import/Upload, Hilfe/Legende, Reports/Export, Verwaltung – dafür gibt es die Weboberfläche.

## Zoomen mit zwei Fingern

| Geste | Wirkung |
|---|---|
| Zwei Finger spreizen/zusammenziehen | Zeitachse zoomen – alle Diagramme einer Nacht zoomen gemeinsam; beim Hineinzoomen lädt die App automatisch die volle Auflösung (Flow 25 Werte/s) |
| „↕ Skala“ aktivieren, dann zwei Finger | Werte-Achse (Skala) des jeweiligen Diagramms zoomen |
| Ein Finger | Seite scrollen; mit „✋ Verschieben“ stattdessen das Zeitfenster bewegen |
| Antippen | Werte zum Zeitpunkt anzeigen (in allen Diagrammen) |
| Übersichtsleiste antippen / ◀ ▶ ＋ － / „Ganze Nacht“ | springen, verschieben, zoomen, zurücksetzen |

## Installation

1. Auf dem Handy die neueste APK aus den GitHub-Releases laden: **Releases → „Sleepy Android-App …“ → `Sleepy-<Version>-build<Nr>.apk`** (Tag `android-latest`). Alternativ unter *Actions → Android-App (APK) → Artifacts*.
2. Beim Öffnen „Installation aus unbekannten Quellen“ für den Browser/Dateimanager erlauben.
3. App öffnen → **Server-Adresse** eingeben, z. B. `192.168.1.50:8000` (ohne `http://` wird `http://` ergänzt) oder `https://sleepy.home.lan` → „Verbindung testen“ → Benutzername/Passwort (bei aktivierter 2FA zusätzlich der Code).

Das Handy muss den Server erreichen (gleiches WLAN, oder unterwegs per VPN, z. B. WireGuard/Tailscale – Sleepy selbst nicht ins Internet freigeben).

Die Anmeldung erzeugt ein eigenes App-Token (kein Browser-Cookie). Es bleibt gültig, bis du dich abmeldest, es 60 Tage nicht benutzt wurde (`SLEEPY_APP_IDLE_DAYS`) oder nach maximal 365 Tagen (`SLEEPY_APP_SESSION_DAYS`). Widerruf jederzeit in der Weboberfläche unter **Einstellungen → Profil & Sicherheit → Verbundene Apps**.

### HTTP oder HTTPS?

* `http://` im Heimnetz funktioniert (die App erlaubt unverschlüsselte Verbindungen ausdrücklich, da Sleepy meist intern läuft).
* Für HTTPS mit eigenem Zertifikat (z. B. Caddy `tls internal`, eigene CA): CA-Zertifikat auf dem Handy installieren (*Einstellungen → Sicherheit → Verschlüsselung & Anmeldedaten → Zertifikat installieren → CA-Zertifikat*). Die App vertraut vom Nutzer installierten CAs.

## Ohne App: Handy-Oberfläche im Browser

Dieselbe Oberfläche liefert der Server unter **`http://<server>:8000/m/`** aus (Anmeldung per Browser-Sitzung). Über „Zum Startbildschirm hinzufügen“ wie eine App nutzbar.

## Bauen

Die APK wird automatisch von GitHub Actions gebaut ([`.github/workflows/android.yml`](../.github/workflows/android.yml)), sobald sich `frontend/` auf `main` ändert, oder manuell über *Actions → Android-App (APK) → Run workflow*.

Lokal (Android-SDK + JDK 21 nötig):

```bash
cd frontend
npm ci && npm run build && npx cap sync android
cd android && ./gradlew assembleRelease
# → app/build/outputs/apk/release/app-release.apk
```

### Signatur

Ohne weitere Einrichtung wird mit dem Entwicklungs-Schlüssel `frontend/android/app/keystore/sleepy-dev.jks` signiert (im Repository, damit Updates sich über die alte Version installieren lassen). Da dieser Schlüssel öffentlich im Repository liegt, wird für dauerhafte Nutzung ein **eigener Schlüssel** empfohlen:

```bash
keytool -genkeypair -keystore sleepy-release.jks -alias sleepy -keyalg RSA -keysize 3072 -validity 10000
base64 -w0 sleepy-release.jks   # Ausgabe als Secret speichern
```

GitHub → Repository → *Settings → Secrets and variables → Actions*: `SLEEPY_KEYSTORE_BASE64`, `SLEEPY_KEYSTORE_PASSWORD`, `SLEEPY_KEY_ALIAS` (`sleepy`), `SLEEPY_KEY_PASSWORD`. Achtung: Beim Wechsel des Schlüssels muss die alte App einmal deinstalliert werden.

## Technik

Capacitor 8 (Android 7.0+, API 24), die Oberfläche ist React/TypeScript/ECharts (`frontend/mobile/`). Netzwerkzugriffe laufen über die native HTTP-Schicht von Capacitor (kein CORS nötig). Es werden keine Daten an Dritte gesendet; die App hat nur die Berechtigung „Internet“, Android-Cloud-Backup ist deaktiviert.
