import type {
  Health,
  IndexResult,
  Order,
  PipelineResult,
  Preflight,
  ProcessSettings,
  Remnant,
  ScanFields,
  Station,
  Upload,
} from "./types";

async function request<T>(
  path: string,
  body?: unknown,
  form?: FormData,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(
      `/api/v1/${path}`,
      body === undefined && !form
        ? {}
        : {
            method: "POST",
            headers: form ? {} : { "Content-Type": "application/json" },
            body: form ?? JSON.stringify(body),
          },
    );
  } catch {
    throw new Error(
      "Cannot reach the backend. Start the local API and retry. If a write was pending, refresh inventory before retrying.",
    );
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map(
                (e: { loc: string[]; msg: string }) =>
                  `${e.loc.slice(1).join(".")}: ${e.msg}`,
              )
              .join("; ")
          : `Backend returned HTTP ${response.status}. Check that the local API is running.`,
    );
  }
  return data as T;
}
export const stationPayload = (station: Station) => ({
  table_width_mm: (station.top + station.bottom) / 2,
  table_height_mm: (station.left + station.right) / 2,
  marker_size_mm: station.marker,
});
export const api = {
  health: () => request<Health>("health"),
  inventory: () => request<{ remnants: Remnant[] }>("remnants"),
  seed: () => request<{ remnants: Remnant[] }>("seed-demo-warehouse", {}),
  preflight: (image: string, station: Station) =>
    request<Preflight>("photo-preflight", {
      image_base64: image,
      ...stationPayload(station),
    }),
  index: (image: string, station: Station, fields: ScanFields) =>
    request<IndexResult>("index-remnant", {
      image_base64: image,
      ...stationPayload(station),
      ...fields,
      save_to_warehouse: true,
      segmentation_mode: "sam",
    }),
  parse: (prompt: string, uploads: string[]) =>
    request<{ order: Order; llm_trace: Record<string, unknown> }>(
      "parse-order",
      { prompt, uploaded_dxf_files: uploads },
    ),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Upload>("upload-dxf", undefined, form);
  },
  execute: (order: Order, settings: ProcessSettings, commit = false) =>
    request<PipelineResult>("execute-pipeline", {
      order,
      ...settings,
      commit_cuts_to_db: commit,
    }),
};
export function downloadText(
  text: string,
  filename: string,
  type = "text/plain",
) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename.replace(/[^a-zA-Z0-9_.-]/g, "_");
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export async function downloadDxf(path: string) {
  const name = path.split(/[\\/]/).pop() ?? "";
  const response = await fetch(`/api/v1/artifacts/${encodeURIComponent(name)}`);
  if (!response.ok)
    throw new Error(
      "This DXF is not available in the managed artifact folder. Download the geometry JSON instead, or index a new photo.",
    );
  downloadText(await response.text(), name, "application/dxf");
}
