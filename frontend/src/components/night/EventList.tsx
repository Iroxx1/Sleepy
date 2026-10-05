import { useMemo, useState } from "react";
import type { EventType, NightEvent } from "../../api/types";
import { clock, num } from "../../lib/format";
import { EventChip } from "../ui";

interface Props {
  events: NightEvent[];
  types: Record<string, EventType>;
  contextChannels: string[];
  selectedId: number | null;
  onSelect: (e: NightEvent) => void;
}

const CTX_LABEL: Record<string, string> = {
  pressure: "Druck",
  epap: "EPAP",
  leak: "Leck",
  flow_limit: "FL",
  spo2: "SpO2",
};

export default function EventList({ events, types, contextChannels, selectedId, onSelect }: Props) {
  const codes = useMemo(() => [...new Set(events.map((e) => e.code))], [events]);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const shown = events.filter((e) => !hidden.has(e.code));
  if (!events.length) return <p className="muted">In dieser Nacht wurden keine Ereignisse aufgezeichnet.</p>;
  return (
    <div>
      <div className="row small" style={{ marginBottom: "0.5rem" }}>
        {codes.map((c) => (
          <label key={c} className="check">
            <input
              type="checkbox"
              checked={!hidden.has(c)}
              onChange={() => {
                const n = new Set(hidden);
                if (n.has(c)) n.delete(c);
                else n.add(c);
                setHidden(n);
              }}
            />
            <EventChip code={c} color={types[c]?.color} short={types[c]?.short} /> {types[c]?.name ?? c} ({events.filter((e) => e.code === c).length})
          </label>
        ))}
      </div>
      <div className="table-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
        <table className="table">
          <thead>
            <tr>
              <th>Uhrzeit</th>
              <th>Ereignis</th>
              <th className="num">Dauer</th>
              {contextChannels.map((c) => (
                <th key={c} className="num" title="Mittelwert während des Ereignisses">
                  {CTX_LABEL[c] ?? c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((e) => (
              <tr key={e.id} className={`clickable ${selectedId === e.id ? "selected" : ""}`} onClick={() => onSelect(e)}>
                <td className="mono">{clock(e.start_ms, true)}</td>
                <td>
                  <EventChip code={e.code} color={types[e.code]?.color} short={types[e.code]?.short} />{" "}
                  <span className="small">{types[e.code]?.name ?? e.label}</span>
                </td>
                <td className="num">{e.duration_s != null ? `${num(e.duration_s, 0)} s` : "–"}</td>
                {contextChannels.map((c) => (
                  <td key={c} className="num">
                    {num(e.context[c], c === "flow_limit" ? 2 : 1)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Klick auf ein Ereignis zoomt alle Diagramme auf diesen Zeitpunkt und markiert das Ereignis.</p>
    </div>
  );
}
