import { useNavigate } from "react-router-dom";
import type { NightRow } from "../api/types";
import { dateDe, hm, num, weekday } from "../lib/format";
import { StatusDot } from "./ui";

interface Props {
  rows: NightRow[];
  selectable?: boolean;
  selected?: Set<number>;
  onToggle?: (id: number) => void;
  sort?: string;
  order?: "asc" | "desc";
  onSort?: (key: string) => void;
}

const COLS: { key: string; label: string; dec: number; title?: string }[] = [
  { key: "ahi", label: "AHI", dec: 2 },
  { key: "cai", label: "CAI", dec: 2 },
  { key: "oai", label: "OAI", dec: 2 },
  { key: "hi", label: "HI", dec: 2 },
  { key: "rera_index", label: "RERA", dec: 2 },
  { key: "leak.p95", label: "Leck 95%", dec: 1, title: "L/min" },
  { key: "pressure.median", label: "Druck Med.", dec: 1, title: "cmH2O" },
  { key: "pressure.p95", label: "Druck 95%", dec: 1, title: "cmH2O" },
  { key: "flow_limit.p95", label: "FL 95%", dec: 2 },
];

export default function NightTable({ rows, selectable, selected, onToggle, sort, order, onSort }: Props) {
  const nav = useNavigate();
  const arrow = (k: string) => (sort === k ? (order === "asc" ? " ▲" : " ▼") : "");
  const th = (k: string, label: string, title?: string, cls = "num") => (
    <th className={`${cls} ${onSort ? "sortable" : ""}`} title={title} onClick={() => onSort?.(k)}>
      {label}
      {arrow(k)}
    </th>
  );
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {selectable && <th aria-label="Auswahl" />}
            <th />
            {th("date", "Datum", undefined, "")}
            {th("usage", "Dauer")}
            {COLS.map((c) => th(c.key, c.label, c.title))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className={`clickable ${selected?.has(r.id) ? "selected" : ""}`} onClick={() => nav(`/nights/${r.id}`)}>
              {selectable && (
                <td onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" aria-label={`Nacht ${r.date} auswählen`} checked={selected?.has(r.id) ?? false} onChange={() => onToggle?.(r.id)} />
                </td>
              )}
              <td>
                <StatusDot status={r.status} />
              </td>
              <td className="nowrap">
                {weekday(r.date)} {dateDe(r.date)}
                {r.notes && <span title="Notiz vorhanden"> 📝</span>}
                {!r.has_detail && r.has_summary && (
                  <span className="badge" style={{ marginLeft: 6 }} title="Nur Tageszusammenfassung, keine Detaildaten">
                    Zusammenfassung
                  </span>
                )}
              </td>
              <td className="num">{hm(r.usage_h)}</td>
              {COLS.map((c) => (
                <td key={c.key} className="num">
                  {num(r.metrics[c.key], c.dec)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
