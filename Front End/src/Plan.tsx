import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  ChevronRight,
  FilePlus2,
  Layers2,
  Plus,
  Settings2,
  Trash2,
} from "lucide-react";
import { api } from "./api";
import { CuttingPlan } from "./CuttingPlan";
import { OrderEditor } from "./OrderEditor";
import { Busy, ErrorNotice, Field, Modal } from "./ui";
import { formatNumber, geometryPath, partDescription } from "./geometry";
import { loadOrderDraft, saveOrderDraft, listIntakeHistory } from "./recovery";
import type { IntakeHistory } from "./recovery";
import type {
  Order,
  PipelineResult,
  ProcessSettings,
  Remnant,
  Upload,
} from "./types";

const initialSettings: ProcessSettings = {
  machine_profile: "ISO_6983_GRBL",
  allow_demo_stock: false,
  lead_in_radius_mm: 0,
  cut_feedrate_mm_min: 1800,
  laser_power_s: 1000,
  pierce_delay_sec: 0.4,
};
interface Props {
  inventory: Remnant[];
  onInventoryChanged: () => void;
  onInventory: () => void;
  sample?: { order: Order; result: PipelineResult };
  example: boolean;
  onLive?: () => void;
}

export function Plan({
  inventory,
  onInventoryChanged,
  onInventory,
  sample,
  example,
  onLive,
}: Props) {
  const [batches, setBatches] = useState<IntakeHistory[]>([]);
  useEffect(() => {
    let mounted = true;
    void listIntakeHistory()
      .then((rows) => {
        if (mounted) setBatches(rows);
      })
      .catch(() => {
        if (mounted)
          setRecoveryNote(
            "Batch history could not be read. Use current inventory or reopen the scanner.",
          );
      });
    return () => {
      mounted = false;
    };
  }, [inventory]);
  const [inputMode, setInputMode] = useState<"prompt" | "parts">("prompt");
  const [prompt, setPrompt] = useState("");
  const [order, setOrder] = useState<Order | null>(null),
    [result, setResult] = useState<PipelineResult | null>(null);
  const [settings, setSettings] = useState(initialSettings);
  const [uploads, setUploads] = useState<(Upload & { quantity: number })[]>([]),
    [uploadErrors, setUploadErrors] = useState<string[]>([]);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(""),
    [trace, setTrace] = useState<Record<string, unknown> | null>(null);
  const [commitDialog, setCommitDialog] = useState(false),
    [committed, setCommitted] = useState(false);
  const [planId, setPlanId] = useState(""),
    [cutConfirmed, setCutConfirmed] = useState(false),
    [recoveryNote, setRecoveryNote] = useState("");
  const [restoredDraft, setRestoredDraft] = useState(false);
  const [dxfStockChoice, setDxfStockChoice] = useState("");
  const [dxfKerf, setDxfKerf] = useState(1);
  const dxfStocks = Array.from(new Map(inventory.filter(s =>
    (!settings.selected_sheet_ids || settings.selected_sheet_ids.includes(s.sheet_id)) &&
    (settings.allow_demo_stock || (!["demo", "local_threshold"].includes(s.inventory_source) && !s.sheet_id.startsWith("DEMO_")))
  ).map(s => [JSON.stringify([s.material, s.thickness_mm]), s])).entries());
  const dxfStock = dxfStocks.find(([key]) => key === dxfStockChoice) ??
    (dxfStocks.length === 1 ? dxfStocks[0] : undefined);
  useEffect(() => {
    if (!order) return;
    setUploads(old => {
      let changed = false;
      const next = old.map(upload => {
        const parts = order.parts.filter(p => p.shape_type === "dxf_file" && p.dxf_path === upload.dxf_path);
        const quantity = parts.reduce((n, p) => n + p.quantity, 0);
        if (!parts.length || quantity === upload.quantity) return upload;
        changed = true;
        return {...upload, quantity};
      });
      return changed ? next : old;
    });
  }, [order]);
  const uploadInput = useRef<HTMLInputElement>(null);
  // Example and live states stay separate. Switching modes never seeds inventory or starts inference.
  const shownResult = example ? (sample?.result ?? null) : result;
  const shownOrder = example ? (sample?.order ?? null) : order;
  const invalidate = () => {
    setResult(null);
    setCommitted(false);
    setError("");
    setPlanId("");
  };
  const editOrder = (next: Order) => {
    invalidate();
    setOrder(next);
  };
  const createOrder = () => {
    setOrder({
      order_id: `JOB_${Date.now().toString(36).toUpperCase()}`,
      material: "",
      thickness_mm: 3,
      kerf_mm: 1,
      parts: [],
    });
    setInputMode("parts");
    invalidate();
  };
  const parse = async () => {
    if (busy || !prompt.trim()) return;
    setBusy("Interpreting your manufacturing request");
    setError("");
    setOrder(null);
    invalidate();
    try {
      const files = uploads.map((u) => u.dxf_path);
      const parsed = uploads.length === 1 && dxfStock
        ? await api.parse(prompt, files, {
            material: dxfStock[1].material,
            thickness_mm: dxfStock[1].thickness_mm,
            kerf_mm: dxfKerf,
          })
        : await api.parse(prompt, files);
      setOrder(parsed.order);
      setTrace(parsed.llm_trace);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const uploadFiles = async (files: File[]) => {
    if (busy) return;
    setBusy(
      `Importing ${files.length} DXF file${files.length === 1 ? "" : "s"}`,
    );
    setUploadErrors([]);
    setError("");
    setOrder(null);
    invalidate();
    const additions: (Upload & { quantity: number })[] = [],
      failures: string[] = [];
    // Two uploads in flight keeps 100+ definitions usable without flooding the API.
    for (let i = 0; i < files.length; i += 2) {
      const responses = await Promise.allSettled(
        files.slice(i, i + 2).map((file) => api.upload(file)),
      );
      responses.forEach((response, j) => {
        if (response.status === "fulfilled")
          additions.push({ ...response.value, quantity: 1 });
        else
          failures.push(
            `${files[i + j].name}: ${response.reason instanceof Error ? response.reason.message : String(response.reason)}`,
          );
      });
    }
    setUploads((old) => [...old, ...additions]);
    setUploadErrors(failures);
    setBusy("");
  };
  const fromUploads = () => {
    editOrder({
      order_id: `DXF_${Date.now().toString(36).toUpperCase()}`,
      material: order?.material ?? dxfStock?.[1].material ?? "",
      thickness_mm: order?.thickness_mm ?? dxfStock?.[1].thickness_mm ?? 3,
      kerf_mm: order?.kerf_mm ?? dxfKerf,
      parts: uploads.map((u, i) => ({
        part_id: `DXF_${i + 1}`,
        shape_type: "dxf_file",
        quantity: u.quantity,
        dxf_path: u.dxf_path,
      })),
    });
    setInputMode("parts");
  };
  const run = async (commit = false) => {
    if (!order || busy || example) return;
    if (!commit && settings.selected_sheet_ids?.length === 0) {
      setError("Select at least one batch or use all compatible inventory.");
      return;
    }
    setError("");
    setBusy(
      commit
        ? "Recording completion of the exact reviewed program"
        : "Nesting and verifying your cutting plan",
    );
    if (!commit) setResult(null);
    setCommitted(false);
    setCommitDialog(false);
    try {
      if (commit && (!result?.plan_id || !cutConfirmed))
        throw new Error(
          "Confirm that the reviewed program was used and cutting completed.",
        );
      const id = planId || crypto.randomUUID();
      setPlanId(id);
      saveOrderDraft({
        prompt,
        order,
        settings,
        uploads,
        inputMode,
        planId: id,
        dxfStockChoice,
        dxfKerf,
      });
      const planned = commit
        ? await api.confirmPlan(result!.plan_id!)
        : await api.execute(order, settings, id);
      setResult(planned);
      if (planned.plan_id) setPlanId(planned.plan_id);
      if (planned.stale_inventory?.length) setPlanId("");
      setCommitted(commit);
      if (commit) onInventoryChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const recoverPlan = async (id = planId) => {
    if (!id) return;
    setBusy("Recovering the saved plan without nesting again");
    setError("");
    try {
      const recovered = await api.plan(id);
      setResult(recovered);
      setCommitted(!!recovered.operator_confirmed_at);
      if (recovered.stale_inventory?.length) setPlanId("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const validateDownload = async () => {
    if (!result?.plan_id) return false;
    setBusy("Checking current stock before program download");
    setError("");
    try {
      const current = await api.plan(result.plan_id);
      setResult(current);
      if (current.stale_inventory?.length) {
        setPlanId("");
        return false;
      }
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy("");
    }
  };
  useEffect(() => {
    const draft = loadOrderDraft<{
      prompt: string;
      order: Order | null;
      settings: ProcessSettings;
      uploads: (Upload & { quantity: number })[];
      inputMode: "prompt" | "parts";
      planId: string;
      dxfStockChoice?: string;
      dxfKerf?: number;
    }>();
    if (
      draft &&
      typeof draft.prompt === "string" &&
      draft.settings &&
      Array.isArray(draft.uploads)
    ) {
      setPrompt(draft.prompt);
      setOrder(draft.order);
      setSettings(draft.settings);
      setUploads(draft.uploads);
      setInputMode(draft.inputMode);
      setPlanId(draft.planId || "");
      setDxfStockChoice(draft.dxfStockChoice || "");
      setDxfKerf(draft.dxfKerf ?? draft.order?.kerf_mm ?? 1);
      setRecoveryNote(
        "Local job draft restored. Recover a saved plan or review the order before planning.",
      );
    }
    setRestoredDraft(true);
  }, []);
  useEffect(() => {
    if (!restoredDraft) return;
    if (
      !saveOrderDraft({ prompt, order, settings, uploads, inputMode, planId, dxfStockChoice, dxfKerf })
    )
      setRecoveryNote("Job recovery could not be saved. Keep this page open.");
  }, [prompt, order, settings, uploads, inputMode, planId, dxfStockChoice, dxfKerf, restoredDraft]);
  const inventoryFingerprint = JSON.stringify(
    inventory.map((s) => [
      s.sheet_id,
      s.material,
      s.thickness_mm,
      s.inventory_source,
      s.geometry,
    ]),
  );
  useEffect(() => {
    if (!committed) setResult(null);
  }, [inventoryFingerprint]);
  const compatible = shownOrder
    ? inventory.filter(
        (s) =>
          (!settings.selected_sheet_ids ||
            settings.selected_sheet_ids.includes(s.sheet_id)) &&
          s.material === shownOrder.material &&
          Math.abs(s.thickness_mm - shownOrder.thickness_mm) <= 0.01 &&
          (settings.allow_demo_stock ||
            (!["demo", "local_threshold"].includes(s.inventory_source) &&
              !s.sheet_id.startsWith("DEMO_"))),
      )
    : [];
  return (
    <>
      <div className="workspace-grid plan-grid">
        <section className="panel input-panel">
          <div className="panel-heading">
            <span className="step-number">01</span>
            <div>
              <h2>
                {example ? "A second life for this sheet." : "Your next job"}
              </h2>
              <p>
                {example
                  ? "A captured, verified example to explore."
                  : "Describe it. Review it. Make room for it."}
              </p>
            </div>
          </div>
          {!example && (
            <fieldset className="batch-stock-selection" disabled={!!busy}>
              <legend>Choose material for this job</legend>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={settings.selected_sheet_ids === undefined}
                  onChange={(e) => {
                    setSettings({
                      ...settings,
                      selected_sheet_ids: e.target.checked ? undefined : [],
                    });
                    invalidate();
                  }}
                />
                Use all compatible inventory
              </label>
              {batches.map((batch) => {
                const ids = batch.sheetIds.filter((id) =>
                  inventory.some((s) => s.sheet_id === id),
                );
                const chosen = settings.selected_sheet_ids;
                return (
                  <label key={batch.id} className="checkbox-label">
                    <input
                      type="checkbox"
                      disabled={!ids.length}
                      checked={
                        !!chosen &&
                        ids.length > 0 &&
                        ids.every((id) => chosen.includes(id))
                      }
                      onChange={(e) => {
                        const next = new Set(chosen || []);
                        ids.forEach((id) =>
                          e.target.checked ? next.add(id) : next.delete(id),
                        );
                        setSettings({
                          ...settings,
                          selected_sheet_ids: [...next],
                        });
                        invalidate();
                      }}
                    />
                    {batch.name} · {ids.length} available / {batch.count} photos
                  </label>
                );
              })}
              {settings.selected_sheet_ids?.length === 0 && (
                <p role="status">Select at least one batch before planning.</p>
              )}
              {settings.selected_sheet_ids && !batches.length && (
                <p className="hint">
                  Saved selection: {settings.selected_sheet_ids.join(", ")}
                </p>
              )}
              <p className="hint">
                Only accepted, currently available sheets from your selection
                can be used. Material and thickness still have to match. Batch
                names are saved in this browser.
              </p>
            </fieldset>
          )}
          {example && sample ? (
            <>
              <div className="example-note">
                <span className="badge neutral">Recorded example</span>
                <p>
                  A synthetic L-cutout sheet, planned by the actual backend.
                  Explore the geometry and the verified output.
                </p>
              </div>
              <div className="example-order-summary">
                <span className="eyebrow">THE JOB</span>
                <p>
                  Make a new run of plates, rings and discs from the material
                  that’s already here.
                </p>
                <div className="example-spec">
                  <span>
                    {sample.order.material}
                    <small>material</small>
                  </span>
                  <span>
                    {sample.order.thickness_mm} mm<small>thickness</small>
                  </span>
                  <span>
                    {sample.order.kerf_mm} mm<small>kerf clearance</small>
                  </span>
                </div>
              </div>
              <div className="example-parts">
                {sample.order.parts.map((p, i) => (
                  <div key={p.part_id}>
                    <span
                      className={`example-shape shape-${p.shape_type} color-${i % 5}`}
                    />
                    <div>
                      <strong>
                        {p.part_id[0] + p.part_id.slice(1).toLowerCase()}
                      </strong>
                      <small>{partDescription(p)}</small>
                    </div>
                    <span className="example-quantity">× {p.quantity}</span>
                  </div>
                ))}
              </div>
              <div className="example-photo-card">
                <img
                  src="/example/station.png"
                  alt="Synthetic source station for the recorded example"
                />
                <span>
                  THE STARTING MATERIAL{" "}
                  <small>1 remnant · 1 existing L-cutout</small>
                </span>
              </div>
              <p className="hint">
                Recorded local-threshold geometry on a synthetic image. Live
                scans use SAM 3.1. No inference runs when you explore this
                example.
              </p>
              <button className="button primary full" onClick={onLive}>
                Plan your own job <ArrowUpRight size={15} />
              </button>
            </>
          ) : (
            <>
              <div className="segmented-control">
                <button
                  className={inputMode === "prompt" ? "active" : ""}
                  disabled={!!busy}
                  onClick={() => setInputMode("prompt")}
                >
                  Describe a job
                </button>
                <button
                  className={inputMode === "parts" ? "active" : ""}
                  disabled={!!busy}
                  onClick={() => {
                    setInputMode("parts");
                    if (!order) createOrder();
                  }}
                >
                  Build parts list
                </button>
              </div>
              {inputMode === "prompt" && (
                <>
                  {uploads.length === 1 && (
                    <div className="dxf-stock-context">
                      <label className="field-label" htmlFor="dxf-stock">DXF material and thickness</label>
                      <select id="dxf-stock" disabled={!!busy} value={dxfStock?.[0] ?? ""}
                        onChange={e => { setDxfStockChoice(e.target.value); setOrder(null); invalidate(); }}>
                        {dxfStocks.length !== 1 && <option value="">Choose stock, or specify it in your prompt</option>}
                        {dxfStocks.map(([key, sheet]) => <option key={key} value={key}>{sheet.material} · {sheet.thickness_mm} mm</option>)}
                      </select>
                      <Field label="DXF kerf (mm)">
                        <input type="number" min="0" max="20" step="0.1" disabled={!!busy} value={dxfKerf}
                          onChange={e => { setDxfKerf(Number(e.target.value)); setOrder(null); invalidate(); }} />
                      </Field>
                      <p className="hint">{dxfStock
                        ? "This stock supplies material and thickness for your request. The DXF supplies the shape and size."
                        : "Choose material and thickness for a short request such as “Cut 10 copies of this.”"}</p>
                    </div>
                  )}
                  <label className="field-label" htmlFor="manufacturing-prompt">
                    Manufacturing request
                  </label>
                  <textarea
                    id="manufacturing-prompt"
                    disabled={!!busy}
                    value={prompt}
                    onChange={(e) => {
                      setPrompt(e.target.value);
                      setOrder(null);
                      setTrace(null);
                      invalidate();
                    }}
                    placeholder={
                      uploads.length === 1
                        ? "I want to cut 10 copies of this."
                        : "Cut 8 plates, 50 × 30 mm, and 4 discs, diameter 20 mm, from 3 mm steel. Kerf 1 mm."
                    }
                  />
                  <p className="hint">
                    {uploads.length === 1
                      ? "Attached: " + uploads[0].filename + ". Enter the number of copies; confirm the stock settings above."
                      : uploads.length > 1
                        ? "DXFs are attached. Use the parts list below to assign each file its own quantity."
                        : "Include quantity, dimensions, thickness and exact material grade."}
                  </p>
                  <button
                    className="button primary full"
                    disabled={!!busy || !prompt.trim()}
                    onClick={() => void parse()}
                  >
                    Review order <ChevronRight size={15} />
                  </button>
                </>
              )}
              <div className="divider" />
              <div className="upload-heading">
                <span className="eyebrow">VENDOR PARTS</span>
                <span className="muted">
                  {uploads.length
                    ? `${uploads.length} definitions`
                    : ".DXF · mm"}
                </span>
              </div>
              <input
                className="sr-only"
                type="file"
                ref={uploadInput}
                aria-label="Vendor DXF files"
                accept=".dxf"
                multiple
                disabled={!!busy}
                onChange={(e) => {
                  void uploadFiles(Array.from(e.target.files ?? []));
                  e.target.value = "";
                }}
              />
              <button
                className="dxf-drop"
                disabled={!!busy}
                onClick={() => uploadInput.current?.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  void uploadFiles(Array.from(e.dataTransfer.files));
                }}
              >
                <FilePlus2 size={18} />
                <span>
                  Add vendor DXFs<small>Choose or drop multiple files</small>
                </span>
                <Plus size={15} />
              </button>
              <div className="upload-tray">
                {uploads.map((u, i) => (
                  <div className="uploaded-part" key={u.dxf_path}>
                    <svg
                      viewBox={`${u.geometry.bounds[0] - 2} ${-u.geometry.bounds[3] - 2} ${u.geometry.bounds[2] - u.geometry.bounds[0] + 4} ${u.geometry.bounds[3] - u.geometry.bounds[1] + 4}`}
                      aria-label={`Geometry of ${u.filename}`}
                    >
                      <path
                        d={geometryPath(u.geometry)}
                        fill="#b7caa4"
                        fillRule="evenodd"
                      />
                    </svg>
                    <div>
                      <strong title={u.filename}>{u.filename}</strong>
                      {u.import_info && <small>
                        {u.import_info.source_units} → mm
                        {u.import_info.spline_count > 0 && (" · curves approximated at " + u.import_info.curve_tolerance_mm + " mm chord tolerance")}
                      </small>}
                      <small>
                        {u.hole_count} holes ·{" "}
                        {formatNumber(u.geometry.area_mm2 / 100)} cm²
                      </small>
                      <small>
                        {formatNumber(
                          u.geometry.bounds[2] - u.geometry.bounds[0],
                        )}{" "}
                        ×{" "}
                        {formatNumber(
                          u.geometry.bounds[3] - u.geometry.bounds[1],
                        )}{" "}
                        mm
                      </small>
                    </div>
                    <input
                      aria-label={`Quantity for ${u.filename} ${i + 1}`}
                      type="number"
                      min="1"
                      max="10000"
                      disabled={!!busy}
                      value={u.quantity || ""}
                      onChange={(e) => {
                        setUploads((old) =>
                          old.map((v, j) =>
                            i === j
                              ? { ...v, quantity: Number(e.target.value) }
                              : v,
                          ),
                        );
                        setOrder(null);
                        invalidate();
                      }}
                    />
                    <button
                      className="icon-button"
                      aria-label={`Remove upload ${u.filename} ${i + 1}`}
                      disabled={!!busy}
                      onClick={() => {
                        setUploads((old) => old.filter((_, j) => j !== i));
                        setOrder(null);
                        invalidate();
                      }}
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ))}
              </div>
              {!!uploads.length && (
                <>
                  <button
                    className="button secondary full"
                    disabled={
                      !!busy ||
                      uploads.some(
                        (u) =>
                          !Number.isInteger(u.quantity) ||
                          u.quantity < 1 ||
                          u.quantity > 10000,
                      )
                    }
                    onClick={fromUploads}
                  >
                    Use {uploads.reduce((n, u) => n + u.quantity, 0)} uploaded{" "}
                    {uploads.reduce((n, u) => n + u.quantity, 0) === 1 ? "part" : "parts"} <ChevronRight size={14} />
                  </button>
                  <button
                    className="text-button upload-prompt-link"
                    disabled={!!busy}
                    onClick={() => {
                      setInputMode("prompt");
                      setTimeout(
                        () =>
                          document
                            .getElementById("manufacturing-prompt")
                            ?.focus(),
                        0,
                      );
                    }}
                  >
                    Or describe this uploaded job in a prompt →
                  </button>
                  {uploads.length === 1 && (
                    <p className="hint">
                      Choose the DXF material and thickness above, then say
                      “I want to cut 10 copies of this.” Review the imported
                      dimensions and the order before planning.
                    </p>
                  )}
                </>
              )}
              <details className="contract-note">
                <summary>What DXF files can I use?</summary>
                <p>
                  One outer boundary with optional disjoint holes. Closed,
                  straight LWPOLYLINE or closed planar SPLINE contours, up to 5 MB
                  per file. Declared mm, cm, m and inch units convert to mm;
                  unitless files are treated as mm. Splines use a 0.05 mm chord
                  tolerance. Native circles, arcs, polyline bulges, blocks and
                  open contours are rejected. Review the imported size and holes.
                </p>
              </details>
              {!!uploadErrors.length && (
                <details open className="upload-failures">
                  <summary>
                    {uploadErrors.length} file
                    {uploadErrors.length === 1 ? "" : "s"} could not be imported
                  </summary>
                  {uploadErrors.map((e, i) => (
                    <p key={i}>{e}</p>
                  ))}
                </details>
              )}
              {order && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void run();
                  }}
                >
                  <div className="divider" />
                  <OrderEditor
                    uploadNames={Object.fromEntries(
                      uploads.map((u) => [u.dxf_path, u.filename]),
                    )}
                    order={order}
                    onChange={editOrder}
                    disabled={!!busy}
                  />
                  <details className="process-details">
                    <summary>
                      <SettingsIcon />
                      Controller & process settings
                    </summary>
                    <fieldset disabled={!!busy}>
                      <Field label="Controller profile">
                        <select
                          value={settings.machine_profile}
                          onChange={(e) => {
                            setSettings({
                              ...settings,
                              machine_profile: e.target
                                .value as ProcessSettings["machine_profile"],
                            });
                            invalidate();
                          }}
                        >
                          <option value="ISO_6983_GRBL">GRBL · ISO 6983</option>
                          <option value="LINUXCNC_LASER">
                            LinuxCNC · laser
                          </option>
                        </select>
                      </Field>
                      <div className="field-grid">
                        {(
                          [
                            "cut_feedrate_mm_min",
                            "laser_power_s",
                            "pierce_delay_sec",
                            "lead_in_radius_mm",
                          ] as const
                        ).map((key) => (
                          <Field
                            key={key}
                            label={
                              {
                                cut_feedrate_mm_min: "Feed (mm/min)",
                                laser_power_s: "Power (S)",
                                pierce_delay_sec: "Pierce delay (s)",
                                lead_in_radius_mm: "Lead-in radius (mm)",
                              }[key]
                            }
                          >
                            <input
                              required
                              type="number"
                              min={
                                key === "cut_feedrate_mm_min" ||
                                key === "laser_power_s"
                                  ? 1
                                  : 0
                              }
                              max={
                                {
                                  cut_feedrate_mm_min: 100000,
                                  laser_power_s: 1000,
                                  pierce_delay_sec: 60,
                                  lead_in_radius_mm: 10,
                                }[key]
                              }
                              step={key === "laser_power_s" ? 1 : 0.1}
                              value={settings[key]}
                              onChange={(e) => {
                                setSettings({
                                  ...settings,
                                  [key]: Number(e.target.value),
                                });
                                invalidate();
                              }}
                            />
                          </Field>
                        ))}
                      </div>
                      <p className="hint">
                        Defaults are demonstration settings. Qualify feed, power
                        and work origin for your equipment. Output follows
                        centerline contours.
                      </p>
                    </fieldset>
                  </details>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      disabled={!!busy}
                      checked={settings.allow_demo_stock}
                      onChange={(e) => {
                        setSettings({
                          ...settings,
                          allow_demo_stock: e.target.checked,
                        });
                        invalidate();
                      }}
                    />
                    Include demo / local-threshold stock
                  </label>
                  <div className="stock-availability">
                    <Layers2 size={14} />
                    <span>
                      {compatible.length} compatible sheets in current inventory
                    </span>
                    <button
                      type="button"
                      className="text-button"
                      onClick={onInventory}
                    >
                      View →
                    </button>
                  </div>
                  {!compatible.length && order.material.trim() && (
                    <div className="notice warning">
                      <div>
                        <strong>
                          No matching {order.thickness_mm} mm {order.material}{" "}
                          stock
                        </strong>
                        <p>
                          {inventory.length
                            ? "Other grades or thicknesses are not substituted. Check stock labels and add matching material, or revise this order."
                            : "Add an accepted remnant before planning this job."}
                        </p>
                        <button
                          type="button"
                          className="text-button"
                          onClick={onInventory}
                        >
                          Inspect inventory →
                        </button>
                      </div>
                    </div>
                  )}
                  <button
                    className="button primary full"
                    type="submit"
                    disabled={!!busy || !order.parts.length}
                  >
                    Nest & verify <ChevronRight size={15} />
                  </button>
                </form>
              )}
              {trace && (
                <details className="contract-note">
                  <summary>Order interpretation details</summary>
                  <pre>{JSON.stringify(trace, null, 2)}</pre>
                </details>
              )}
            </>
          )}
          {busy && <Busy label={busy} />}
          {!example && recoveryNote && (
            <p className="hint" role="status">
              {recoveryNote}
            </p>
          )}
          {!example && planId && (
            <button
              type="button"
              className="text-button"
              disabled={!!busy}
              onClick={() => void recoverPlan()}
            >
              Recover saved plan
            </button>
          )}
          <ErrorNotice message={error} />
        </section>
        <CuttingPlan
          result={shownResult}
          example={example}
          committed={committed}
          busy={busy}
          onCommit={() => {
            setCutConfirmed(false);
            setCommitDialog(true);
          }}
          onValidate={example ? undefined : validateDownload}
        />
      </div>
      {commitDialog && (
        <Modal
          title="Record completion of this exact cutting plan?"
          onClose={() => setCommitDialog(false)}
        >
          <p>
            This uses the exact saved layout and verified programs you reviewed.
            Inventory must still match the original sheets. Changed stock blocks
            the whole update and requires a new plan.
          </p>
          <p>
            Completion is reported by the operator. No machine is connected;
            remaining geometry is predicted from this verified program.
          </p>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={cutConfirmed}
              onChange={(e) => setCutConfirmed(e.target.checked)}
            />
            I used this exact program on the listed sheets and completed the
            cut.
          </label>
          <div className="modal-actions">
            <button
              className="button secondary"
              onClick={() => setCommitDialog(false)}
            >
              Keep preview
            </button>
            <button
              className="button primary"
              disabled={!cutConfirmed || !!busy}
              onClick={() => void run(true)}
            >
              Confirm completed cut & update stock
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
function SettingsIcon() {
  return <Settings2 size={13} />;
}
