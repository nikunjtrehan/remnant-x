import { useState } from "react";
import { ArrowUpRight, Boxes, RefreshCw, Search, ScanLine } from "lucide-react";
import { SheetViewer } from "./SheetViewer";
import { Busy, ErrorNotice, Modal } from "./ui";
import { api, downloadText } from "./api";
import { formatNumber } from "./geometry";
import type { Remnant } from "./types";

export function Inventory({
  remnants,
  loading,
  error,
  onRefresh,
  onScan,
  example,
}: {
  remnants: Remnant[];
  loading: boolean;
  error: string;
  onRefresh: () => void;
  onScan: () => void;
  example: boolean;
}) {
  const [query, setQuery] = useState(""),
    [selectedId, setSelectedId] = useState("");
  const [seedConfirm, setSeedConfirm] = useState(false),
    [seeding, setSeeding] = useState(false),
    [seedError, setSeedError] = useState("");
  const list = remnants.filter((r) =>
    `${r.sheet_id} ${r.material} ${r.thickness_mm}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const selected = list.find((r) => r.sheet_id === selectedId) ?? list[0];
  const seed = async () => {
    setSeeding(true);
    setSeedError("");
    try {
      await api.seed();
      setSeedConfirm(false);
      onRefresh();
    } catch (e) {
      setSeedError((e as Error).message);
    } finally {
      setSeeding(false);
    }
  };
  return (
    <>
      <div className="inventory-toolbar">
        <div className="search-field">
          <Search size={15} />
          <input
            aria-label="Search inventory"
            placeholder="Find a sheet, grade or thickness…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <span className="muted">
          {list.length} sheet{list.length === 1 ? "" : "s"}
        </span>
        <button
          className="button secondary"
          disabled={example || loading}
          onClick={onRefresh}
        >
          <RefreshCw size={14} />
          Refresh
        </button>
        <button className="button primary" onClick={onScan}>
          <ScanLine size={15} />
          Scan a remnant
        </button>
      </div>
      {loading && <Busy label="Retrieving warehouse inventory" />}
      <ErrorNotice message={error} />
      <div className="workspace-grid inventory-grid">
        <section className="panel inventory-list">
          <div className="inventory-list-head">
            <span className="eyebrow">
              {example ? "EXAMPLE STOCK" : "WAREHOUSE INVENTORY"}
            </span>
            <span className="mono">mm</span>
          </div>
          {list.map((r) => (
            <button
              className={`stock-row ${selected?.sheet_id === r.sheet_id ? "selected" : ""}`}
              key={r.sheet_id}
              onClick={() => setSelectedId(r.sheet_id)}
            >
              <span className="stock-glyph">
                <Boxes size={21} strokeWidth={1} />
              </span>
              <span>
                <strong>{r.sheet_id}</strong>
                <small>
                  {r.material} · {r.thickness_mm} mm · {r.hole_count} cutout
                  {r.hole_count === 1 ? "" : "s"}
                </small>
                <span className="stock-source">
                  {r.inventory_source === "sam"
                    ? "SAM 3.1 capture"
                    : r.inventory_source}
                </span>
              </span>
              <ArrowUpRight size={14} />
            </button>
          ))}
          {!list.length && (
            <div className="empty-list">
              <Boxes size={26} />
              <h3>
                {query ? "No matching sheets." : "Your inventory starts here."}
              </h3>
              <p>
                {query
                  ? "Try another grade or sheet ID."
                  : "Scan your first remnant, or explicitly load synthetic demo stock."}
              </p>
            </div>
          )}
          {!example && (
            <div className="inventory-seed">
              <button
                className="text-button"
                onClick={() => setSeedConfirm(true)}
              >
                Load synthetic demo stock →
              </button>
              <p>Three example sheets, clearly marked as demo.</p>
            </div>
          )}
        </section>
        <section className="panel canvas-panel">
          <div className="canvas-heading">
            <div>
              <span className="eyebrow">STOCK INSPECTION</span>
              <h2>{selected?.sheet_id ?? "No sheet selected"}</h2>
            </div>
            {selected && (
              <span className="badge neutral">
                {selected.material} · {selected.thickness_mm} mm
              </span>
            )}
          </div>
          <SheetViewer
            key={selected?.sheet_id}
            geometry={selected?.geometry}
            title="Inventory sheet geometry"
          />
          {selected && (
            <>
              <div className="metric-strip">
                <div>
                  <strong>
                    {formatNumber(selected.usable_area_mm2 / 100)}
                    <small> cm²</small>
                  </strong>
                  <span>usable material</span>
                </div>
                <div>
                  <strong>{selected.hole_count}</strong>
                  <span>existing cutouts</span>
                </div>
                <div>
                  <strong className="source-value">
                    {selected.inventory_source}
                  </strong>
                  <span>source of geometry</span>
                </div>
              </div>
              <div className="action-row">
                <button
                  className="button secondary"
                  onClick={() =>
                    downloadText(
                      JSON.stringify(selected, null, 2),
                      `${selected.sheet_id}.json`,
                      "application/json",
                    )
                  }
                >
                  Download sheet record <ArrowUpRight size={13} />
                </button>
              </div>
            </>
          )}
        </section>
      </div>
      {seedConfirm && (
        <Modal
          title="Load demonstration stock?"
          onClose={() => !seeding && setSeedConfirm(false)}
        >
          <p>
            This adds three synthetic sheets. Repeating this action resets the
            three DEMO_ records, including their predicted cut history. Your
            other stock is unaffected.
          </p>
          <p>
            Use a separate demo API database for demonstrations. Planning with
            these sheets also requires “Include demo stock”.
          </p>
          <ErrorNotice message={seedError} />
          {seeding && <Busy label="Loading demo stock" />}
          <div className="modal-actions">
            <button
              className="button secondary"
              disabled={seeding}
              onClick={() => setSeedConfirm(false)}
            >
              Keep current stock
            </button>
            <button
              className="button primary"
              disabled={seeding}
              onClick={() => void seed()}
            >
              Load 3 demo sheets
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
