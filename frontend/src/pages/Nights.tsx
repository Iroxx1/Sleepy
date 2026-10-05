import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { NightRow } from "../api/types";
import { useDevice } from "../hooks/useDevice";
import { Card, Empty, ErrorBox, Icon, Loading } from "../components/ui";
import NightTable from "../components/NightTable";

const EVENT_OPTS = [
  ["", "Alle"],
  ["OA", "Obstruktive Apnoe (OA)"],
  ["CA", "Zentrale Apnoe (CA)"],
  ["H", "Hypopnoe (H)"],
  ["UA", "Nicht klassifiziert (UA)"],
  ["RERA", "RERA"],
  ["CSR", "Cheyne-Stokes (CSR)"],
];

const FILTERS = ["from", "to", "ahi_min", "ahi_max", "leak_min", "leak_max", "pressure_min", "pressure_max", "usage_min", "usage_max", "event", "q"];

export default function Nights() {
  const { deviceId } = useDevice();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const [sort, setSort] = useState("date");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [qText, setQText] = useState(sp.get("q") || "");
  const [showFilters, setShowFilters] = useState(FILTERS.some((f) => f !== "q" && sp.get(f)));
  const [page, setPage] = useState(0);
  const pageSize = 100;

  const params: Record<string, string | number | null> = { device_id: deviceId, sort, order, offset: page * pageSize, limit: pageSize };
  for (const f of FILTERS) {
    const v = sp.get(f);
    if (v) params[f] = v;
  }
  const q = useQuery({
    queryKey: ["nights", params],
    queryFn: () => api.get<{ total: number; items: NightRow[] }>("/api/nights", params),
    placeholderData: keepPreviousData,
  });

  function setFilter(k: string, v: string) {
    const n = new URLSearchParams(sp);
    if (v) n.set(k, v);
    else n.delete(k);
    setSp(n, { replace: true });
    setPage(0);
  }

  function search(e: FormEvent) {
    e.preventDefault();
    setFilter("q", qText.trim());
  }

  function toggle(id: number) {
    const n = new Set(selected);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    setSelected(n);
  }

  function onSort(k: string) {
    if (sort === k) setOrder(order === "asc" ? "desc" : "asc");
    else {
      setSort(k);
      setOrder("desc");
    }
  }

  const field = (k: string, label: string, type = "number", step = "0.1") => (
    <label className="field">
      {label}
      <input type={type} step={step} value={sp.get(k) || ""} onChange={(e) => setFilter(k, e.target.value)} style={{ width: type === "date" ? 150 : 90 }} />
    </label>
  );

  return (
    <div className="stack">
      <Card>
        <form className="row" onSubmit={search}>
          <div className="row grow" style={{ position: "relative" }}>
            <input
              className="grow"
              placeholder="Suche, z. B. „ahi>5“, „event:CA 2026-09“, „usage<4h leak>20“"
              value={qText}
              onChange={(e) => setQText(e.target.value)}
              aria-label="Suche"
            />
          </div>
          <button className="primary" type="submit">
            <Icon name="search" size={16} /> Suchen
          </button>
          <button type="button" className={showFilters ? "active" : ""} onClick={() => setShowFilters(!showFilters)}>
            Filter
          </button>
          {[...sp.keys()].length > 0 && (
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setSp(new URLSearchParams(), { replace: true });
                setQText("");
              }}
            >
              Zurücksetzen
            </button>
          )}
        </form>
        <details className="search-help muted" style={{ marginTop: "0.5rem" }}>
          <summary>Suchsyntax</summary>
          <code>ahi&gt;5</code>, <code>ahi&gt;=2</code>, <code>cai&gt;1</code>, <code>leak&gt;20</code> (95 %-Leckage), <code>pressure&gt;10</code>,{" "}
          <code>usage&lt;4h</code>, <code>fl&gt;0.3</code>, <code>event:CA</code>, <code>event:OA&gt;=5</code>, <code>2026-09</code>,{" "}
          <code>2026-09-01..2026-09-15</code>, <code>device:SERIENNUMMER</code>, <code>notizen</code>. Begriffe werden UND-verknüpft.
        </details>
        {showFilters && (
          <div className="row" style={{ marginTop: "0.75rem", alignItems: "flex-end" }}>
            {field("from", "Von", "date")}
            {field("to", "Bis", "date")}
            {field("ahi_min", "AHI ≥")}
            {field("ahi_max", "AHI ≤")}
            {field("leak_min", "Leck 95% ≥")}
            {field("leak_max", "Leck 95% ≤")}
            {field("pressure_min", "Druck 95% ≥")}
            {field("pressure_max", "Druck 95% ≤")}
            {field("usage_min", "Nutzung ≥ h")}
            {field("usage_max", "Nutzung ≤ h")}
            <label className="field">
              Ereignistyp
              <select value={sp.get("event") || ""} onChange={(e) => setFilter("event", e.target.value)}>
                {EVENT_OPTS.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
      </Card>
      <Card
        title={`Nächte ${q.data ? `(${q.data.total})` : ""}`}
        actions={
          <button className="primary" disabled={selected.size < 2} onClick={() => nav(`/compare?ids=${[...selected].join(",")}`)}>
            {selected.size} Nächte vergleichen
          </button>
        }
      >
        <ErrorBox error={q.error} />
        {q.isLoading ? (
          <Loading />
        ) : q.data && q.data.items.length ? (
          <>
            <NightTable rows={q.data.items} selectable selected={selected} onToggle={toggle} sort={sort} order={order} onSort={onSort} />
            {q.data.total > pageSize && (
              <div className="row" style={{ marginTop: "0.75rem", justifyContent: "center" }}>
                <button disabled={page === 0} onClick={() => setPage(page - 1)}>
                  ← Zurück
                </button>
                <span className="muted small">
                  Seite {page + 1} / {Math.ceil(q.data.total / pageSize)}
                </span>
                <button disabled={(page + 1) * pageSize >= q.data.total} onClick={() => setPage(page + 1)}>
                  Weiter →
                </button>
              </div>
            )}
          </>
        ) : (
          <Empty>Keine Nächte gefunden.</Empty>
        )}
      </Card>
    </div>
  );
}
