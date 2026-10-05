# Recherche: CPAP-Datenformate, OSCAR, SleepHQ

Stand: Oktober 2026. Diese Datei dokumentiert, **was aus welchen Quellen über die Formate bekannt ist**, welche Annahmen Sleepy trifft und welche davon noch an echten Daten validiert werden müssen (siehe [VALIDATION.md](VALIDATION.md)).

## 1. Quellen

| Quelle | Lizenz | Verwendung in Sleepy |
|---|---|---|
| EDF/EDF+-Spezifikation (Kemp et al. 1992, Kemp & Olivan 2003, edfplus.info) | offen | Eigener Reader nach Spezifikation (`parser/cpap_parser/edf.py`) |
| OSCAR – Open Source CPAP Analysis Reporter (`oscar/SleepLib/loader_plugins/resmed_loader.cpp`, `edfparser.cpp`, `resmed_EDFinfo.cpp`) | GPL-3.0 | **Nur technische Referenz** (Dateinamen, Signal-Labels, Einheiten, STR-Struktur, Modusnummern). Kein Code übernommen. |
| OSCAR `prisma_loader.cpp/.h` (Löwenstein prisma) | GPL-3.0 | **Nur technische Referenz** für Fakten: Bedeutung der Ereignis-IDs (`RespEventID`), Parameter-IDs, Zeiteinheit 1/10 s, Sample-Breite `#1/#2` in WMEDF. Kein Code übernommen; alles an echten Dateien nachgeprüft (Abschnitt 3b). |
| SleepHQ (Funktionsumfang, öffentlich sichtbare Oberfläche) | proprietär | Nur funktionales Vorbild, kein Code/kein Format |

## 2. Entscheidung OSCAR-Wiederverwendung

OSCAR ist in C++/Qt geschrieben und GPL-3.0-lizenziert. Eine direkte Wiederverwendung hätte bedeutet:

* entweder die Qt-Loader als Bibliothek zu kompilieren und per FFI anzubinden (große Abhängigkeit, Qt im LXC, kein stabiles API),
* oder Code nach Python zu portieren – eine Portierung wäre ein abgeleitetes Werk und würde Sleepy unter die GPL-3.0 stellen.

**Entscheidung:** Eigene Implementierung in Python (EDF-Reader + ResMed-Parser). OSCAR dient ausschließlich als Referenz für *Fakten* über das Format (Dateinamen, Bedeutung von Labels, Einheiten), die zudem in den EDF-Headern selbst stehen. Die Skalierung (physikalische/digitale Bereiche) wird immer aus dem jeweiligen EDF-Header gelesen, nicht aus OSCAR übernommen.

## 3. ResMed SD-Karte (S9, AirSense/AirCurve 10, AirSense/AirCurve 11)

```
Identification.tgt        S9/AS10: Textdatei "#KEY Wert" (#SRN Seriennr., #PNA Produktname, #PCD Produktcode, …)
Identification.json       AS11: JSON, FlowGenerator.IdentificationProfiles.Product.{SerialNumber, ProductCode, ProductName}
Identification.crc        Prüfsumme (nicht interpretiert, nur archiviert)
STR.edf                   Tageszusammenfassung: 1 EDF-Datensatz pro Therapietag
SETTINGS/                 Einstellungsdateien (nur archiviert)
DATALOG/YYYYMMDD/         ein Ordner pro Therapietag (S9: Dateien direkt in DATALOG/)
   YYYYMMDD_HHMMSS_BRP.edf  hochaufgelöst 25 Hz: Flow.40ms (L/s), Press.40ms (cmH2O), [TrigCycEvt.40ms]
   YYYYMMDD_HHMMSS_PLD.edf  0,5 Hz: MaskPress.2s, Press.2s, EprPress.2s, Leak.2s (L/s), RespRate.2s,
                            TidVol.2s (L), MinVent.2s, Snore.2s, FlowLim.2s, [IERatio, B5ITime, B5ETime, TgtVent…]
   YYYYMMDD_HHMMSS_SAD.edf  1 Hz: SpO2.1s, Pulse.1s (−1 = kein Oximeter) – AS11 teils "SA2"
   YYYYMMDD_HHMMSS_EVE.edf  EDF+ Annotationen: Obstructive Apnea, Central Apnea, Hypopnea, Apnea, Arousal, …
   YYYYMMDD_HHMMSS_CSL.edf  EDF+ Annotationen: "CSR Start"/"CSR End"
   *.crc                    Prüfsummen
```

### Fakten, die Sleepy verwendet

