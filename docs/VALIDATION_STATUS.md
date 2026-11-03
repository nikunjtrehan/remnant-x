# Current validation evidence

Reviewed on 3 November 2026. This page distinguishes the latest verified test
baseline from earlier integration and physical experiments.

## Latest local checks

The 3 November DXF fit-report change passed **232 offline backend tests**,
**56 frontend tests across 11 files**, TypeScript compilation and a Vite
production build. The backend suite reports the existing Starlette/HTTPX
deprecation warning. These tests use temporary databases and mocked model calls.
Eight new backend cases distinguish failed import from insufficient stock,
prove successful spillover, explain partial quantities and keep search failures
separate from geometric impossibility. See the [fit-report design](architecture/DXF_FIT_REPORT.md).

The preceding SAM targeting and recovery change passed 224 backend / 54 frontend
tests at its own revision; it is included in the newer suite above.

Separately, two live end-to-end capture requests used the original generic
`sheet` input and the supplied `ss304` material. Both resolved to `metal sheet`,
returned the expected **2 / 5 holes**, and remained pending review in a separate
temporary database. No user inventory was added or modified by these checks.
The [SAM prompt comparison](architecture/SAM_PROMPT_RECOVERY.md) records the
alternatives and their limits.

The [Checks workflow](../.github/workflows/checks.yml) runs on each push;
[published runs](https://github.com/nikunjtrehan/remnant-x/actions/workflows/checks.yml)
report the corresponding hosted results.

## Earlier hosted baseline: 31 October

[GitHub Actions run 41216278990](https://github.com/nikunjtrehan/remnant-x/actions/runs/41216278990)
completed successfully on **31 October 2026**, for source revision
[`1e1efbe`](https://github.com/nikunjtrehan/remnant-x/tree/1e1efbeff3320edb94c943d79058606cc5505ce3).
The actual job logs report:

| Check | Observed result |
| --- | --- |
| Offline backend tests | 211 passed, one deprecation warning |
| Frontend tests | 49 passed across 11 files |
| TypeScript compilation and Vite production build | Passed |
| Hosted environment | Windows, Python 3.11 and Node 22 |

These historical results were read from that successful run. They describe
the earlier source revision, not the new 3 November test totals above.

## Historical reports

The [30 October integration review](FINAL_READINESS.md) records **184 backend / 42
frontend** tests. Those figures describe that earlier revision. Its dependency
audit and browser exercise also retain their original date and scope.

The [physical validation](architecture/PHYSICAL_VALIDATION_20261030.md) records
two cardboard specimens and eight photographs, including blocked captures and
ground-truth corrections. It is evidence of image-derived geometry, not machine
qualification or uniform dimensional accuracy.

## Three-copy result

The [31 October nesting experiment](architecture/ROTATED_STOCK_NESTING.md)
used accepted physical-photo geometries and the original-size vendor part.
It placed **3/3 requested copies: one on Piece B and two on Piece A**.
Both final programs passed software verification, with zero reported cutting
path across existing stock holes or outside the supplied sheets. Inventory was
unchanged. This experiment is separate from the earlier contour measurement
image and from the recorded synthetic Example in the frontend.

Physical metal cutting, controller/process qualification, measured procurement
savings and equivalent-production utilization baselines remain unestablished.
