import { useCallback, useEffect, useRef, useState } from "react";
import {
  Archive,
  CheckCircle2,
  ImagePlus,
  Pause,
  RefreshCw,
  ScanLine,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { Capture } from "./Capture";
import { api, downloadText } from "./api";
import { collectPhotos, readFile } from "./photo-import";
import type { SourcePhoto } from "./photo-import";
import { Busy, ErrorNotice, Field, loadLocal } from "./ui";
import { defaultStation, validStation } from "./station";
import type { IndexResult, Preflight, ScanFields, Station } from "./types";

type Status =
  | "unchecked"
  | "checking"
  | "ready"
  | "blocked"
  | "indexing"
  | "added"
  | "error";
interface Item extends SourcePhoto {
  id: string;
  fields: ScanFields;
  status: Status;
  check?: Preflight;
  result?: IndexResult;
  error?: string;
  revision: number;
}
const statusLabel: Record<Status, string> = {
  unchecked: "Needs check",
  checking: "Checking markers",
  ready: "Ready for SAM",
  blocked: "Photo needs attention",
  indexing: "SAM is analyzing",
  added: "Added to inventory",
  error: "Analysis not confirmed",
};
function PhotoThumb({ file }: { file: File }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    if (!URL.createObjectURL) return;
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  return url ? (
    <img src={url} alt="" loading="lazy" />
  ) : (
    <ImagePlus size={22} />
  );
}
export function PhotoBatch({
  onSaved,
  stationProfile,
  onStationProfileChange,
  onBusyChange,
}: {
  onSaved: () => void;
  stationProfile?: Station;
  onStationProfileChange?: (station: Station) => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const [items, setItems] = useState<Item[]>([]),
    [selectedId, setSelectedId] = useState("");
  const [station, setStation] = useState(
    () =>
      stationProfile ??
      loadLocal("remnantx.station.v1", defaultStation, validStation),
  );
  const [busy, setBusy] = useState(""),
    [issues, setIssues] = useState<string[]>([]),
    [error, setError] = useState("");
  const [defaults, setDefaults] = useState({ material: "", thickness: 3 }),
    [stopping, setStopping] = useState(false);
  const input = useRef<HTMLInputElement>(null),
    replaceId = useRef(""),
    active = useRef(false),
    stop = useRef(false);
  const selected = items.find((i) => i.id === selectedId) ?? items[0];
  const patch = (id: string, changes: Partial<Item>) =>
    setItems((old) => old.map((i) => (i.id === id ? { ...i, ...changes } : i)));
  const fieldsChanged = useCallback(
    (fields: ScanFields) =>
      setItems((old) =>
        old.map((i) =>
          i.id === selectedId &&
          JSON.stringify(i.fields) !== JSON.stringify(fields)
            ? { ...i, fields }
            : i,
        ),
      ),
    [selectedId],
  );
  const checked = useCallback(
    (check: Preflight) =>
      setItems((old) =>
        old.map((i) =>
          i.id === selectedId &&
          !["added", "indexing", "error"].includes(i.status)
            ? {
                ...i,
                check,
                status: check.ready ? "ready" : "blocked",
                error: "",
              }
            : i,
        ),
      ),
    [selectedId],
  );
  const changeStation = useCallback(
    (next: Station) => {
      setStation(next);
      onStationProfileChange?.(next);
      setItems((old) =>
        old.map((i) =>
          i.status === "added"
            ? i
            : {
                ...i,
                status: "unchecked",
                check: undefined,
                error: "",
                fields: { ...i.fields, segmentation_box_px: undefined },
              },
        ),
      );
    },
    [onStationProfileChange],
  );
  useEffect(() => {
    if (
      stationProfile &&
      JSON.stringify(stationProfile) !== JSON.stringify(station)
    )
      changeStation(stationProfile);
  }, [stationProfile, changeStation]);
  useEffect(() => {
    onBusyChange?.(!!busy);
  }, [busy, onBusyChange]);
  const importFiles = async (files: File[]) => {
    if (active.current || !files.length) return;
    active.current = true;
    setBusy("Opening photos and ZIP archives");
    setError("");
    try {
      const replacing = items.find((i) => i.id === replaceId.current);
      const imported = await collectPhotos(
        files,
        items.filter((i) => i.id !== replacing?.id),
      );
      setIssues(imported.issues);
      if (replacing) {
        if (imported.accepted.length !== 1) {
          setError("To replace a photo, choose exactly one JPEG or PNG.");
          return;
        }
        patch(replacing.id, {
          ...imported.accepted[0],
          status: "unchecked",
          check: undefined,
          result: undefined,
          error: "",
          revision: replacing.revision + 1,
          fields: { ...replacing.fields, segmentation_box_px: undefined },
        });
      } else {
        const rows = imported.accepted.map((source) => {
          const id = crypto.randomUUID();
          return {
            ...source,
            id,
            fields: {
              sheet_id: `REM_${id.replaceAll("-", "").slice(0, 16).toUpperCase()}`,
              material: defaults.material,
              thickness_mm: defaults.thickness,
              segmentation_concept: "sheet",
              use_clahe: false,
            },
            status: "unchecked" as const,
            revision: 0,
          };
        });
        setItems((old) => [...old, ...rows]);
        if (!selectedId && rows.length) setSelectedId(rows[0].id);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      active.current = false;
      setBusy("");
      replaceId.current = "";
    }
  };
  const checkAll = async () => {
    if (active.current) return;
    active.current = true;
    stop.current = false;
    setStopping(false);
    setError("");
    const pending = items.filter((i) => i.status !== "added");
    try {
      for (let n = 0; n < pending.length; n++) {
        if (stop.current) break;
        const item = pending[n];
        setBusy(
          `Checking photo ${n + 1} of ${pending.length}: ${item.file.name}`,
        );
        patch(item.id, { status: "checking", error: "" });
        try {
          const check = await api.preflight(
            await readFile(item.file, "url"),
            station,
          );
          patch(item.id, { check, status: check.ready ? "ready" : "blocked" });
        } catch (e) {
          patch(item.id, { status: "blocked", error: (e as Error).message });
        }
      }
    } finally {
      active.current = false;
      setBusy("");
      setStopping(false);
    }
  };
  const analyze = async (ids?: string[]) => {
    if (active.current) return;
    const ready = items.filter(
      (i) => i.status === "ready" && (!ids || ids.includes(i.id)),
    );
    const idsInQueue = items.map((i) => i.fields.sheet_id.trim());
    if (new Set(idsInQueue).size !== idsInQueue.length) {
      setError(
        "Every photo needs a different inventory ID. Inspect the affected photos and correct their IDs.",
      );
      return;
    }
    if (
      ready.some(
        (i) =>
          !i.fields.sheet_id.trim() ||
          !i.fields.material.trim() ||
          i.fields.thickness_mm < 0.1 ||
          i.fields.thickness_mm > 50 ||
          !Number.isFinite(i.fields.thickness_mm) ||
          !i.fields.segmentation_concept.trim(),
      )
    ) {
      setError(
        "Supply material / exact grade and valid thickness for every ready photo before analysis.",
      );
      return;
    }
    if (!ready.length) return;
    active.current = true;
    stop.current = false;
    setStopping(false);
    setError("");
    setBusy("Checking inventory IDs before analysis");
    try {
      const existing = await api.inventory();
      const collisions = ready.filter((item) =>
        existing.remnants.some(
          (stock) => stock.sheet_id === item.fields.sheet_id,
        ),
      );
      if (collisions.length)
        throw new Error(
          "An inventory ID already exists. Inspect current inventory and use a new ID before importing another sheet.",
        );
      for (let n = 0; n < ready.length; n++) {
        if (stop.current) break;
        const item = ready[n];
        setBusy(
          `Analyzing photo ${n + 1} of ${ready.length}: ${item.file.name}`,
        );
        patch(item.id, { status: "indexing", error: "" });
        try {
          const result = await api.index(
            await readFile(item.file, "url"),
            station,
            item.fields,
          );
          if (!result.saved_remnant)
            throw new Error(
              "Inventory save was not confirmed. Refresh inventory before retrying.",
            );
          patch(item.id, { status: "added", result });
          onSaved();
        } catch (e) {
          patch(item.id, { status: "error", error: (e as Error).message });
        }
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      active.current = false;
      setBusy("");
      setStopping(false);
    }
  };
  const counts = {
    ready: items.filter((i) => i.status === "ready").length,
    added: items.filter((i) => i.status === "added").length,
    attention: items.filter((i) => ["blocked", "error"].includes(i.status))
      .length,
  };
  return (
    <>
      <section className="panel batch-panel">
        <div className="batch-heading">
          <div>
            <span className="eyebrow">
              REMNANT INTAKE · MULTIPLE PHOTOS OR ZIP
            </span>
            <h2>A whole stack. One clear queue.</h2>
            <p>
              One station photo per distinct remnant. Check every photo before
              sending it to SAM.
            </p>
          </div>
          <span className="badge neutral">{items.length} / 50 photos</span>
        </div>
        <input
          ref={input}
          type="file"
          multiple
          className="sr-only"
          accept=".jpg,.jpeg,.png,.zip"
          aria-label="Batch station photos or ZIP"
          disabled={!!busy}
          onChange={(e) => {
            void importFiles(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
        <div className="batch-start">
          <button
            className="batch-drop"
            disabled={!!busy}
            onClick={() => {
              replaceId.current = "";
              input.current?.click();
            }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              void importFiles(Array.from(e.dataTransfer.files));
            }}
          >
            <UploadCloud size={24} />
            <span>
              <strong>Add photos or a ZIP</strong>
              <small>JPEG / PNG · 20 MB each · 100 MB per queue</small>
            </span>
            <Archive size={19} />
          </button>
          <form
            className="batch-defaults"
            onSubmit={(e) => {
              e.preventDefault();
              setItems((old) =>
                old.map((i) =>
                  i.status === "added"
                    ? i
                    : {
                        ...i,
                        fields: {
                          ...i.fields,
                          material: defaults.material,
                          thickness_mm: defaults.thickness,
                        },
                        revision: i.revision + 1,
                      },
                ),
              );
            }}
          >
            <Field label="Batch material / exact grade">
              <input
                required
                value={defaults.material}
                placeholder="e.g. ss304"
                disabled={!!busy}
                onChange={(e) =>
                  setDefaults({ ...defaults, material: e.target.value })
                }
              />
            </Field>
            <Field label="Batch thickness (mm)">
              <input
                type="number"
                required
                min="0.1"
                max="50"
                step="0.1"
                value={defaults.thickness || ""}
                disabled={!!busy}
                onChange={(e) =>
                  setDefaults({
                    ...defaults,
                    thickness: Number(e.target.value),
                  })
                }
              />
            </Field>
            <button
              className="button secondary"
              disabled={!!busy || !items.some((i) => i.status !== "added")}
            >
              Apply to pending photos
            </button>
          </form>
        </div>
        {!!issues.length && (
          <details open className="upload-failures">
            <summary>
              {issues.length} import notice{issues.length === 1 ? "" : "s"}
            </summary>
            {issues.map((issue, i) => (
              <p key={i}>{issue}</p>
            ))}
          </details>
        )}
        {!!items.length && (
          <>
            <div className="batch-actions">
              <button
                className="button secondary"
                disabled={!!busy || items.every((i) => i.status === "added")}
                onClick={() => void checkAll()}
              >
                <ScanLine size={15} />
                Check pending photos
              </button>
              <button
                className="button primary"
                disabled={!!busy || !counts.ready}
                onClick={() => void analyze()}
              >
                <CheckCircle2 size={15} />
                Analyze {counts.ready} ready photo
                {counts.ready === 1 ? "" : "s"}
              </button>
              {busy && (
                <button
                  className="button ghost"
                  disabled={stopping}
                  onClick={() => {
                    stop.current = true;
                    setStopping(true);
                  }}
                >
                  <Pause size={14} />
                  {stopping
                    ? "Stopping after current photo"
                    : "Stop after current photo"}
                </button>
              )}
              <span className="batch-counts" role="status">
                {counts.added} added · {counts.ready} ready · {counts.attention}{" "}
                need attention
              </span>
              <button
                className="text-button"
                onClick={() =>
                  downloadText(
                    JSON.stringify(
                      items.map(({ label, fields, status, error, result }) => ({
                        file: label,
                        ...fields,
                        status,
                        error,
                        saved_sheet_id: result?.saved_remnant?.sheet_id,
                      })),
                      null,
                      2,
                    ),
                    "photo-batch-report.json",
                    "application/json",
                  )
                }
              >
                Batch report ↓
              </button>
            </div>
            <div className="batch-queue" aria-label="Photo intake queue">
              {items.map((item, i) => (
                <div
                  className={`batch-row ${item.id === selected?.id ? "selected" : ""}`}
                  key={item.id}
                >
                  <button
                    className="batch-select"
                    aria-label={`Inspect photo ${i + 1}: ${item.file.name}`}
                    disabled={!!busy}
                    onClick={() => setSelectedId(item.id)}
                  >
                    <PhotoThumb file={item.file} />
                    <span>
                      <strong title={item.label}>{item.file.name}</strong>
                      <small>
                        {item.fields.material || "Set material"} ·{" "}
                        {item.fields.thickness_mm} mm
                      </small>
                      <span className={`batch-status status-${item.status}`}>
                        {statusLabel[item.status]}
                      </span>
                    </span>
                  </button>
                  <div className="batch-row-actions">
                    {item.status !== "added" && (
                      <button
                        className="icon-button"
                        aria-label={`Replace photo ${i + 1}`}
                        disabled={!!busy}
                        onClick={() => {
                          replaceId.current = item.id;
                          input.current?.click();
                        }}
                      >
                        <RefreshCw size={13} />
                      </button>
                    )}
                    <button
                      className="icon-button"
                      aria-label={`Remove photo ${i + 1} from queue`}
                      disabled={!!busy}
                      onClick={() => {
                        setItems((old) => old.filter((i) => i.id !== item.id));
                        if (selectedId === item.id)
                          setSelectedId(
                            items.find((i) => i.id !== item.id)?.id ?? "",
                          );
                      }}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <p className="hint">
              Each accepted photo is saved independently. Failed photos stay in
              the queue; successful ones are not repeated. Different photos of
              the same physical sheet must not be entered as separate stock.
            </p>
          </>
        )}
        {busy && <Busy label={busy} />}
        <ErrorNotice message={error} />
        {selected?.error && (
          <ErrorNotice
            message={`${selected.file.name}: ${selected.error}${selected.status === "error" ? " Refresh inventory before retrying; a failed response does not confirm that stock was unchanged." : ""}`}
          />
        )}
      </section>
      {selected && (
        <Capture
          key={`${selected.id}-${selected.revision}`}
          onSaved={onSaved}
          batch={{
            file: selected.file,
            fields: selected.fields,
            station,
            check: selected.check,
            result: selected.result,
            locked: !!busy || selected.status === "added",
            onFieldsChange: fieldsChanged,
            onStationChange: changeStation,
            onChecked: checked,
            onAnalyze: () => void analyze([selected.id]),
          }}
        />
      )}
    </>
  );
}
