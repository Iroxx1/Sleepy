# Recherche: CPAP-Datenformate, OSCAR, SleepHQ

Stand: Oktober 2026. Diese Datei dokumentiert, **was aus welchen Quellen über die Formate bekannt ist**, welche Annahmen Sleepy trifft und welche davon noch an echten Daten validiert werden müssen (siehe [VALIDATION.md](VALIDATION.md)).

## 1. Quellen

| Quelle | Lizenz | Verwendung in Sleepy |
|---|---|---|
| EDF/EDF+-Spezifikation (Kemp et al. 1992, Kemp & Olivan 2003, edfplus.info) | offen | Eigener Reader nach Spezifikation (`parser/cpap_parser/edf.py`) |
| OSCAR – Open Source CPAP Analysis Reporter (`oscar/SleepLib/loader_plugins/resmed_loader.cpp`, `edfparser.cpp`, `resmed_EDFinfo.cpp`) | GPL-3.0 | **Nur technische Referenz** (Dateinamen, Signal-Labels, Einheiten, STR-Struktur, Modusnummern). Kein Code übernommen. |
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

## 4. Andere Hersteller

| Hersteller | Status in Sleepy | Begründung |
|---|---|---|
| Philips Respironics (System One / DreamStation) | **Erkennung** (Ordner `P-Series`), Dateien werden archiviert, aber **nicht ausgewertet** | Binärformat mit vielen Versionen, DreamStation 2 zusätzlich verschlüsselt. Ohne Testdaten keine verlässliche Implementierung. |
| Löwenstein (prisma) | **nicht unterstützt**, keine Erkennung | Format ohne belastbare öffentliche Dokumentation; nichts erfunden. |
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
