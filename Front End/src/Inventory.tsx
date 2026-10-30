import { useEffect, useState } from "react";
import { ArrowUpRight, Boxes, RefreshCw, Search, ScanLine } from "lucide-react";
import { SheetViewer } from "./SheetViewer";
import { Busy, ErrorNotice, Modal, Field } from "./ui";
import { api, downloadText } from "./api";
import { formatNumber, geometrySourceLabel } from "./geometry";
import type { Remnant } from "./types";
import type { IndexResult } from "./types";
import { GeometryReview } from "./GeometryReview";
import { stockLabel } from "./stock-label";

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
  const [location, setLocation] = useState(""),
    [editing, setEditing] = useState(false),
    [stockError, setStockError] = useState("");
  const [reviewsOpen, setReviewsOpen] = useState(false),
    [reviews, setReviews] = useState<
      { review_id: string; fields: NonNullable<IndexResult["review_fields"]> }[]
    >([]);
  const [review, setReview] = useState<IndexResult | null>(null),
    [reviewBusy, setReviewBusy] = useState("");
  const list = remnants.filter((r) =>
    `${r.sheet_id} ${r.material} ${r.thickness_mm} ${r.location ?? ""}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const selected = list.find((r) => r.sheet_id === selectedId) ?? list[0];
  useEffect(() => {
    setLocation(selected?.location ?? "");
    setStockError("");
  }, [selected?.sheet_id, selected?.location]);
  const loadReviews = async () => {
    setReviewsOpen(true);
    setReviewBusy("Finding pending geometry reviews");
    setStockError("");
    try {
      setReviews((await api.reviews()).reviews);
    } catch (e) {
      setStockError((e as Error).message);
    } finally {
      setReviewBusy("");
    }
  };
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
        <button
          className="button secondary"
          disabled={example || loading}
          onClick={() => void loadReviews()}
        >
          Recover pending reviews
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
                  {geometrySourceLabel(r.inventory_source)}
                </span>
                <small>{r.location || "Location not set"}</small>
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
                    {geometrySourceLabel(selected.inventory_source)}
                  </strong>
                  <span>source of geometry</span>
                </div>
              </div>
              <div className="action-row">
                <button
                  className="button secondary"
                  onClick={() =>
                    downloadText(
                      stockLabel(selected),
                      selected.sheet_id + ".label.svg",
                      "image/svg+xml",
                    )
                  }
                >
                  Download printable stock label
                </button>
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
              {!example && (
                <form
                  className="stock-location"
                  onSubmit={(e) => {
                    e.preventDefault();
                    setEditing(true);
                    setStockError("");
                    void api
                      .location(selected.sheet_id, location)
                      .then(() => onRefresh())
                      .catch((err) => setStockError(err.message))
                      .finally(() => setEditing(false));
                  }}
                >
                  <Field label="Rack / storage location">
                    <input
                      value={location}
                      maxLength={120}
                      placeholder="e.g. Rack B / slot 3"
                      onChange={(e) => setLocation(e.target.value)}
                    />
                  </Field>
                  <button className="button secondary" disabled={editing}>
                    Save location
                  </button>
                  <p className="hint">
                    Write or attach this stock ID to the physical sheet. Match
                    the ID and location to the cutting plan before use.
                  </p>
                  <ErrorNotice message={stockError} />
                </form>
              )}
            </>
          )}
        </section>
      </div>
      {reviewsOpen && (
        <Modal
          title="Recover pending geometry reviews"
          onClose={() => {
            setReviewsOpen(false);
            setReview(null);
            setStockError("");
          }}
        >
          <p>
            These completed analyses are stored on this workstation's backend.
            Opening or accepting one does not call SAM again.
          </p>
          {reviewBusy && <Busy label={reviewBusy} />}
          <ErrorNotice message={stockError} />
          {!reviews.length && !reviewBusy && (
            <p>No geometry reviews are waiting.</p>
          )}
          <div className="review-inbox">
            {reviews.map((item) => (
              <button
                className="button secondary"
                key={item.review_id}
                disabled={!!reviewBusy}
                onClick={() => {
                  setReviewBusy("Loading saved geometry");
                  setStockError("");
                  void api
                    .review(item.review_id)
                    .then(setReview)
                    .catch((e) => setStockError(e.message))
                    .finally(() => setReviewBusy(""));
                }}
              >
                {item.fields.sheet_id} · {item.fields.material} ·{" "}
                {item.fields.thickness_mm} mm
              </button>
            ))}
          </div>
          {review && (
            <GeometryReview
              key={review.review_id}
              result={review}
              onAccepted={() => {
                setReviews((old) =>
                  old.filter((item) => item.review_id !== review.review_id),
                );
                setReview(null);
                onRefresh();
              }}
              onRejected={() => {
                setReviews((old) =>
                  old.filter((item) => item.review_id !== review.review_id),
                );
                setReview(null);
              }}
            />
          )}
        </Modal>
      )}
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
