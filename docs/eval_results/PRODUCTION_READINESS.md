# Production-readiness evidence boundary

OpenAdapt has production-capable mechanisms. It does not have one global
production-readiness state. Each workflow, application, version, environment,
identity rule, effect oracle, and deployment boundary needs its own
qualification.

The `current` label in `PUBLISHED_EVIDENCE.json` has one narrow meaning: the
evidence set matches the current published `openadapt-flow` release. It does
not mean the campaign is production acceptance. The evidence manifest records
that distinction in `campaigns[].evidence_scope.production_acceptance`.

## What the current public Evals set establishes

The Flow 1.31.0 set contains four campaigns. Every condition has three trials.

| Campaign | Environment | What it measures | Production acceptance |
| --- | --- | --- | --- |
| Comparison | Synthetic MockMed, local macOS host, headless Chromium | Compiled replay and two Playwright controls under clean, theme, and bounded label drift | No |
| Independent replication | The same bounded environment in a second complete run | Repeatability of the comparison result | No |
| Transaction probe | Synthetic MockMed fault server and its independent persistence store | Outcome taxonomy under normal, timeout, optimistic-screen, session, and duplicate faults | No |
| Remote lease safety | An instrumented fake remote backend | The input-edge refusal contract when a frame lease is absent or changes | No |

The comparison and replication count silent incorrect success and over-halt.
The transaction and remote-lease probes do not count both metrics as production
reliability measures. Their manifest entries say `not_counted`. They therefore
cannot satisfy a production-acceptance gate.

No campaign in this set represents hosted execution, a customer workflow,
Windows UIA, native macOS Accessibility, Linux AT-SPI, a real RDP session, or a
real Citrix ICA/HDX session. Other repositories retain their own bounded
substrate campaigns. Those results remain specific to their exact tasks and
environments, and no campaign in this repository establishes production
acceptance.

## Acceptance exit conditions

A production claim for one workflow needs one immutable acceptance record that
contains all of these facts:

1. The exact task, application version, operating system, display/session
   properties, OpenAdapt release, runner, and deployment revisions.
2. At least three trials for each healthy and fault condition in the accepted
   matrix, with no hidden retry or excluded run.
3. An independent oracle for the intended effect, wrong-record effects,
   duplicates, collateral changes, and effect absence or uncertainty.
4. A complete failure taxonomy that counts silent incorrect success,
   over-halt, safe halt, uncertain delivery, platform failure, and operator
   intervention.
5. The full delivery path for that operating model. A managed-browser result
   includes authenticated submission, idempotency, polling, one-use delivery,
   execution, independent verification, a signed receipt, and a signed webhook.
6. Real configured production dependencies. A mock or simulated success cannot
   satisfy the gate.
7. A clean-machine install and first-run check on every operating system that
   the claim names.

For a real RDP or Citrix claim, the record also includes reconnect, session
change, stale-frame, resolution/DPI, and compression fault conditions. A fake
remote backend proves a runtime contract only. It does not replace a real
session result.

For a generally available Desktop release, distribution evidence is separate
from workflow qualification. The release needs the intended signing,
notarization or Authenticode, installer, update, rollback, and key-lifecycle
evidence. An unsigned or ad-hoc-signed Beta installer can still provide useful
evaluation evidence, but it is not a generally available signed release.
