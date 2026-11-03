# Code audit — 3 November 2026

Changes were limited to reproduced defects and their regression tests. All 21
new audit cases fail against the original revision and pass against the fixes.
The tests used temporary warehouses, synthetic geometry and mocked models.
They did not alter the recording inventory or spend model credits.

| Reproduced defect | Narrow correction |
| --- | --- |
| Malformed numeric values could raise server errors; booleans could become measurements; enormous quantities could overflow. | Validate numeric conversion and quantity bounds before geometry. Treat unused null dimensions as omitted, without changing the caller's input. |
| Swapped unequal L-bracket dimensions passed the language guard despite describing a mirrored shape. | Allow width/height interchangeability for unlocked rectangles only. |
| Concurrent retries of one plan ID could collide on insertion. | Preserve one canonical saved plan; identical requests recover it, changed requests remain rejected. |
| Review-save retries could collide, and competing reviews could persist the same photograph twice. | Save/check reviews transactionally, retain request-hash checks and enforce the existing duplicate-photo rule at persistence. |
| Separate API workers could accept and reject one review inconsistently. | Protect rejection with the same SQLite write transaction used by acceptance; preserve one consistent review/stock outcome. |
| Fully consumed sheets appeared in available inventory. | Exclude zero-area records from availability queries while retaining historical records and receipts. |
| A contour or hole smaller than output precision could round to a point and still pass verification. | Reconstruct each emitted contour and reject invalid or zero-area polygons before export or plan save. |
| Thickness filtering used different tolerances depending on whether material was supplied. | Apply the existing ±0.01 mm compatibility tolerance consistently. |
| DXF context allowed 20 mm clearance while order validation allowed 15 mm. | Align the context schema and input bound with the existing 15 mm order limit. |
| A retried preview returning an existing completion receipt could be shown as uncompleted. | Keep the completed status and refresh inventory when that receipt is returned. |

`backend/tests/test_audit_regressions.py` contains 21 audit cases, including
identical/conflicting retries, cross-worker review actions, unchanged stock during previews and both legacy
and reviewed completion paths. `Front End/src/Plan.test.tsx` covers completed
receipt display. The earlier [JSON-recovery fix](ORDER_JSON_RECOVERY.md) remains
covered by eight backend cases and frontend error-guidance tests.

Final local verification: **261 backend tests**, **60 frontend tests across
12 files**, TypeScript compilation and production build. The frontend assertions
and five-second per-test limit were retained. Its worker count was reduced to
one after resource contention caused timeouts in unchanged tests on this Windows
machine. This setting affects tests, not application or model concurrency.

This audit does not certify a particular CNC controller, cutting process or
physical measurement accuracy. Existing documented qualification limits remain.
