import { useEffect, useRef, useState } from "react";
import {
  Check,
  CheckCircle2,
  ChevronRight,
  Download,
  ImagePlus,
  ScanLine,
  Settings2,
  UploadCloud,
} from "lucide-react";
import { api, downloadDxf, downloadText } from "./api";
import { SheetViewer } from "./SheetViewer";
import { PhotoRegion } from "./PhotoRegion";
import { Busy, ErrorNotice, Field, loadLocal } from "./ui";
import { formatNumber } from "./geometry";
import { defaultStation, validStation } from "./station";
import type { IndexResult, Preflight, ScanFields, Station } from "./types";

const locations = ["Top left", "Top right", "Bottom right", "Bottom left"];

export interface CaptureBinding {
  file: File;
  fields: ScanFields;
  station: Station;
  check?: Preflight;
  result?: IndexResult;
  locked: boolean;
  onFieldsChange: (fields: ScanFields) => void;
  onStationChange: (station: Station) => void;
  onChecked: (check: Preflight) => void;
  onAnalyze: () => void;
}
export function Capture({
  onSaved,
  batch,
  stationProfile,
  onStationProfileChange,
}: {
  onSaved: () => void;
  batch?: CaptureBinding;
  stationProfile?: Station;
  onStationProfileChange?: (station: Station) => void;
}) {
  const [station, setStation] = useState(
    () =>
      batch?.station ??
      stationProfile ??
      loadLocal("remnantx.station.v1", defaultStation, validStation),
  );
  const [image, setImage] = useState(""),
    [filename, setFilename] = useState("");
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [result, setResult] = useState<IndexResult | null>(null);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState("");
  const [sheetId, setSheetId] = useState(
    () =>
      batch?.fields.sheet_id ?? `REM_${Date.now().toString(36).toUpperCase()}`,
  );
  const [material, setMaterial] = useState(batch?.fields.material ?? ""),
    [thickness, setThickness] = useState(batch?.fields.thickness_mm ?? 3);
  const [concept, setConcept] = useState(
      batch?.fields.segmentation_concept ?? "sheet",
    ),
    [clahe, setClahe] = useState(batch?.fields.use_clahe ?? false),
    [rectified, setRectified] = useState(false);
  const [regionEnabled, setRegionEnabled] = useState(false),
    [box, setBox] = useState<number[] | null>(
      batch?.fields.segmentation_box_px ?? null,
    );
  const locked = !!busy || !!batch?.locked;
  const revision = useRef(0),
    photoInput = useRef<HTMLInputElement>(null);
  const check = async (photo: string, profile: Station, version: number) => {
    setBusy("Checking markers and calibration");
    setError("");
    try {
      const checked = await api.preflight(photo, profile);
      if (revision.current === version) setPreflight(checked);
      if (revision.current === version) batch?.onChecked(checked);
    } catch (e) {
      if (revision.current === version) setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const choosePhoto = async (file?: File) => {
    if (!file || busy) return;
    const version = ++revision.current;
    setPreflight(null);
    setResult(null);
    setError("");
    setRectified(false);
    setImage("");
    setFilename("");
    setBox(batch?.fields.segmentation_box_px ?? null);
    setRegionEnabled(false);
    if (!/\.(png|jpe?g)$/i.test(file.name) || file.size > 20_000_000) {
      setError("Choose a JPEG or PNG photo under 20 MB.");
      return;
    }
    setBusy("Reading photo");
    const reader = new FileReader();
    reader.onerror = () => {
      setError("Could not read this photo. Please choose it again.");
      setBusy("");
    };
    reader.onload = () => {
      if (revision.current !== version) return;
      const photo = reader.result as string;
      setImage(photo);
      setFilename(file.name);
      if (batch?.check) {
        setPreflight(batch.check);
        setBusy("");
      } else void check(photo, station, version);
    };
    reader.readAsDataURL(file);
  };
  useEffect(() => {
    if (batch) void choosePhoto(batch.file);
    return () => {
      revision.current++;
    };
  }, [batch?.file]);
  useEffect(() => {
    if (
      !batch?.result &&
      (batch?.station ?? stationProfile) &&
      JSON.stringify(batch?.station ?? stationProfile) !==
        JSON.stringify(station)
    )
      updateStation((batch?.station ?? stationProfile)!, false);
  }, [batch?.station, stationProfile]);
  useEffect(() => {
    if (batch) setPreflight(batch.check ?? null);
  }, [batch?.check]);
  useEffect(() => {
    if (batch?.result) setResult(batch.result);
  }, [batch?.result]);
  useEffect(() => {
    batch?.onFieldsChange({
      sheet_id: sheetId,
      material,
      thickness_mm: thickness,
      segmentation_concept: concept,
      use_clahe: clahe,
      ...(box ? { segmentation_box_px: box } : {}),
    });
  }, [sheetId, material, thickness, concept, clahe, box]);
  const updateStation = (next: Station, notify = true) => {
    revision.current++;
    setStation(next);
    setPreflight(null);
    setResult(null);
    setRectified(false);
    setError("");
    setBox(null);
    setRegionEnabled(false);
    if (notify) {
      batch?.onStationChange(next);
      onStationProfileChange?.(next);
    }
    try {
      localStorage.setItem("remnantx.station.v1", JSON.stringify(next));
    } catch {
      /* Current session still works without storage. */
    }
  };
  const analyze = async () => {
    if (!preflight?.ready || locked) return;
    if (batch) {
      batch.onAnalyze();
      return;
    }
    setBusy("SAM 3.1 is extracting the sheet and cutouts");
    setError("");
    try {
      const indexed = await api.index(image, station, {
        sheet_id: sheetId,
        material,
        thickness_mm: thickness,
        segmentation_concept: concept,
        use_clahe: clahe,
        ...(box ? { segmentation_box_px: box } : {}),
      });
      setResult(indexed);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  return (
    <div className="workspace-grid capture-grid">
      <section className="panel input-panel">
        <div className="panel-heading">
          <span className="step-number">01</span>
          <div>
            <h2>Start with a photograph.</h2>
            <p>All four corners. One flat sheet.</p>
          </div>
        </div>
        <details className="station-details">
          <summary>
            <Settings2 size={14} />
            <span>{station.name}</span>
            <span className="mono">Edit setup</span>
          </summary>
          <fieldset disabled={locked}>
            <Field label="Station name">
              <input
                value={station.name}
                onChange={(e) =>
                  updateStation({ ...station, name: e.target.value })
                }
              />
            </Field>
            <div className="field-grid">
              {(["top", "bottom", "left", "right", "marker"] as const).map(
                (key) => (
                  <Field
                    key={key}
                    label={`${key === "marker" ? "Black marker square" : `${key[0].toUpperCase()}${key.slice(1)} span`} (mm)`}
                  >
                    <input
                      type="number"
                      min="1"
                      max={key === "marker" ? 500 : 2000}
                      step="0.1"
                      value={station[key] || ""}
                      onChange={(e) =>
                        updateStation({
                          ...station,
                          [key]: Number(e.target.value),
                        })
                      }
                    />
                  </Field>
                ),
              )}
            </div>
          </fieldset>
          <p className="hint">
            Measure between outer black-square edges, excluding white borders.
            Opposite spans are averaged into the rectangular station model.
            Markers: 0 top-left, 1 top-right, 2 bottom-right, 3 bottom-left.
          </p>
        </details>
        <input
          className="sr-only"
          type="file"
          accept=".jpg,.jpeg,.png"
          ref={photoInput}
          aria-label="Station photo"
          disabled={locked}
          onChange={(e) => {
            void choosePhoto(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        {!batch && (
          <button
            className="photo-drop"
            disabled={locked}
            onClick={() => photoInput.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              void choosePhoto(e.dataTransfer.files[0]);
            }}
          >
            <UploadCloud size={27} />
            <strong>
              {image ? "Replace photograph" : "Choose a station photo"}
            </strong>
            <span>{filename || "Drop a JPEG or PNG · up to 20 MB"}</span>
          </button>
        )}
        {batch && (
          <div className="batch-inspector-label">
            <span className="eyebrow">SELECTED PHOTO</span>
            <strong>{filename || batch.file.name}</strong>
          </div>
        )}
        <div className="marker-checklist">
          {locations.map((location, id) => {
            const found =
              preflight?.detected_ids.includes(id) &&
              !preflight.duplicate_ids.includes(id);
            return (
              <div
                className={found ? "marker-check found" : "marker-check"}
                key={id}
              >
                <span className="marker-id">{id}</span>
                <div>
                  {location}
                  <small>{found ? "Detected" : "Required"}</small>
                </div>
                {found && <Check size={13} />}
              </div>
            );
          })}
        </div>
        {preflight && (
          <div
            className={`notice ${preflight.ready ? "success" : "warning"}`}
            role="status"
          >
            {preflight.ready ? (
              <CheckCircle2 size={17} />
            ) : (
              <ScanLine size={17} />
            )}
            <div>
              <strong>
                {preflight.ready
                  ? "Ready for analysis"
                  : `${preflight.detected_ids.length} of 4 station markers detected`}
              </strong>
              <p>
                {preflight.ready
                  ? `Marker drift ${preflight.scale_drift_mm} mm. Calibration consistency check passed.`
                  : preflight.issues.map((i) => i.message).join(" ")}
              </p>
              {!preflight.ready && (
                <p>
                  Keep every marker and its white border visible. Replace the
                  photo or correct the station setup.
                </p>
              )}
            </div>
          </div>
        )}
        {image && !preflight && !busy && (
          <button
            className="button secondary full"
            onClick={() => void check(image, station, revision.current)}
          >
            Check photograph <ChevronRight size={15} />
          </button>
        )}
        {preflight?.ready && !result && (
          <div className="region-controls">
            <button
              className="text-button"
              disabled={locked}
              onClick={() => {
                setRectified(true);
                setRegionEnabled((v) => !v);
              }}
            >
              {regionEnabled
                ? "Finish region selection"
                : "Select a sheet region (optional)"}{" "}
              →
            </button>
            {box && (
              <button
                className="text-button"
                disabled={locked}
                onClick={() => setBox(null)}
              >
                Clear region
              </button>
            )}
            <p className="hint">
              {box
                ? "A region prompt will replace the text concept for SAM."
                : regionEnabled
                  ? "Drag around the sheet in the rectified view, keeping its holes inside."
                  : "If the scene is ambiguous, target the intended sheet before analysis."}
            </p>
          </div>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void analyze();
          }}
        >
          <fieldset disabled={locked || !!result}>
            <div className="divider" />
            <Field label="Inventory ID">
              <input
                required
                value={sheetId}
                maxLength={120}
                onChange={(e) => setSheetId(e.target.value)}
              />
            </Field>
            <div className="field-grid">
              <Field label="Material / exact grade">
                <input
                  required
                  placeholder="e.g. ss304, cardboard"
                  value={material}
                  onChange={(e) => setMaterial(e.target.value)}
                />
              </Field>
              <Field label="Thickness (mm)">
                <input
                  required
                  type="number"
                  min="0.1"
                  max="50"
                  step="0.1"
                  value={thickness || ""}
                  onChange={(e) => setThickness(Number(e.target.value))}
                />
              </Field>
            </div>
            <Field label="What should SAM find?">
              <input
                required
                value={concept}
                placeholder="e.g. cardboard sheet"
                onChange={(e) => setConcept(e.target.value)}
              />
            </Field>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={clahe}
                onChange={(e) => setClahe(e.target.checked)}
              />
              Normalize lighting with CLAHE{" "}
              <span className="muted">Optional</span>
            </label>
            <p className="hint">
              Analysis sends the rectified photo to Meta SAM 3.1 and adds the
              accepted geometry to inventory. Existing holes need no manual
              measurements.
            </p>
            <button
              className="button primary full"
              disabled={!preflight?.ready || locked || !!result}
              type="submit"
            >
              <ScanLine size={15} />
              Analyze & add to inventory
            </button>
          </fieldset>
        </form>
        {busy && <Busy label={busy} />}
        <ErrorNotice message={error} />
        {result && (
          <div className="notice success">
            <CheckCircle2 size={17} />
            <div>
              <strong>Added to inventory</strong>
              <p>
                {result.saved_remnant?.sheet_id} · {result.hole_count} cutout
                {result.hole_count === 1 ? "" : "s"} preserved
              </p>
              {!batch && (
                <button
                  className="text-button"
                  onClick={() => {
                    setResult(null);
                    setSheetId(`REM_${Date.now().toString(36).toUpperCase()}`);
                    setImage("");
                    setPreflight(null);
                    setFilename("");
                  }}
                >
                  Scan another remnant →
                </button>
              )}
            </div>
          </div>
        )}
      </section>
      <section className="panel canvas-panel">
        <div className="canvas-heading">
          <div>
            <span className="eyebrow">
              {result ? "INDEXED GEOMETRY" : "CAPTURE WORKSPACE"}
            </span>
            <h2>
              {result
                ? "Every cutout accounted for."
                : image
                  ? "A good capture starts at the corners."
                  : "Give your offcut a second life."}
            </h2>
          </div>
          <span className="badge neutral">
            {result
              ? result.saved_remnant?.inventory_source === "sam"
                ? "SAM 3.1"
                : (result.saved_remnant?.inventory_source?.replaceAll(
                    "_",
                    " ",
                  ) ?? "Indexed geometry")
              : "Live capture"}
          </span>
        </div>
        {result ? (
          <>
            <SheetViewer
              geometry={result.geometry}
              title="Indexed remnant geometry"
            />
            <div className="metric-strip">
              <div>
                <strong>{result.hole_count}</strong>
                <span>existing cutouts</span>
              </div>
              <div>
                <strong>
                  {formatNumber(result.usable_area_mm2 / 100, 1)}{" "}
                  <small>cm²</small>
                </strong>
                <span>usable material</span>
              </div>
              <div>
                <strong>
                  {formatNumber(result.timings_ms.total_ms / 1000)}{" "}
                  <small>s</small>
                </strong>
                <span>analysis time</span>
              </div>
            </div>
            <div className="action-row">
              <button
                className="button secondary"
                onClick={() =>
                  void downloadDxf(result.dxf_path).catch((e) =>
                    setError(e.message),
                  )
                }
              >
                <Download size={14} />
                Sheet DXF
              </button>
              <button
                className="button ghost"
                onClick={() =>
                  downloadText(
                    JSON.stringify(result.geometry, null, 2),
                    "remnant-geometry.json",
                    "application/json",
                  )
                }
              >
                Geometry JSON
              </button>
            </div>
          </>
        ) : image ? (
          <>
            <div className="photo-tabs">
              <button
                className={!rectified ? "active" : ""}
                onClick={() => setRectified(false)}
              >
                Original photo
              </button>
              <button
                disabled={!preflight?.ready}
                className={rectified ? "active" : ""}
                onClick={() => setRectified(true)}
              >
                Rectified station
              </button>
            </div>
            <div className="photo-preview">
              <img
                src={rectified ? preflight?.rectified_image_base64 : image}
                alt={
                  rectified
                    ? "Perspective-corrected indexing station"
                    : "Selected indexing station photograph"
                }
              />
              {preflight && !rectified && (
                <svg
                  aria-label="Detected marker outlines"
                  viewBox={`0 0 ${preflight.image_width_px} ${preflight.image_height_px}`}
                  preserveAspectRatio="xMidYMid meet"
                >
                  {preflight.markers.map((m, i) => (
                    <g key={i}>
                      <polygon
                        points={m.corners_px.map((p) => p.join(",")).join(" ")}
                        fill="#b9e78422"
                        stroke="#c2ef86"
                        strokeWidth={4}
                      />
                      <text
                        x={m.corners_px[0][0]}
                        y={m.corners_px[0][1] - 10}
                        fill="#d9ffad"
                        stroke="#143b24"
                        strokeWidth={0.8}
                        fontSize={25}
                        fontWeight="700"
                      >
                        ID {m.id}
                      </text>
                    </g>
                  ))}
                </svg>
              )}
              {rectified && preflight?.frame && (
                <PhotoRegion
                  width={preflight.frame.width_px}
                  height={preflight.frame.height_px}
                  enabled={regionEnabled && !locked}
                  box={box}
                  onChange={setBox}
                />
              )}
            </div>
          </>
        ) : (
          <div className="photo-empty">
            <ImagePlus size={49} strokeWidth={1} />
            <h3>Four markers. One photograph.</h3>
            <p>
              Place the remnant flat on your station.
              <br />
              Keep markers 0–3 and their white borders visible.
            </p>
            <div className="station-diagram">
              <span>0</span>
              <span>1</span>
              <i />
              <span>3</span>
              <span>2</span>
            </div>
          </div>
        )}
        <div className="canvas-caption">
          <span className="pulse-square" />
          {result
            ? "Geometry is in the station frame. Reindex after moving the sheet."
            : "Marker checks run locally on the backend. SAM is called only when you analyze."}
        </div>
      </section>
    </div>
  );
}
