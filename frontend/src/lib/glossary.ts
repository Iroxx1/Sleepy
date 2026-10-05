// Deutsche Erklärungen der Abkürzungen und Begriffe (Hilfeseite + Tooltips).

export interface GlossaryEntry {
  term: string;
  long: string;
  text: string;
  group: string;
  aliases?: string[];
}

export const GLOSSARY: GlossaryEntry[] = [
  // ---- Indizes
  { group: "Indizes", term: "AHI", long: "Apnoe-Hypopnoe-Index", text: "Anzahl der Apnoen und Hypopnoen pro Stunde Therapiezeit (OA + CA + UA + H). Wird vom Gerät berechnet und zusätzlich von Sleepy aus den Ereignissen nachgerechnet." },
  { group: "Indizes", term: "AI", long: "Apnoe-Index", text: "Apnoen (obstruktiv, zentral, nicht klassifiziert) pro Stunde." },
  { group: "Indizes", term: "HI", long: "Hypopnoe-Index", text: "Hypopnoen pro Stunde." },
  { group: "Indizes", term: "OAI", long: "Obstruktiver Apnoe-Index", text: "Obstruktive Apnoen pro Stunde (Atemwege verschlossen, Atemanstrengung vorhanden)." },
  { group: "Indizes", term: "CAI", long: "Zentraler Apnoe-Index", text: "Zentrale Apnoen (bei ResMed „Clear Airway“: Atemwege offen, keine Atemanstrengung erkannt) pro Stunde." },
  { group: "Indizes", term: "UAI", long: "Index nicht klassifizierter Apnoen", text: "Apnoen, die das Gerät weder als obstruktiv noch als zentral einordnen konnte, pro Stunde." },
  { group: "Indizes", term: "RDI", long: "Respiratory Disturbance Index", text: "Wie AHI, zusätzlich RERAs: (Apnoen + Hypopnoen + RERAs) pro Stunde." },
  { group: "Indizes", term: "RERA-Index", long: "Respiratory Effort Related Arousals", text: "Atemanstrengungs-bedingte Weckreaktionen pro Stunde (ResMed-Annotation „Arousal“).", aliases: ["RERA"] },
  { group: "Indizes", term: "ODI", long: "Oxygen Desaturation Index", text: "Sauerstoff-Entsättigungen um mindestens 3 % pro Stunde. Nur mit Pulsoximeter; von Sleepy mit einem vereinfachten, nicht klinisch validierten Verfahren berechnet." },
  // ---- Ereignisse
  { group: "Ereignisse", term: "OA", long: "Obstruktive Apnoe", text: "Atemfluss praktisch null, obwohl geatmet wird – Atemweg verschlossen." },
  { group: "Ereignisse", term: "CA", long: "Zentrale Apnoe / Clear Airway", text: "Atemfluss praktisch null bei offenem Atemweg (das Gerät erkennt keinen Verschluss)." },
  { group: "Ereignisse", term: "UA", long: "Nicht klassifizierte Apnoe", text: "Apnoe ohne eindeutige Zuordnung." },
  { group: "Ereignisse", term: "H", long: "Hypopnoe", text: "Deutlich verminderter Atemfluss über mindestens ca. 10 Sekunden." },
  { group: "Ereignisse", term: "RE", long: "RERA", text: "Atemanstrengungs-bedingte Weckreaktion (Arousal)." },
  { group: "Ereignisse", term: "CSR", long: "Cheyne-Stokes-Atmung", text: "Periodisches An- und Abschwellen der Atmung. Sleepy zeigt die vom Gerät markierten Zeiträume und deren Anteil an der Therapiezeit." },
  { group: "Ereignisse", term: "PB", long: "Periodische Atmung", text: "Periodisches Atemmuster (nur bei Geräten, die es melden)." },
  { group: "Ereignisse", term: "FL", long: "Flusslimitierung", text: "Abgeflachte Einatemkurve als Zeichen eines teilweise verengten Atemwegs. ResMed liefert einen Index von 0 (keine) bis 1 (stark)." },
  { group: "Ereignisse", term: "VS", long: "Vibratory Snore", text: "Vibrationsschnarchen (bei manchen Herstellern als Ereignis)." },
  { group: "Ereignisse", term: "LL", long: "Large Leak", text: "Große Leckage (Zeiträume mit Leckage über der Schwelle)." },
  // ---- Druck & Geräte
  { group: "Druck & Therapie", term: "CPAP", long: "Continuous Positive Airway Pressure", text: "Therapie mit konstantem Überdruck." },
  { group: "Druck & Therapie", term: "APAP", long: "Automatic PAP (AutoSet)", text: "Das Gerät passt den Druck innerhalb eines Bereichs (Min/Max) automatisch an." },
  { group: "Druck & Therapie", term: "Bilevel", long: "BiPAP / VPAP", text: "Getrennte Drücke für Ein- (IPAP) und Ausatmung (EPAP)." },
  { group: "Druck & Therapie", term: "ASV", long: "Adaptive Servo-Ventilation", text: "Spezielle Bilevel-Therapie mit variabler Druckunterstützung." },
  { group: "Druck & Therapie", term: "IPAP", long: "Inspiratory Positive Airway Pressure", text: "Druck während der Einatmung." },
  { group: "Druck & Therapie", term: "EPAP", long: "Expiratory Positive Airway Pressure", text: "Druck während der Ausatmung. Bei ResMed-CPAP/APAP mit EPR ist das der abgesenkte Ausatemdruck." },
  { group: "Druck & Therapie", term: "EPR", long: "Expiratory Pressure Relief", text: "ResMed-Komfortfunktion: Druckabsenkung beim Ausatmen um 1–3 cmH2O (Stufe)." },
  { group: "Druck & Therapie", term: "cmH2O", long: "Zentimeter Wassersäule", text: "Einheit für den Therapiedruck." },
  { group: "Druck & Therapie", term: "Maskendruck", long: "", text: "Gemessener Druck an der Maske (hochaufgelöst 25 Hz bzw. 0,5 Hz)." },
  { group: "Druck & Therapie", term: "Rampe", long: "", text: "Langsamer Druckanstieg zu Beginn der Therapie (Rampenzeit in Minuten)." },
  // ---- Atmung & Signale
  { group: "Atmung & Signale", term: "Flow", long: "Atemfluss", text: "Luftstrom in L/min, beim ResMed mit 25 Messungen pro Sekunde. Positive Werte = Einatmung, negative = Ausatmung." },
  { group: "Atmung & Signale", term: "Leckage", long: "Leak", text: "Ungewollt entweichende Luft (z. B. an der Maske) in L/min. Die gestrichelte Linie markiert die Schwelle (Standard 24 L/min, ResMed-Konvention)." },
  { group: "Atmung & Signale", term: "Atemfrequenz", long: "Respiratory Rate", text: "Atemzüge pro Minute." },
  { group: "Atmung & Signale", term: "Atemzugvolumen", long: "Tidal Volume (Vt)", text: "Luftmenge pro Atemzug in mL." },
  { group: "Atmung & Signale", term: "Atemminutenvolumen", long: "Minute Ventilation (MV)", text: "Luftmenge pro Minute in L/min (≈ Atemfrequenz × Atemzugvolumen)." },
  { group: "Atmung & Signale", term: "Schnarchen", long: "Snore", text: "Schnarch-Index des Geräts (relative Größe, keine Lautstärke in dB)." },
  { group: "Atmung & Signale", term: "SpO2", long: "Sauerstoffsättigung", text: "Sauerstoffsättigung des Blutes in % – nur mit angeschlossenem Pulsoximeter." },
  { group: "Atmung & Signale", term: "Puls", long: "Herzfrequenz", text: "Schläge pro Minute – nur mit Pulsoximeter." },
  { group: "Atmung & Signale", term: "I:E", long: "Inspirations-/Exspirationsverhältnis", text: "Verhältnis von Ein- zu Ausatemzeit (Rohwert des Geräts)." },
  // ---- Statistik
  { group: "Statistik", term: "Median", long: "50 %-Perzentil", text: "Mittlerer Wert: die Hälfte der Messwerte liegt darunter, die Hälfte darüber. Robuster gegenüber Ausreißern als der Mittelwert." },
  { group: "Statistik", term: "95 %", long: "95 %-Perzentil (P95)", text: "95 % der Messzeit lag der Wert darunter, 5 % darüber. Gängige Kennzahl für Druck und Leckage.", aliases: ["P95", "95 %-Perzentil"] },
  { group: "Statistik", term: "Std.-Abw.", long: "Standardabweichung", text: "Maß für die Streuung der Werte um den Mittelwert." },
  { group: "Statistik", term: "Trend", long: "linearer Trend", text: "Steigung einer Ausgleichsgeraden über den Zeitraum. „steigend/fallend“ wird nur angezeigt, wenn die Änderung im Verhältnis zur Streuung deutlich ist." },
  { group: "Statistik", term: "Statistisch auffällig", long: "", text: "Ein Wert weicht deutlich (robuste Abweichung ≥ 3) von deinem persönlichen Median der letzten 30 Nächte ab. Das ist eine rein statistische Beobachtung, keine medizinische Bewertung." },
  { group: "Statistik", term: "Gerätewert / berechnet", long: "", text: "„Gerät“ = vom PAP-Gerät selbst berechnet (z. B. STR.edf). „Berechnet“ = von Sleepy aus den Detaildaten ermittelt. Kleine Abweichungen sind normal." },
  // ---- Sleepy
  { group: "Sleepy", term: "Therapietag", long: "", text: "Ein Therapietag läuft von 12:00 bis 12:00 Uhr. Die Nacht vom 4. auf den 5. Oktober gehört zum 4. Oktober." },
  { group: "Sleepy", term: "Sitzung", long: "Maskensitzung", text: "Zeitraum zwischen Maske auf und Maske ab. Eine Nacht kann mehrere Sitzungen haben." },
  { group: "Sleepy", term: "Status-Ampel", long: "", text: "Grün/Gelb/Rot im Kalender nach deinen Schwellenwerten (Einstellungen → Schwellenwerte). Keine medizinische Bewertung." },
  { group: "Sleepy", term: "STR.edf", long: "", text: "ResMed-Datei mit einer Tageszusammenfassung pro Therapietag (Kennzahlen und Einstellungen)." },
  { group: "Sleepy", term: "BRP / PLD / SAD / EVE / CSL", long: "ResMed-Dateitypen", text: "BRP: Flow und Maskendruck (25 Hz) · PLD: Druck, Leckage, Atemparameter (alle 2 s) · SAD: SpO2/Puls · EVE: Ereignisse · CSL: Cheyne-Stokes-Zeiträume." },
];

const BY_TERM = new Map<string, GlossaryEntry>();
for (const g of GLOSSARY) {
  BY_TERM.set(g.term.toLowerCase(), g);
  for (const a of g.aliases ?? []) BY_TERM.set(a.toLowerCase(), g);
}

/** Tooltip text for a KPI label such as "AHI", "Leck 95 %", "CAI". */
export function explain(label: string): string | undefined {
  const l = label.toLowerCase();
  const direct = BY_TERM.get(l);
  if (direct) return `${direct.term}${direct.long ? ` – ${direct.long}` : ""}: ${direct.text}`;
  for (const g of GLOSSARY) {
    if (g.term.length >= 2 && new RegExp(`(^|\\W)${g.term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(\\W|$)`, "i").test(label)) {
      return `${g.term}${g.long ? ` – ${g.long}` : ""}: ${g.text}`;
    }
  }
  return undefined;
}
