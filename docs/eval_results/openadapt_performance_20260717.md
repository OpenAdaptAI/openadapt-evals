# OpenAdapt performance evidence — 2026-07-17

This report separates the latest qualified compiled-runtime candidate evidence from historical demo-conditioned agent evidence.

## Latest qualified compiler/runtime candidate: compiled versus API

| Application | Arm | Condition | Runs | Success | Silent incorrect | Over-halt | Mean | p50 | p95 | Model calls | Cost |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| frappe_lending | compiled | baseline | 3 | 3/3 | 0 | 0 | 20.82s | 20.81s | 21.76s | 0 | $0.00 |
| frappe_lending | compiled | ui_cosmetic_v1 | 3 | 3/3 | 0 | 0 | 34.71s | 39.10s | 46.72s | 0 | $0.00 |
| frappe_lending | api | baseline | 3 | 3/3 | 0 | 0 | 0.98s | 1.00s | 1.03s | 0 | $0.00 |
| frappe_lending | api | ui_cosmetic_v1 | 3 | 3/3 | 0 | 0 | 0.98s | 0.95s | 1.05s | 0 | $0.00 |
| openemr_local | compiled | baseline | 3 | 3/3 | 0 | 0 | 36.32s | 35.97s | 37.26s | 0 | $0.00 |
| openemr_local | compiled | ui_cosmetic_v1 | 3 | 3/3 | 0 | 0 | 37.26s | 37.17s | 37.48s | 0 | $0.00 |
| openemr_local | api | baseline | 3 | 3/3 | 0 | 0 | 2.27s | 2.26s | 2.34s | 0 | $0.00 |
| openemr_local | api | ui_cosmetic_v1 | 3 | 3/3 | 0 | 0 | 2.30s | 2.30s | 2.35s | 0 | $0.00 |

Compiled execution passed 12/12 and averaged 32.28s; API control passed 12/12 and averaged 1.63s. The compiled GUI path was 19.8× slower. Both had zero measured silent incorrect success, over-halt, model calls, and model cost.

This is a complete model-free subset, not a complete comparative matrix: the paid/zero-shot agent arm was intentionally omitted, and both source artifacts mark `publication_ready=false`.
The artifacts were generated at Flow candidate `84c7a94`. Exact current Flow 1.12.1 changed shared replayer/effect code afterward, so its requalification remains pending.

Classification: silent incorrect success means the arm reported completion but the independent oracle failed; over-halt means the oracle passed without a completion claim. p95 uses nearest rank.

## Historical legacy agent: DC versus zero-shot

| Condition | Runs | Success | Silent incorrect | Over-halt | Mean | p50 | p95 | Mean steps |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ZS | 12 | 3/12 | 5 | 0 | 84.37s | 78.47s | 132.04s | 9.75 |
| DC | 12 | 3/12 | 6 | 0 | 71.37s | 64.68s | 116.80s | 9.25 |

Both historical arms passed 3/12 (25%), so DC − ZS was 0 percentage points. DC reduced mean wall time from 84.37s to 71.37s, but silent incorrect successes rose from 5/12 to 6/12. This is legacy Claude computer use, not current compiled Flow.

## What remains unmeasured

- Current compiled Flow versus zero-shot on WAA: no valid result.
- Exact current Flow 1.12.1 on the matched Frappe/OpenEMR matrix: requalification pending.
- Current paid agent arm on the matched Frappe/OpenEMR matrix: intentionally omitted.
- A real design-partner Windows/Citrix workflow: not represented here.

## Caveats

- Frappe and OpenEMR tasks use synthetic records on one macOS host.
- The current study measures one workflow per application and cosmetic drift only.
- Direct API controls are expected to be faster and are the preferred actuation tier when available.
- The historical WAA study used a legacy computer-use architecture, not the current compiler/runtime.
- The model-free compiler/runtime artifacts qualify candidate 84c7a94, not exact current Flow 1.12.1.
- Primary screenshots and oracle-evidence files remain in the ignored local Flow worktree; this report preserves normalized rows and their hashes, not those files.
- Legacy model ID, token usage, and dollar cost are unavailable in the retained artifacts.
- No new GUI, cloud, or model runs were performed for this report.

The JSON companion contains every normalized row and SHA-256 hashes for all source artifacts.
