# Evidence and release rules

The README shows what openadapt-evals does and the latest measured results.
This page holds the rules behind those results: how a published result is tied
to one exact OpenAdapt release, how it is kept current, what it does and does
not certify, and what stays out of this public repository.

## Every published result pins one Flow release

[`docs/eval_results/PUBLISHED_EVIDENCE.json`](eval_results/PUBLISHED_EVIDENCE.json)
lists every published Flow evidence set and the exact `openadapt-flow` release
it was measured on: version, source commit, release tag, and wheel and sdist
digests. It also marks which set is current. Because each set pins one wheel, a
new Flow release can make the current set stale without any commit landing
here.

[`scripts/check_published_evidence_freshness.py`](../scripts/check_published_evidence_freshness.py)
fails when the current set no longer pins the latest Flow release on PyPI, or
when a pinned digest does not match that release. It runs offline on every pull
request and against PyPI once a day. A failed daily run opens an issue, so the
alert outlives GitHub's 60-day pause on schedules in quiet repositories.

## Accepted drift

When a new Flow release ships before the comparison can be re-run, the current
entry can carry an `accepted_drift` record. It names one version, gives a
reason, and expires no more than 31 days out. While it is in place, the README
must say that the newer release was not measured;
`tests/test_published_evidence_freshness.py` checks that sentence. After the
expiry date, the daily check fails again until a new set is published.

## Publish a new set, never edit an old one

Mark a replaced set `superseded` in `PUBLISHED_EVIDENCE.json` and add the new
one. Old sets stay in the repository and stay reproducible against the wheel
they were measured on.

## "Current" is not production acceptance

The `current` label means only that a set matches the latest Flow release. It
does not mean any workflow is accepted for production. Every current entry and
campaign records `production_acceptance: false`. Setting it to `true` by hand
fails the freshness check, because a declared flag is not evidence. Production
acceptance can enter this repository only through
`scripts/import_production_acceptance.py`, which refuses every import until a
private-export contract is approved.

The verifier design, the acceptance exit conditions for one workflow, and the
gaps in the current set (no hosted run, no Windows UIA, no RDP or Citrix, no
customer application) are in
[`docs/eval_results/PRODUCTION_READINESS.md`](eval_results/PRODUCTION_READINESS.md)
and [`docs/eval_results/PRIVATE_EXPORT_CONTRACT.md`](eval_results/PRIVATE_EXPORT_CONTRACT.md).

## ExtraDup stays an evaluation

The ExtraDup kill-scan reports `execute_seal: false` and
`production_seal: false`. Its result covers the synthetic MockMed rollouts only.
It does not certify a production write, and its mutated writes are kept out of
any training reward. The frozen corpus and its scope are described in
[`openadapt_evals/extradup/README.md`](../openadapt_evals/extradup/README.md)
and [`docs/reward/README.md`](reward/README.md).

## Spending caps on paid runs

`openadapt-eval-flow` is a dry run unless you pass `--live`. Any live paid run
is held to a per-run cap, a total cap, a per-task token cap, and an abort after
repeated billing errors. The defaults are $0.50, $5.00, 60,000 tokens, and two
errors. The caps were added after an early run without them cost $40 to $70.

## What stays out of this repository

This repository is public and MIT licensed. Deployment-derived thresholds,
tuned adversary parameters, per-system effect-checking recipes, the grown
hardening corpus, and real customer or EMR datasets stay private.
`source-policy.public.json` lists the categories, and
[`scripts/check_source_boundary.py`](../scripts/check_source_boundary.py)
rejects matching files from the tree and from built packages on every pull
request and release.

Code under GPL, AGPL, LGPL, or SSPL licenses is not copied into this package.
A benchmark under one of those licenses has to be downloaded at run time.
Vendored code under permissive licenses is listed in `NOTICE`, and
[`scripts/check_third_party_notices.py`](../scripts/check_third_party_notices.py)
checks its provenance in the source tree and in built packages.
