import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Card, Disclaimer } from "../components/ui";
import { GLOSSARY } from "../lib/glossary";

const STATUS = [
  ["green", "unauffällig", "AHI unter der gelben Schwelle, Nutzung ausreichend, Leckage unter der Schwelle"],
  ["yellow", "auffällig", "AHI über der gelben Schwelle, kurze Nutzung oder hohe Leckage"],
  ["red", "viele Ereignisse", "AHI über der roten Schwelle"],
  ["none", "keine Daten", "für diesen Tag wurden keine Therapiedaten importiert"],
];

export default function Help() {
  const [q, setQ] = useState("");
  const groups = useMemo(() => {
    const f = q.trim().toLowerCase();
    const items = GLOSSARY.filter((g) => !f || `${g.term} ${g.long} ${g.text} ${(g.aliases || []).join(" ")}`.toLowerCase().includes(f));
    const m = new Map<string, typeof items>();
    for (const g of items) m.set(g.group, [...(m.get(g.group) || []), g]);
    return [...m.entries()];
  }, [q]);

  return (
    <div className="stack">
      <Card title="Hilfe & Legende">
        <p style={{ marginTop: 0 }}>
          Hier findest du die Erklärungen der Abkürzungen und Begriffe. Viele Kennzahlen zeigen die Erklärung auch als Tooltip, wenn du mit der
          Maus darauf zeigst.
        </p>
        <input placeholder="Begriff suchen, z. B. AHI, EPR, Perzentil …" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: "100%", maxWidth: 420 }} aria-label="Glossar durchsuchen" />
      </Card>

      {groups.map(([group, items]) => (
        <Card key={group} title={group}>
          <dl className="glossary">
            {items.map((g) => (
              <div key={g.term} className="glossary-row" id={`g-${g.term}`}>
                <dt>
                  <strong>{g.term}</strong>
                  {g.long && <span className="muted"> · {g.long}</span>}
                </dt>
                <dd>{g.text}</dd>
              </div>
            ))}
          </dl>
        </Card>
      ))}
      {groups.length === 0 && <Card><p className="muted">Kein Eintrag gefunden.</p></Card>}

      <div className="grid cols-2">
        <Card title="Farben der Status-Ampel">
          <table className="table">
            <tbody>
              {STATUS.map(([s, l, d]) => (
                <tr key={s}>
                  <td><span className={`dot ${s}`} /></td>
                  <td><strong>{l}</strong></td>
                  <td style={{ whiteSpace: "normal" }}>{d}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">Die Schwellen legst du unter <Link to="/settings">Einstellungen → Schwellenwerte</Link> fest.</p>
        </Card>
        <Card title="Diagramme bedienen">
          <ul className="obs-list">
            <li><strong>Mausrad</strong>: zoomt an der Mausposition, alle Diagramme bewegen sich gemeinsam.</li>
            <li><strong>Umschalt + Mausrad</strong>: zeitlich verschieben.</li>
            <li><strong>Bereich aufziehen</strong> (Modus „Bereich wählen“): genau diesen Zeitraum anzeigen.</li>
            <li><strong>Verschieben</strong>-Modus: mit gedrückter Maustaste ziehen.</li>
            <li><strong>Doppelklick</strong> oder Taste <kbd>0</kbd>: ganze Nacht. Tasten <kbd>←</kbd>/<kbd>→</kbd>, <kbd>+</kbd>/<kbd>−</kbd>.</li>
            <li><strong>Übersichtsleiste</strong> oben anklicken: Ausschnitt dorthin verschieben.</li>
            <li><strong>Ereignis in der Liste</strong> anklicken: Zoom auf das Ereignis mit Markierung.</li>
            <li>Ereignismarker im Flow liegen am vom Gerät gespeicherten Zeitpunkt (Ende des Ereignisses); die farbige Fläche zeigt die Dauer.</li>
          </ul>
        </Card>
        <Card title="Suche in „Nächte“">
          <ul className="obs-list">
            <li><code>ahi&gt;5</code>, <code>cai&gt;=1</code>, <code>oai&lt;2</code>, <code>rdi&gt;5</code></li>
            <li><code>leak&gt;20</code> (95 %-Leckage), <code>leak_median&gt;5</code>, <code>pressure&gt;10</code>, <code>fl&gt;0.3</code></li>
            <li><code>usage&lt;4h</code>, <code>usage&gt;=90min</code></li>
            <li><code>event:CA</code>, <code>event:OA&gt;=5</code></li>
            <li><code>2026-09</code>, <code>2026-09-01..2026-09-15</code>, <code>05.10.2026</code></li>
            <li><code>device:SERIENNUMMER</code>, <code>notizen</code> – mehrere Begriffe werden UND-verknüpft</li>
          </ul>
        </Card>
        <Card title="SD-Karte importieren">
          <ol className="obs-list">
            <li>SD-Karte aus dem Gerät nehmen (Gerät vorher ausschalten bzw. Therapie beendet).</li>
            <li>Den <strong>kompletten Inhalt</strong> der Karte in eine ZIP-Datei packen (oder unter Import den Ordner wählen).</li>
            <li><Link to="/import">Import</Link> → ZIP auswählen. Bereits bekannte Dateien werden automatisch erkannt.</li>
            <li>SD-Karte wieder ins Gerät stecken. Keine Dateien auf der Karte löschen oder verändern.</li>
          </ol>
        </Card>
      </div>
      <Disclaimer />
    </div>
  );
}
