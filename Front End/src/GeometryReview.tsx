import { useState } from "react";
import { api, downloadText } from "./api";
import { SheetViewer } from "./SheetViewer";
import { Busy, ErrorNotice } from "./ui";
import { stockLabel } from "./stock-label";
import type { IndexResult } from "./types";

export function GeometryReview({
  result,
  onAccepted,
  onRejected,
}: {
  result: IndexResult;
  onAccepted: (result: IndexResult) => void;
  onRejected: () => void;
}) {
  const [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(""),
    [error, setError] = useState("");
  const act = async (accept: boolean) => {
    if (
      busy ||
      !result.review_id ||
      (accept && (!confirmed || result.review_blocked))
    )
      return;
    setBusy(
      accept
        ? "Accepting this exact reviewed geometry"
        : "Rejecting this capture",
    );
    setError("");
    try {
      if (accept) onAccepted(await api.acceptReview(result.review_id));
      else {
        await api.rejectReview(result.review_id);
        onRejected();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const f = result.review_fields;
  return (
    <section className="geometry-review">
      <div className="notice warning">
        <div>
          <strong>Review required · unavailable for planning</strong>
          <p>
            {f?.sheet_id} · {f?.material} · {f?.thickness_mm} mm ·{" "}
            {f?.location || "Location not set"}
          </p>
          <p>
            Compare the outline and every hole with the photograph. No hole
            measurements are required.
          </p>
        </div>
      </div>
      {result.review_blocked && (
        <ErrorNotice message="ERR_CAPTURE_TRUNCATED: The outline reaches the station edge." />
      )}
      <SheetViewer
        geometry={result.geometry}
        title="Review detected outline and holes"
        photo={
          result.review_image_base64 && result.review_frame
            ? {
                src: result.review_image_base64,
                width: result.review_frame.width_mm,
                height: result.review_frame.height_mm,
              }
            : undefined
        }
      />
      <p className="hint">
        {result.hole_count} detected cutout{result.hole_count === 1 ? "" : "s"}.
        Use Photo to compare the overlay; zoom to inspect edges. A hand, clamp,
        glare or overlapping sheet can hide material. Reject and recapture if
        the outline is uncertain.
      </p>
      <label className="checkbox-label review-confirm">
        <input
          type="checkbox"
          checked={confirmed}
          disabled={!!busy || result.review_blocked}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        The full outline and all holes match. The sheet was flat and
        unobstructed; the grade and thickness are correct.
      </label>
      <div className="action-row">
        <button
          className="button primary"
          disabled={!confirmed || !!busy || result.review_blocked}
          onClick={() => void act(true)}
        >
          Accept geometry & add stock
        </button>
        <button
          className="button secondary"
          disabled={!!busy}
          onClick={() => void act(false)}
        >
          Reject & recapture
        </button>
      </div>
      {busy && <Busy label={busy} />}
      <ErrorNotice message={error} />
    </section>
  );
}
export function StockLabelButton({ result }: { result: IndexResult }) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    result.saved_remnant && (
      <div>
        <button
          className="button secondary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              const current = (await api.inventory()).remnants.find(
                (stock) => stock.sheet_id === result.saved_remnant!.sheet_id,
              );
              if (!current)
                throw new Error(
                  "This stock ID is no longer listed. Inspect inventory before printing a label.",
                );
              downloadText(
                stockLabel(current),
                current.sheet_id + ".label.svg",
                "image/svg+xml",
              );
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Download stock label
        </button>
        <ErrorNotice message={error} />
      </div>
    )
  );
}
