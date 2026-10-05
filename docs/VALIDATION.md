# Validierung mit echten SD-Karten-Daten

Der ResMed-Parser wurde mit **synthetischen** Dateien entwickelt und getestet, die die dokumentierte Struktur nachbilden (`cpap_parser.testing.synthetic_resmed`). Echte Daten lagen nicht vor. Bevor Sleepy produktiv genutzt wird, sollte der Parser einmal mit einer Kopie der eigenen SD-Karte geprüft werden.

## Benötigte Dateien

Eine **vollständige Kopie der SD-Karte** (am einfachsten als ZIP):

* `Identification.tgt` bzw. `Identification.json` (+ `.crc`)
* `STR.edf`
* `DATALOG/` mit mindestens 3–5 Nächten, ideal:
  * eine Nacht mit mehreren Masken-Sitzungen (Maske zwischendurch abgesetzt),
  * eine Nacht mit vielen Ereignissen,
  * falls vorhanden eine Nacht mit Oximeter (SAD/SA2-Datei mit Werten).
* `SETTINGS/` (wird nur archiviert)

> Keine echten Daten in das Git-Repository einchecken. Die `.gitignore` schließt `*.edf`, `*.zip` und Datenverzeichnisse aus.

## Prüfschritte

1. **Import:** ZIP hochladen. Erwartung: Gerät, Modell und Seriennummer korrekt erkannt; keine Fehler im Importprotokoll; Warnungen lesen (Import → Details & Protokoll).
2. **Abgleich mit dem Gerät/myAir/OSCAR** für 2–3 Nächte:
   * Nutzungsdauer, AHI, Leck 95 %, Druck 95 % (Spalten „Gerät“ und „Berechnet“ in „Alle Kennzahlen“).
   * Gerätewerte müssen exakt mit der Geräteanzeige übereinstimmen; berechnete Werte dürfen leicht abweichen.
3. **Ereignis-Zeitpunkt (wichtigste offene Annahme):** In einer Nacht auf eine obstruktive Apnoe klicken. Der flache/reduzierte Flow muss im markierten Bereich **vor** der senkrechten Markierung liegen. Falls er *nach* der Markierung liegt: in `parser/cpap_parser/resmed/parser.py` `EVENT_ONSET_IS_END = False` setzen, Parser-Version erhöhen und „Alle Nächte neu berechnen“.
4. **Einheiten:** Flow-Spitzen typischerweise 20–60 L/min, Atemzugvolumen 300–700 mL, Leckage im L/min-Bereich. In „Sitzungen, Einstellungen & Herkunft → Kanäle“ stehen Original-Label, Einheit und ggf. Umrechnung.
5. **Unbekannte Kanäle/Annotationen:** Werden generisch übernommen (`x_…` bzw. Ereignistyp „Sonstiges“) und im Protokoll gemeldet. Diese Labels bitte melden, damit sie sauber zugeordnet werden.
6. **Einstellungen:** Modus, Min/Max-Druck, EPR-Stufe mit dem Gerätemenü vergleichen.

## Was bei Abweichungen hilft

```bash
sudo /opt/sleepy/scripts/diagnose.sh > diagnose.txt   # keine Gesundheitsdaten enthalten
```

Zur Analyse eines Formatproblems genügen meist die **EDF-Header** (erste 256 + n·256 Bytes) einer betroffenen Datei – sie enthalten Labels, Einheiten und Skalierung, aber keine Messwerte:

```bash
/opt/sleepy/venv/bin/python - <<'EOF'
from cpap_parser.edf import read_edf_header
h = read_edf_header("DATALOG/20261004/20261004_223015_PLD.edf")
print(h.start, h.n_records, h.record_duration, h.reserved)
for s in h.signals:
    print(repr(s.label), s.dimension, s.physical_min, s.physical_max, s.digital_min, s.digital_max, s.samples_per_record)
EOF
```

Nach einer Parser-Anpassung genügt **„Alle Nächte neu berechnen“** (Einstellungen → System) – die Originaldateien liegen unverändert im Archiv, ein erneuter Upload ist nicht nötig.
