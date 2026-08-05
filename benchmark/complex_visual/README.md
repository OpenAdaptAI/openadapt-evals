# Complex visual workflow benchmark

This public harness drives three separate headed OS windows under X11: Inbox,
Worklist, and Document editor. It records target crops from a demonstrated
healthy workflow. Replay resolves targets only from those retained pixels. It
does not import fixture roles or colors. It sends real XTest pointer and
keyboard events, and it captures the X root before guarded actions. The
workflow reads synthetic email,
branches by priority, loops over two attachments and two worklist rows, updates
a CSV worklist, and creates a document.

The fixture runs as a local headed process. A second process opens SQLite in
read-only mode and reads the CSV, Maildir, and document stores through new
handles. It records exact before and after states. The actor does not use this
observer for target selection. The classifier compares every non-target record
field, including the status and route of REC-999.

It starts no cloud service and makes no model call. A Flow integration can
supply its own trial callback and retain the campaign and metric contract.

Run it with:

```sh
Xvfb :99 -screen 0 1280x700x24 &
DISPLAY=:99 python -m benchmark.complex_visual.run_campaign --output /tmp/complex-visual
```

The campaign runs at least three trials for every condition: healthy, wrong
entity, ambiguity, focus theft, stale frame, partial render, display drift,
reconnect, and commit-timeout. It reports silent incorrect successes and
over-halts, under-halts, wrong-entity writes, duplicates, collateral writes,
and reconciled uncertain deliveries separately. A safe-halt condition that
completes the effect fails the campaign. A commit-timeout dispatches the write,
loses the acknowledgement, and uses the independent observer. It never retries.

The path-scoped CI workflow uploads retained demonstration and trial frames,
event traces, observer before and after states, fixture logs, and the campaign
summary. These are synthetic artifacts. The workflow starts no paid service.

Only the public mechanism and a synthetic sample are in this directory. Do not
add grown failure data, tuned adversary parameters, deployment thresholds,
oracle recipes, or real-EMR data. Keep those artifacts in the private boundary
defined by `source-policy.yaml`.