| Thema | Umsetzung | Quelle |
|---|---|---|
| Therapietag | 12:00 bis 12:00 Uhr; Ordnername = Therapietag | OSCAR |
| Zeitzone | EDF speichert Gerätelokalzeit ohne Zone → Sleepy speichert „Wall-Clock-Millisekunden“ und zeigt exakt die Gerätezeit | EDF-Spezifikation |
| Jahreszahl | EDF `dd.mm.yy`, 85–99 → 19xx, sonst 20xx | EDF-Spezifikation |
| STR.edf | Startdatum = erster Tag, Datensatz *i* = Tag +*i*; `MaskOn/MaskOff` = Minuten seit 12:00, −1 = unbenutzt; `Duration` = Minuten; negative Werte = „nicht verfügbar“ | OSCAR |
| STR-Kennzahlen | AHI, AI, HI, OAI, CAI, UAI, RIN (RERA-Index), Leak.50/70/95/Max, MaskPress.*, TgtIPAP.*, TgtEPAP.*, RespRate.*, TidVol.*, MinVent.*, SpO2.* | OSCAR |
| Einheiten | Flow/Leak in L/s (→ ×60 L/min), Tidalvolumen in L (→ ×1000 mL). Umrechnung nur, wenn die EDF-Einheit dies angibt (oder fehlt – dann mit Hinweis) | EDF-Header + OSCAR |
| Therapiemodus | AS10/S9-Nummerierung (0 CPAP, 1 AutoSet, …, 11 AutoSet for Her); AS11 abweichend (1 APAP, 2 For Her, 3 CPAP, …) | OSCAR |
| Seriennummer-Fallback | EDF-Feld „recording identification“ enthält `SRN=…` | OSCAR |
| Label-Varianten | S9 verwendet lokalisierte/abweichende Labels („Mask Pres“, „Therapy Pres“, „Leck“ …) | OSCAR |

### Annahmen, die noch an echten Daten geprüft werden müssen

1. **Zeitpunkt der Ereignis-Annotation:** OSCAR zeichnet ResMed-Ereignisse so, dass die Markierung am *Ende* des Ereignisses liegt und die Dauer nach links reicht. Sleepy übernimmt diese Interpretation (`EVENT_ONSET_IS_END = True`), speichert aber zusätzlich den Roh-Zeitpunkt (`onset_ms`). Prüfung: flacher Flow muss *vor* der OA-Markierung liegen.
2. **Bilevel/AirCurve-Labels** (IPAP/EPAP in PLD) sind nur über Präfixe abgebildet – ungetestet.
3. **Firmware** ist bei AS10 nicht eindeutig in `Identification.tgt` dokumentiert → Sleepy zeigt „nicht ermittelbar“, alle Rohschlüssel sind in der Geräteansicht sichtbar.
4. **STR „CSR“** – Bedeutung/Einheit unklar → nur als Rohwert gespeichert („CSR (Gerätewert, Rohwert)“).
5. **I:E-Verhältnis** – OSCAR teilt durch 100; Sleepy zeigt den Rohwert mit dieser Kennzeichnung.
6. **Leckage-Art** – ob `Leak.2s` unbeabsichtigte oder Gesamtleckage ist, wird nicht behauptet; Anzeige als „Leckage“ in Geräteeinheit.

## 3b. Löwenstein prisma SMART / prisma SOFT

```
config.pscfg                         JSON: dev.sn (Seriennummer hexadezimal), devid (0x92 = prisma SMART,
                                     0x91 = prisma SOFT), fwversion, hwversion
statistic.psstat                     JSON mit numerischen Schlüsseln (Langzeitstatistik) – Bedeutung nicht
                                     dokumentiert, wird nur archiviert
Dcm/dcm.zip                          Kommunikationsmodul (nur archiviert)
<SN dezimal, 10-stellig>/YYYYMMDD/   Therapietag, den das Gerät der Sitzung zuordnet
    signal_<n>.wmedf                 Signale einer Maskensitzung
    event_<n>.xml                    Einstellungen + Atemereignisse derselben Sitzung
    trendCurves.tc                   binär, nicht dokumentiert (nur archiviert)
<SN>/log/*.log                       Geräteprotokolle (nur archiviert)
```

### Fakten, die Sleepy verwendet (an einer echten prisma-SMART-Karte geprüft)

