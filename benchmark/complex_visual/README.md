# Complex visual workflow benchmark

This public harness tests a pixel-only workflow across Inbox, Worklist, and
Document editor windows. The workflow reads synthetic email, branches by
priority, loops over attachments, updates a CSV worklist, creates a document,
and proves results through independent SQLite, CSV, Maildir, and document-hash
reads.

It is local and synthetic by default. It starts no cloud service and makes no
model call. `run_campaign.py` is a deterministic reference implementation. A
Flow integration can supply its own `execute_trial` callback and retain the
same campaign and metric contract.

Run it with:

```sh
python -m benchmark.complex_visual.run_campaign
```

The campaign runs at least three trials for every condition: healthy, wrong
entity, ambiguity, focus theft, stale frame, partial render, display drift,
reconnect, and commit-timeout. It reports silent incorrect successes and
over-halts separately from aggregate outcomes. A commit-timeout must reconcile
through independent state; it must never cause a blind retry.

Only the public mechanism and a synthetic sample are in this directory. Do not
add grown failure data, tuned adversary parameters, deployment thresholds,
oracle recipes, or real-EMR data. Keep those artifacts in the private boundary
defined by `source-policy.yaml`.
