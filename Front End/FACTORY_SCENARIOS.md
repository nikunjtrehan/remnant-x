# Factory scenarios · desktop prototype

The operating sequence is **capture → calibration → analysis → visual acceptance
→ available stock → reviewed order → verified plan → operator-reported cut**.
Material grade and thickness come from stock records or the operator, never
from an inferred visual identity.

| Situation | Implemented response |
| --- | --- |
| A marker is hidden/cropped | Names the missing corner and ID, marks it red, blocks analysis and offers photo replacement or station setup |
| All markers are found but scale is inconsistent | Shows a calibration-specific error and setup guidance |
| Spare markers duplicate a station ID | Explains that exactly one marker of each station ID is required |
| Unreadable/oversized file or damaged ZIP | Import error retains other valid inputs; file/count/expanded-size limits apply |
| Disconnected sheets in a photo | Backend rejects the disconnected mask; photograph each remnant separately |
| Detected outline reaches the station edge | Review is blocked when geometry is within 1 mm of the calibrated frame edge; recapture the full sheet |
| Glare, shadows, blur, hands, clamps or overlapping sheets | Guided capture instructions and a zoomable photo/geometry overlay; the operator must reject uncertain boundaries |
| Bent/raised sheet | Capture guidance requires a flat, unobstructed sheet; this is an operator check |
| Wrong outline or missing hole | Pending geometry is unavailable for planning; reject and recapture/refine without measuring each hole |
| Mixed material/thickness batch | Per-photo metadata and visible batch defaults; metadata locks after analysis and is shown again during acceptance |
| Exact duplicate image under another filename/ID | Browser SHA-256 deduplication plus backend byte-hash checks across non-rejected reviewed scans |
| Different views of the same physical sheet | Use its existing physical stock ID; acceptance cannot replace an existing inventory ID |
| Worker must retrieve the correct sheet | Plan shows physical ID, exact grade, thickness and rack/slot; Inventory provides printable labels |
| Missing or contradictory job inputs | Backend clarification is retained and the editable request is preserved |
| Unsupported DXF or wrong declared units | Bounded loader rejects unsupported files; tray shows filename, millimetre dimensions and quantities |
| No compatible material or insufficient space | Exact-grade/thickness guidance; explicit unplaced counts and no partial-batch inventory update |
| One photo fails in a batch | Other valid photos can be analyzed; every geometry is accepted independently |
| Analysis response is lost | Recover the stable review ID; a completed result is reused without another model call |
| Browser refresh | Restore original files, metadata, job draft and workspace mode; no automatic paid work |
| Save/confirmation response is lost | Recover/retry the same review or plan; database acceptance and cut receipts are replay-safe |
| Another request changes stock after planning | Current-stock check blocks stale export; atomic confirmation rejects stale geometry/material/provenance across the whole batch |
| Program downloaded but no cutting happened | Download is distinct from completion; no inventory subtraction occurs on download |
| Operator reports cutting finished | Confirm the exact saved plan, require an explicit operator declaration, and update predicted stock atomically |
| Mouse wheel over a numeric field | Scrolling blurs numeric fields so quantities, thickness and process values are not changed by wheel scrolling |

## Limits that remain explicit

- Blur, glare, occlusion, overlap and flatness are **not automatically certified**.
  Their guidance and mandatory visual review do not replace measured quality
  thresholds or machine qualification. The border guard cannot reveal a hidden
  edge entirely inside the frame.
- Different photos with different new IDs cannot reliably be recognized as the
  same physical sheet. Physical labels and operator discipline are required.
- Recovery is local to the same browser origin and backend database. Browser
  data clearing removes unsent photos. Quota failures show a warning. A backend
  crash before storing a completed result may require an explicit retry.
- No factory-wide reservation/scheduling system is implemented. A current-stock
  check and stale rejection do not coordinate two operators physically starting
  cuts simultaneously.
- Operator-reported completion is not machine telemetry. Remaining material
  is predicted from verified geometry; no machine is controlled by this UI.
- Legacy direct API auto-save/commit contracts remain available for trusted
  clients, as documented in `WORKFLOW_GUIDE.md`.

## Evidence

The 30 October browser exercise used a separate database and explicit offline
perception. Three synthetic photos yielded two reviews and one missing-marker
rejection. Before acceptance, perception count was two and inventory count zero.
After browser refresh and accepting both reviews, those counts were two and two.
One review was recovered through Inventory. Location editing and a labelled SVG
download were checked. An uploaded DXF produced a 50-copy verified plan, survived
refresh, and used the saved plan for operator-confirmed stock update. A subsequent
simulated stock change blocked export and completion. No physical cut, live SAM
accuracy test or paid model request is claimed by this exercise.
