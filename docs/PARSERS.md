# Parser-Architektur und neue Hersteller

```
parser/cpap_parser/
├── edf.py            EDF/EDF+ Reader (Spezifikation, gzip, TAL-Annotationen)
├── edf_writer.py     Writer für synthetische Testdaten
├── model.py          herstellerunabhängiges Datenmodell (ParsedNight, ParsedSignal, ParsedEvent …)
├── channels.py       kanonische Kanal- und Ereigniscodes (flow, pressure, leak … / OA, CA, H …)
├── base.py           CPAPParser-Basisklasse, FileSet, Registry, detect()
├── resmed/           ResMed (vollständig)
│   ├── identification.py, str_file.py, labels.py, parser.py
├── philips.py        Philips (nur Erkennung, nicht unterstützt)
└── testing/synthetic_resmed.py
```

## Vertrag eines Parsers

```python
class MyParser(CPAPParser):
    name = "acme"; manufacturer = "ACME"; version = "1.0"
    def find_roots(self, rel_paths) -> list[str]: ...     # Wurzelverzeichnisse im Upload ("" oder "a/b/")
    def detect(self, files: FileSet) -> Detection | None: ...
    def identify(self, files: FileSet) -> DeviceInfo: ...
    def classify(self, rel_path: str) -> FileClassification: ...  # "events" | "waveform" | "summary" | …
    def plan(self, files: FileSet) -> list[NightPlan]: ...       # welche Nächte, welche Dateien
    def parse_night(self, files: FileSet, night: date) -> ParsedNight: ...
    def summaries(self, files: FileSet) -> dict[date, dict]: ... # optional: Tageszusammenfassungen
PARSER = register(MyParser())
```

und Import in `cpap_parser/__init__.py`.

Regeln:

* **Nie raten.** Unbekannte Signale als `x_<label>` übernehmen, unbekannte Annotationen als `OTHER` mit Originaltext, und eine Warnung in `ParsedNight.warnings` schreiben.
* Zeitstempel als Wall-Clock-Millisekunden (`model.wall_ms`).
* Rohwerte verlustfrei als int16 + `gain/offset` liefern; Einheitenumrechnung in `gain/offset` falten und in `conversion` dokumentieren.
* `FileSet` bekommt Dateien aus dem Rohdatenarchiv (Pfad relativ zur Karten-Wurzel). `files.versions(rel)` liefert ältere Versionen (z. B. frühere `STR.edf`).
* `version` erhöhen, wenn sich die Interpretation ändert – danach „Alle Nächte neu berechnen“.

## Tests

Synthetische Testdaten erzeugen, Parser darauf testen (`tests/test_resmed_parser.py` als Vorlage). Keine echten Personendaten einchecken.
