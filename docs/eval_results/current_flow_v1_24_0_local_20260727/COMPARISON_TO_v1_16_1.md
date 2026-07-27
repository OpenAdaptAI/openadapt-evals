# Flow 1.24.0 versus the published 1.16.1 evidence

The comparison in `docs/eval_results/current_flow_v1_16_1_local_20260718` was
still the published result eight minor releases later. This directory re-runs it
against the current published wheel with the **byte-identical runner** (SHA-256
`ac58c0b9a02cfc991144a1f5c7a2814c6b6b748bcba27b87f8e1027ee575970f`), the same
task, the same arm-independent oracle, the same three trials per cell, and no
retries. Nothing about the methodology was changed to suit the numbers.

## Exact binding

| | 1.16.1 (published 2026-07-18) | 1.24.0 (this run, 2026-07-27) |
|---|---|---|
| Flow version | `1.16.1` | `1.24.0` |
| Flow commit | `113ce992b491576d77236f495b983165ce7a63bd` | `4ca7566b73154769398d3135507060fa020aad0a` |
| Wheel SHA-256 | `c7073283475e7ae722db2478b499d962364851104e09edb71f254ba21c1310cd` | `170fdac154794292c99dc6eea6486e7a2c3fdf321bcd87976d924bccd3db4aef` |
| Evals commit | `7629ba5a2447c919e499e88e9b4eedbc80c8f3ab` | `1fec68532e70…` |
| Runner SHA-256 | `ac58c0b9…970f` | `ac58c0b9…970f` (identical) |
| Platform | `macOS-15.7.3-arm64-arm-64bit` | `macOS-15.7.3-arm64-arm-64bit` |
| Python / Playwright | 3.12.7 / 1.61.0 | 3.12.7 / 1.61.0 |

## Compiled replay, side by side

Task success is the independent screenshot/OCR oracle; over-halt means the arm
reported halt/incomplete while that oracle confirmed the intended effect.

| Condition | 1.16.1 success | 1.24.0 success | 1.16.1 over-halt | 1.24.0 over-halt | 1.16.1 steady median | 1.24.0 steady median |
|---|---:|---:|---:|---:|---:|---:|
| `clean` | 3/3 | 3/3 | 0 | **2** | 7.189s | **12.263s** |
| `theme` | 3/3 | 3/3 | **3** | **0** | 12.661s | 6.822s |
| `rename` | 3/3 | 3/3 | 0 | 0 | 7.114s | 6.500s |

Silent incorrect success, wrong-action writes, model calls, and model cost are
**0** in every cell of both runs. The steelmanned DOM controls are unchanged:
3/3 on `clean` and `theme` at ~0.2s steady, and 0/3 on `rename`, failing loudly
at the first renamed locator before any mutation.

## Regression: the over-halt moved into the no-drift baseline

The `region_stable` postcondition failure on `step_010` (the `Save Encounter`
click) that fired 3/3 under `theme` drift on 1.16.1 no longer fires under
`theme` — Flow's fix landed. It now fires **2/3 under `clean`**, where there is
no drift at all:

```
Postconditions failed for step 'step_010' (click 'Save Encounter'):
expected screen state not reached (semantic drift) — failed: region_stable
region=(0, 228, 696, 223) — run aborted
```

In every one of those trials the independent oracle confirmed the encounter was
saved correctly. This is strictly worse than the 1.16.1 behaviour it replaced: a
false halt under cosmetic drift is defensible, a false halt on an undrifted
application is a baseline reliability regression. It is not a flake — an
independent replication (`replication/`) reproduced the same 2/3 pattern with
the same failing region.

The counted trials are retained in `clean_postcondition_over_halt.json`.
`theme_postcondition_over_halt.json` is retained with zero observations as the
evidence that the 1.16.1 theme regression is fixed.

Consequence beyond timing: the aborted run stops **before** independent effect
verification, so the run reports `HALTED_BEFORE_EFFECT` for a save that
demonstrably landed. `transaction_probe/` measures that directly — it is the
same failure the `ok` / `effect_verified` cell records.

## Improvement: identity coverage

The compiled bundle now arms **5 of 8** identity-applicable clicks, against
**1 of 8** on 1.16.1. The three that remain unarmed are refused for stated
reasons (row text too generic, or the only readable text is the target's own
mutable label) rather than silently skipped. Task completion is still not a
universal wrong-target-immunity claim for unarmed steps.

## What is not claimed

- No zero-shot / computer-use-agent comparison was run, on either release. No
  model was called and no VM was started.
- Synthetic MockMed, one workflow, one macOS host, headless Chromium.
- No hosted lifecycle, Windows UIA, RDP, Citrix, or real customer application is
  represented.
