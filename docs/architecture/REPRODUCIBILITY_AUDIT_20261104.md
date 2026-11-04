# Fresh-clone reproducibility audit — 4 November 2026

I audited a fresh clone of public revision `77ac7311bb630961d171205b625fb1183ff3b420`
before making these local changes. The clone used a new Python environment,
a clean npm install, empty audit storage and a separate frontend origin. My
recording workspace, its database and provider credentials were not used.

## Reproduced defects and narrow fixes

| Defect | Reproduction | Change and regression evidence |
| --- | --- | --- |
| A new nested warehouse path could not start | Selecting the documented new workspace path failed with SQLite `unable to open database file` when its parent directory did not exist. | Create the database parent before connecting; preserve lazy API creation and the `:memory:` special value. Tests open/reopen a nested database and verify health remains read-only. |
| Prompt material could disagree with selected stock | A copper prompt plus SS304 stock context could return `PARSED_OK` when a fixed offline model response supplied SS304. Grade detection discarded other generic material mentions. | Preserve distinct grade/family mentions and require clarification before inference when they conflict. Tests cover copper/SS304, acrylic/AL6061, SS316/SS304, steel/acrylic, plexiglass/SS304 and copper/steel, with zero model calls. Grade aliases remain accepted. |
| The documented benchmark-rendering entry point was not reproducible from a public clone | Calling the renderer without its private run argument raised `IndexError`; its original raw input files are intentionally unpublished. | Add public offline replay of the normalized archive and DXF fixtures. Give the private publisher an explicit CLI/help error. Tests reject changed scores, summaries, duplicate trials and changed fixture bytes; output cannot overwrite an existing file. |

The new tests failed before the corresponding fixes and passed afterward.
Twelve workspace/material cases and six archive-replay cases were added. Existing
assertions, frontend behavior and test timeouts were not weakened.

## Verification results

| Check | Result and scope |
| --- | --- |
| Fresh Python dependency installation | Pinned development requirements installed; `pip check` reported no broken requirements. |
| Fresh frontend dependency installation | `npm ci` succeeded from the public lockfile. |
| npm advisory check | Zero known vulnerabilities reported for the installed frontend lockfile on 4 November. This is not a Python dependency advisory scan. |
| Unchanged baseline | 261 backend tests and 60 frontend tests passed; TypeScript and Vite build passed. |
| Updated backend suite | **279 passed**, one existing Starlette/HTTPX deprecation warning. |
| Frontend checks | **60 passed across 12 files**, TypeScript and production build passed. Frontend source was unchanged by this audit. |
| Offline benchmark preparation | 20 cases: 15 complete orders and five reject/clarify cases; two DXF fixtures validated. |
| Public historical replay | 120 trials verified; preserved scores 50/60 for current-failover-at-the-time and 51/60 for parallel agreement; 182 provider requests including the historical pilot. No new provider calls. |
| Browser example | Recorded 28/28 synthetic layout loaded; path playback and verification details worked; no captured console errors/warnings. |
| Fresh browser workspace | Connected to isolated API and displayed empty inventory. |
| Real HTTP smoke check | Health, OpenAPI and API documentation loaded; sample mounting-plate DXF uploaded and three copies planned for each of GRBL and LinuxCNC. Both final programs passed software verification, saved plans were readable, inventory stayed unchanged. |
| Prepared emitter probes | Both checked-in emitters passed their offline preparation probes. |
| Example-generation script | Regenerated 28/28 parts with verified output; checked-in image and recording restored byte-for-byte afterward. |
| Python entry points | Backend, benchmark and script modules compiled successfully. |
| Documentation links | 149 relative Markdown/HTML file targets resolved; this does not assert external-site uptime. |

Local environment: Windows, Python 3.11.15, Node 25.2.1 and npm 11.6.2.
Hosted CI uses Windows, Python 3.11 and Node 22; local results above do not claim
a new hosted run. A vendor-managed Python installation was not registered with
the Windows `py` launcher, so the audit invoked its Python 3.11 executable
directly. The startup guide now explains that alternative.

## Reviewer commands

Install dependencies using the [startup guide](../LOCAL_STARTUP.md), then run:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m benchmarks.order_interpretation --prepare
.\.venv\Scripts\python.exe -m benchmarks.replay_report
```

In `Front End`, run `npm run check`. The [benchmark guide](../../benchmarks/README.md)
separates public historical replay from opt-in live evaluation and private
site publishing. Replay cannot establish current provider latency or accuracy.

## Evidence wording

- The machine claim is **“Emits software-verified G-code for GRBL and LinuxCNC
  profiles.”** Path playback is not controller simulation; no simulator-tested
  or physically cut claim was added.
- Metal evidence leads with the two photos and their expected **2 and 5 holes**.
  Broader glare conditions have not yet been characterized; metal dimensional
  accuracy was not inferred from hole counts.
- The [physical report](PHYSICAL_VALIDATION_20261030.md) now summarizes median
  error with its sample definition and identifies **7.32 mm as worst case**.
  The selected planning gap is disclosed separately from uncalibrated photo error.
- The [capture SOP](../CAPTURE_SOP.md) records measured station values. Camera,
  lighting, camera position and fixing details absent from the experiment record
  are explicitly marked not recorded; none were guessed.
- The linked full decision JSON had stale pending-implementation statuses; those now match the reviewed decision cards on the website. Historical benchmark observations were not changed.
- Project-authorship references use singular wording. Winner-source quotations,
  external URLs and the parser's support for customer prompts saying “we” are
  unchanged. The existing real-remnant demo remains near the top of the README.

## Limits of this audit

No paid SAM or order-model requests were rerun. Their dated evidence remains
separate. No machine was connected, no controller simulator ran, and no actual
cutting, production deployment or material-savings measurement was performed.
The checks establish the tested installation and behavior; they do not prove
that all possible inputs or environments are defect-free.
