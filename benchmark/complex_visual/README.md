# Complex visual workflow benchmark

This public harness drives a no-DOM pixel desktop with Inbox, Worklist, and
Document editor windows. It finds controls from PNG pixels, moves a pointer,
clicks, types, and changes windows. The workflow reads synthetic email,
branches by priority, loops over two attachments and two worklist rows, updates
a CSV worklist, and creates a document.

The fixture runs as a local process. The actor receives screenshots and input
receipts only. A second process opens SQLite in read-only mode and reads the
CSV, Maildir, and document stores through new handles. The actor does not use
this observer for target selection. The observer derives the result from the
immutable task truth and persisted effects.

It starts no cloud service and makes no model call. A Flow integration can
supply its own trial callback and retain the campaign and metric contract.

Run it with:

```sh
python -m benchmark.complex_visual.run_campaign
```

The campaign runs at least three trials for every condition: healthy, wrong
entity, ambiguity, focus theft, stale frame, partial render, display drift,
reconnect, and commit-timeout. It reports silent incorrect successes and
over-halts, wrong-entity writes, duplicates, collateral writes, and reconciled
uncertain deliveries separately. A commit-timeout dispatches the write, loses
the acknowledgement, and uses the independent observer. It never retries.

Only the public mechanism and a synthetic sample are in this directory. Do not
add grown failure data, tuned adversary parameters, deployment thresholds,
oracle recipes, or real-EMR data. Keep those artifacts in the private boundary
defined by `source-policy.yaml`.
