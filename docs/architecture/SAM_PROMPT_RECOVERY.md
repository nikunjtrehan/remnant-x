# Material-aware SAM prompts and explicit recovery

Decision and live checks: **3 November 2026**.

## Problem

The capture interface used the generic concept `sheet`. On a real metal photo,
Meta returned HTTP 200 and a completed stream with no segmentation. This was a
valid zero-match response, not an expired key or failed request. Sending the
same full images with `metal sheet` produced the expected outlines and **two
and five holes**.

Meta documents both concrete noun phrases and spatial prompts. It explicitly
states that zero matches can produce a completed response with empty text.
The service does not explain why a particular concept failed to match.
See [Meta's SAM prompting guide](https://dev.meta.ai/docs/sam/segmenting).

## Decision

1. Use a concrete material description before the first SAM request. Metal
   uploads default to `metal sheet`; cardboard and acrylic have their own
   descriptions.
2. Resolve the legacy API description `sheet` using the **supplied** material.
   This also handles older saved queues. Preserve explicit custom descriptions
   and the exact material grade used for inventory matching.
3. Record the description actually sent to SAM in the segmentation trace.
4. After no match, offer an explicit material-description reset or optional
   region selection. Neither changing a description nor drawing a region
   automatically spends another inference request.
5. Keep mask validation and worker acceptance. Region prompts identify a
   location; SAM still supplies the outline and holes. No threshold mask,
   invented boundary, silent hole filling or island removal replaces SAM.

## Alternatives tested on the same two metal photos

The station used the existing measured configuration: 657.5 × 511.5 mm spans
and 48 mm black marker squares. These are diagnostic comparisons on two photos,
not a statistical accuracy or latency benchmark.

| Method | Photo 1 | Photo 2 | Decision |
| --- | --- | --- | --- |
| Full image, `metal sheet` | Expected two holes | Expected five holes | Keep as the normal metal path |
| SAM box prompt, without a text concept | False solid islands inside holes | False solid islands and incomplete holes | Both rejected by the existing disconnected-stock check; do not make this an automatic retry |
| Crop to the region, then `metal sheet` | Two real holes plus two false holes on black marker ink | Expected five holes | Do not add as the default recovery |

For the retained path, a second end-to-end API check deliberately submitted the
old `sheet` description with stock material `ss304`. The backend sent
`metal sheet`; both responses were HTTP 200, with **2 / 5 holes**, unblocked
**pending** reviews, and no saved stock. SAM request times in that check were
**5.55 / 5.96 seconds**. A separate temporary database kept the user's inventory
unchanged.

The box comparison found false solid islands of about **484.6 / 89.4 mm²**.
The cropped first image contained false holes of about **61.4 and 7.0 mm²** on
surface ink, despite passing topology validation. A mathematically valid mask
can still misunderstand the photograph. This is why visual review remains a
required step in the worker workflow.

## Scope of the evidence

These checks establish the observed behavior and hole counts for these photos.
The new metal specimens have no independent dimensional survey in this test.
They do not establish uniform millimetre accuracy, reliability on all metals,
machine qualification or guaranteed recovery from every failed segmentation.
The earlier [measured cardboard experiments](PHYSICAL_VALIDATION_20261030.md)
remain separate evidence.

Offline regressions cover the legacy material description, preserved custom
descriptions, spatial coordinates and object IDs, no hidden inference retry,
no stock after failure, and explicit acceptance after a recovered review.

## Implementation

- `backend/materials.py`: resolve only the legacy generic concept from the
  supplied material; preserve grade identity and explicit descriptions.
- `backend/api.py`: apply that resolution to capture requests, including old
  queue entries.
- `backend/sam_client.py`: record the effective prompt and validate spatial
  requests independently of text and previously selected object IDs.
- `Front End/src/Capture.tsx` and `PhotoBatch.tsx`: concrete defaults and
  explicit recovery for the selected failed photo, without repeating successful
  batch items.

The official [spatial-prompt protocol](https://github.com/meta-models/meta-sam/blob/main/protocol/sam3.md)
uses inclusive wire bounds; the application supplies half-open pixel bounds in
the rectified image. Text concepts and box tokens are alternative SAM prompt
types and are not combined in one request.
