# Reproduce the Flow 1.35.1 local evidence

This set uses the exact published `openadapt-flow` 1.35.1 wheel and the exact
release-tagged source at `44e99a48ebf048c18892aa17cef6ae594db0d0c2`.
It uses the synthetic MockMed fixture, loopback network traffic, and a local
headless Chromium browser. It uses no paid service and no customer data.

Create a clean Python 3.12 environment that includes `pip`, because each runner
records `pip freeze`. Install `openadapt-flow[console,browser]==1.35.1` (which
resolved `openadapt-types==0.17.1` and `playwright==1.64.0`) and `requests`.
Install the Playwright-managed Chromium for 1.64.0 (`playwright install
chromium`, revision `1248`). Download the Flow wheel and source archive without
changing them, verify their SHA-256 digests against PyPI, and check out the
`v1.35.1` source tag.

This run installed the downloaded wheel with `uv pip install`, so the
`openadapt-flow` line in each `dependency-freeze.txt` names the local wheel file
without a digest. Each `results.json` and `EVIDENCE_MANIFEST.json` binds the
wheel digest.

Run these commands from Evals commit
`e6a246909be2371a4fc95f871bec49133bc0b9d2`:

```bash
python scripts/run_current_flow_local_benchmark.py \
  --flow-source /path/to/openadapt-flow-v1.35.1 \
  --flow-wheel /path/to/openadapt_flow-1.35.1-py3-none-any.whl \
  --out out/current

python scripts/run_current_flow_local_benchmark.py \
  --flow-source /path/to/openadapt-flow-v1.35.1 \
  --flow-wheel /path/to/openadapt_flow-1.35.1-py3-none-any.whl \
  --out out/current/replication

python scripts/run_flow_transaction_probe.py \
  --flow-source /path/to/openadapt-flow-v1.35.1 \
  --flow-wheel /path/to/openadapt_flow-1.35.1-py3-none-any.whl \
  --out out/current/transaction_probe

python scripts/probe_remote_lease_safety.py \
  --flow-source /path/to/openadapt-flow-v1.35.1 \
  --flow-wheel /path/to/openadapt_flow-1.35.1-py3-none-any.whl \
  --out out/current/remote_lease_safety

python scripts/build_evidence_manifest.py out/current \
  --sdist-sha256 c5c6c437472b23999223b0d2473dbf21de2ca05274c270ae3854adeda6b07dca
```

Each campaign retains its installed-package freeze, Python version,
`openadapt-types` version, browser version when applicable, and exact
Playwright Chromium revision. `EVIDENCE_MANIFEST.json` binds every verifier,
result, replication artifact, report, task/oracle contract, environment,
dependency snapshot, reliability-metric coverage, and maturity boundary.

The reports are the runners' output and were not edited. The comparison
report's section on a Flow-versus-zero-shot run is fixed text in the runner. It
says the live WAA replay path leaves WAA's checker unwired, which was true when
the runner was written. Since Evals #347, `openadapt-eval-flow --live` scores
replays with WAA's checker, tested with fakes only. No zero-shot comparison was
run for this set.

The manifest marks every campaign as `production_acceptance: false`. These are
local synthetic or contract-fixture results. They do not establish hosted,
customer-workflow, RDP-session, or Citrix-session production acceptance.