* **WMEDF** = EDF-Header (Versionsfeld `1`), Datensatzdauer 1 s. Das *reserved*-Feld jedes Signals gibt die Sample-Breite an: `#1` = 8 Bit (vorzeichenlos, wenn digitales Minimum ≥ 0), `#2` = 16 Bit. Dateigröße = Header + Datensätze × Summe der Bytes – geprüft für alle Dateien der Karte.
* Startzeit im EDF-Header ist Ortszeit (passt zur Unix-Zeit im XML-Kommentar `started …` plus Zeitzone).
* Signale (Label → Sleepy): `RespFlow` → Flow (L/min, 5 Hz), `LeakFlowBreath` → Leckage (L/min), `CPAPPressure` → Druck (Soll), `Pressure` → Maskendruck, `PressureMeasured`, `ObstructLevel` (%), `FlowFull`, `rRMV`, `IPAP`/`EPAP` (bei CPAP/APAP identisch mit `CPAPPressure` und dann ausgeblendet). Druck in hPa wird exakt in cmH2O umgerechnet (× 1/0,980665); Skalierung immer aus dem Header.
* **Ereignisse:** `EndTime` und `Duration` in 1/10 s; `EndTime` ist das **Ende** des Ereignisses relativ zum Start der zugehörigen Signaldatei. Geprüft: Bei obstruktiven Apnoen fällt die Flow-Amplitude genau im Fenster `[EndTime − Duration, EndTime]` auf ca. 15 % (Hypopnoen ca. 45 %) des Werts davor; die größte `EndTime` jeder Datei entspricht der Signaldauer.
* Ereignis-IDs: 101 OA, 102 CA, 103/105/106 Apnoe (Leckage/hoher Druck/Bewegung → UA), 111/112/113 Hypopnoe → H, 121 RERA, 131 Schnarchen → VS, 141 Artefakt, 151 Flusslimitierung, 161 kritische Leckage → LL, 181 CSR, 221 gerätegetriggerter Atemzug, 1–5 Zwei-Minuten-Epochen (schwere/leichte Obstruktion, Flusslimitierung, Schnarchen, periodische Atmung), 261 Tiefschlaf-Epoche (Geräteschätzung).
* Parameter (`DeviceEventID="0"`): 6 Modus (1 CPAP, 2 APAP), 9/10 Druck min/max (1/100 hPa), 11/12 Softstart-Drücke, 13 softPAP (0 aus, 1 leicht, 2 standard), 15 APAP-Regelung (1 standard, 2 dynamisch), 16 Befeuchterstufe, 17 Autostart, 18/19 Softstart-Zeit, 21 Schlauchtyp, 38 PMaxOA.

### Nicht interpretiert (bewusst)

* Ereignis-IDs ohne öffentliche Dokumentation (z. B. 108, 231, 241, 262, 1007, 1008, 1101, 1111, 1112, 1118, 1126, 1129, 1130, 1230, 1231, 1240, 1241) werden **nicht** als Ereignisse übernommen, sondern je Nacht gezählt (`summary_raw.unknown_event_codes`).
* Unbekannte Parameter (z. B. 14) landen in `summary_raw.unknown_parameters`.
* `statistic.psstat`, `trendCurves.tc`, Protokolle: nur archiviert. Daher gibt es (anders als bei ResMed-STR.edf) **keine Geräte-Tageswerte**; AHI usw. berechnet Sleepy aus den Ereignissen.
* Einheiten von Softstart-Zeit und Schlauchtyp werden als Gerätewert angezeigt.
* prisma LINE (`config.pcfg`, `therapy.pdat`) wird erkannt und archiviert, aber nicht ausgewertet (keine Testdaten).

## 4. Andere Hersteller

| Hersteller | Status in Sleepy | Begründung |
|---|---|---|
| Philips Respironics (System One / DreamStation) | **Erkennung** (Ordner `P-Series`), Dateien werden archiviert, aber **nicht ausgewertet** | Binärformat mit vielen Versionen, DreamStation 2 zusätzlich verschlüsselt. Ohne Testdaten keine verlässliche Implementierung. |
| Löwenstein prisma SMART/SOFT | **unterstützt** (Abschnitt 3b) | an einer echten Karte geprüft |
| Löwenstein prisma LINE | **Erkennung**, archiviert, nicht ausgewertet | keine Testdaten |
| Fisher & Paykel, BMC/Luna, React Health | nicht unterstützt | wie oben |

Die Parser-Architektur (`CPAPParser` mit `detect/identify/classify/plan/parse_night/summaries`) ist so geschnitten, dass weitere Hersteller als eigene Module ergänzt werden können (siehe [PARSERS.md](PARSERS.md)). Da Originaldaten immer archiviert werden, können früher importierte, damals nicht unterstützte Karten später ausgewertet werden.

## 5. SleepHQ/OSCAR-Funktionsabgleich

| Funktion | Sleepy | Bemerkung |
|---|---|---|
| Nachtansicht mit Flow, Druck, Leck, Atemparametern, SpO2 | ✅ | synchronisiert, Zoom bis Rohsample-Ebene |
| Ereignisflags, Ereignisliste mit Sprung | ✅ | |
| AHI/AI/HI/OAI/CAI/UAI/RDI/RERA | ✅ | Gerätewerte und unabhängig berechnete Werte |
| ODI | ✅ (nur mit Oximeter) | vereinfachter, nicht klinisch validierter Algorithmus (≥3 % vom gleitenden Median) |
| Kalender, Trends, Perzentile, Vergleich, Reports | ✅ | |
| Einstellungsverlauf | ✅ | aus STR.edf je Tag |
| Eigene Ereigniserkennung aus dem Flow (z. B. OSCAR „User Flags“) | ❌ | nicht implementiert |
| Atemzug-für-Atemzug-Analyse (Inspirationszeit, Flusslimitierungs-Scoring aus Flow) | ❌ | nur die vom Gerät gelieferten Kanäle |
| Import externer Oximeter (CMS50, Wellue/Viatom) | ❌ | Architektur vorbereitet, nicht implementiert |
| Online-Teilen / Cloud-Sync | ❌ (bewusst) | rein lokal |
| Schlafstadien | ❌ | aus CPAP-Daten nicht seriös ableitbar |
