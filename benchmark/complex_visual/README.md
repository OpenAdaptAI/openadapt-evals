# Complex visual workflow benchmark

This public harness drives three separate headed OS windows under X11: Inbox,
Worklist, and Document editor. It records target crops from the source frames
and interaction geometry of a real demonstration. It records native and drifted
visual variants. Replay resolves targets only from those retained pixels. It
does not read fixture roles, colors, or a fixture geometry file. It sends real
XTest pointer and keyboard events, and it captures the X root before guarded
actions.

The Inbox shows a synthetic binary task card. The card contains a full SHA-256
digest. The separate actor reads and checks this card from a captured screen
frame. It gets the branch, both loop bounds, the document text, and the action
identifier from the visible card. The actor does not receive a task or truth
file. The campaign covers urgent and normal routes. The two cases use different
loop bounds.

The fixture, actor, and observer run as separate processes. The actor can write
only its sibling artifact directory. The coordinator keeps truth and observer
evidence in a read-only sibling directory while the actor runs. Each observer
record binds the phase, exact truth-file hash, and exact snapshot hash. The
observer opens SQLite in read-only mode. It reads the CSV, Maildir, and document
stores through new handles. The actor does not use this observer for target
selection.

The classifier requires the exact expected action identifier and a pending to
complete state transition. It rejects a preexisting complete state. It compares
all fields of every non-target record. It also counts unexpected actions,
documents, and mail as collateral effects.

It starts no cloud service and makes no model call. A Flow integration can
supply its own trial callback and retain the campaign and metric contract.

Run it with:

```sh
Xvfb :99 -screen 0 1280x700x24 &
DISPLAY=:99 python -m benchmark.complex_visual.run_campaign --output /tmp/complex-visual
```

The campaign runs at least three trials for every condition: healthy urgent,
healthy normal, wrong entity, ambiguity, focus theft, stale frame, partial
render, display drift, reconnect, and commit-timeout. It reports silent
incorrect successes, over-halts, under-halts, wrong-entity writes, duplicates,
collateral writes, and reconciled uncertain deliveries separately. A safe-halt
condition that completes the effect fails the campaign. A commit-timeout
dispatches the write, omits the visual receipt, and uses the independent
observer. It never retries.

The path-scoped CI workflow uploads retained demonstration and trial frames,
event traces, hash-bound observer evidence, sealed truth, fixture logs, and the
campaign summary. These are synthetic artifacts. The workflow starts no paid
service.

Only the public mechanism and a synthetic sample are in this directory. Do not
add grown failure data, tuned adversary parameters, deployment thresholds,
oracle recipes, or real-EMR data. Keep those artifacts in the private boundary
defined by `source-policy.yaml`.
