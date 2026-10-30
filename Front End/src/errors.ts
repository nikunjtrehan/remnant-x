const guidance: Record<string, [string, string]> = {
  ERR_DUPLICATE_CAPTURE: [
    "This photograph was already analyzed",
    "Recover its saved review or inspect the existing stock record. A renamed file or a new stock ID does not make this a new sheet.",
  ],
  ERR_NO_MARKERS: [
    "No station markers detected",
    "Use a station photograph with markers 0–3 and their white borders visible. Move the camera back and retake the photo.",
  ],
  ERR_FIDUCIAL_OCCLUDED: [
    "All four markers must be visible",
    "Uncover the missing corner or move the camera back. Replace this photo; the other batch photos are kept.",
  ],
  ERR_DUPLICATE_FIDUCIAL: [
    "Duplicate station markers",
    "Keep exactly one marker of each ID 0–3 on the station. Remove spare marker sheets from view.",
  ],
  ERR_CALIBRATION_DRIFT: [
    "This photo could not be calibrated",
    "Retake an overhead photo with all marker squares and white borders clear. If the problem remains, check the selected station, spans and printed marker size.",
  ],
  ERR_INVALID_HOMOGRAPHY: [
    "The station cannot be calibrated",
    "Check marker placement and recapture with all four corners visible.",
  ],
  ERR_DECODE_IMAGE: [
    "This photo cannot be opened",
    "Choose a readable JPEG or PNG. Re-export a damaged image and try again.",
  ],
  ERR_MULTIPLE_SHEETS: [
    "Could not trace one complete remnant",
    "Photograph one whole remnant inside the calibrated station. Separate overlapping sheets; if an edge leaves the station, move it inside and retake the photo. Review any stray detected fragments.",
  ],
  ERR_SAM_OBJECT_SELECTION: [
    "Choose one sheet",
    "Use the region selector around the intended remnant, including its holes, or photograph it separately.",
  ],
  ERR_NO_SHEET_FOUND: [
    "No usable sheet was detected",
    "Check the photograph and the object description, select the intended region, or retake the photo.",
  ],
  ERR_SAM_NO_MATCH: [
    "No sheet matched the description",
    "Describe the visible sheet, select its region or recapture. No stock was added.",
  ],
  ERR_INVALID_MASK_TOPOLOGY: [
    "The outline could not be traced reliably",
    "Clear hands, clamps and glare from the outline and holes, then recapture. Do not accept uncertain geometry.",
  ],
  ERR_CAPTURE_TRUNCATED: [
    "The full sheet outline is not visible",
    "Move the sheet completely inside the calibrated station and recapture. This geometry cannot be accepted.",
  ],
  ERR_STOCK_ID_EXISTS: [
    "This physical stock ID already exists",
    "Inspect the existing inventory record. A second photo of the same sheet must not create new available stock.",
  ],
  ERR_REVIEW_INPUT_CHANGED: [
    "An earlier analysis must be recovered",
    "Recover or reject the saved review before changing this capture's inputs.",
  ],
  ERR_REVIEW_REJECTED: [
    "This capture was rejected",
    "Replace the photograph or refine the region and analyze it as a new review.",
  ],
  ERR_STALE_WAREHOUSE: [
    "Stock changed after this plan was created",
    "Refresh inventory and generate a new plan. Review its layout and program before cutting or updating stock.",
  ],
  ERR_STALE_WAREHOUSE_MATERIAL: [
    "The selected stock changed",
    "Refresh inventory and review a new plan with matching grade and thickness.",
  ],
  ERR_NO_COMPATIBLE_REMNANTS: [
    "No matching stock is available",
    "Add stock with the requested exact material grade and thickness, or revise the order. Different grades are not substituted.",
  ],
  ERR_PARTIAL_BATCH: [
    "The complete order does not fit",
    "Add compatible stock or revise the order. The placed subset is visible; remaining parts must be resolved before updating inventory.",
  ],
  ERR_UNSAFE_GCODE: [
    "The program did not pass verification",
    "Do not use this output. Review the job and process settings and generate a new verified plan.",
  ],
  ERR_SAM_TIMEOUT: [
    "Sheet analysis timed out",
    "Keep this photo in the queue. Recover completed analysis first; retry only if no result was saved.",
  ],
  ERR_SAM_HTTP: [
    "The segmentation service is unavailable",
    "Keep the photo and retry later. Other completed photos and reviews remain available.",
  ],
  ERR_SAM_NOT_CONFIGURED: [
    "Live segmentation is not configured",
    "The workstation administrator must configure Meta SAM access before live analysis.",
  ],
  ERR_INVALID_VENDOR_DXF: [
    "This DXF could not be imported",
    "Use closed straight LWPOLYLINE or closed planar SPLINE boundaries with contained holes. Supported units: mm, cm, m or inches. Check the exported CAD file.",
  ],
  ERR_UNMANAGED_DXF: [
    "The uploaded part file is unavailable",
    "Upload the DXF again, then review the quantities and dimensions before planning.",
  ],
};
export function errorGuidance(message: string) {
  const code = message.match(/ERR_[A-Z_]+/)?.[0] ?? "";
  const known = guidance[code];
  return {
    title: known?.[0] ?? "Let’s resolve this first.",
    body: known?.[1] ?? message.replace(/^ERR_[A-Z_]+:\s*/, ""),
    detail: known ? message : "",
  };
}
