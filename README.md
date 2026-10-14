# openadapt-evals

[![Tests](https://github.com/OpenAdaptAI/openadapt-evals/actions/workflows/test.yml/badge.svg)](https://github.com/OpenAdaptAI/openadapt-evals/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/openadapt-evals.svg)](https://pypi.org/project/openadapt-evals/)
[![Python](https://img.shields.io/pypi/pyversions/openadapt-evals.svg)](https://pypi.org/project/openadapt-evals/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

openadapt-evals measures how well a GUI agent, or a workflow compiled by
OpenAdapt, completes desktop tasks. It runs each task, scores the result with
the benchmark's own checker rather than the agent's claim of success, and saves
scores and step-by-step traces you can compare across runs. For
[Windows Agent Arena](https://microsoft.github.io/WindowsAgentArena/) (WAA), it
can also create and delete the Windows VMs the benchmark needs, in your own
Azure or AWS account.

Use it to:

- get a reproducible WAA score for a GUI agent you're building,
- check whether a change to OpenAdapt made replay better or worse, or
- compare a compiled workflow with a model-driven agent on the same tasks.

To record and replay your own workflows, use
[OpenAdapt](https://github.com/OpenAdaptAI/OpenAdapt) (`pip install openadapt`)
instead.

## Quick start

You need Python 3.10 or later. The quick start needs no VM and no API key, and
it costs nothing.

```bash
pip install openadapt-evals
openadapt-evals mock --tasks 5
```

```
==================================================
Evaluation Results
==================================================
Attempts:     5
Outcomes:     5
Errors:       0
Success rate: 100.0% (outcomes only)
Avg score:    1.000 (outcomes only)
Avg steps:    1.0 (all attempts)
```

The mock environment and its scripted agent always succeed, so this run only
shows that the install works. Scores and traces go to `benchmark_results/`.

## Score your own agent

Subclass `BenchmarkAgent` and return one action per step:

```python
from openadapt_evals import (
    BenchmarkAction,
    BenchmarkAgent,
    WAAMockAdapter,
    compute_metrics,
    evaluate_agent_on_benchmark,
)


class MyAgent(BenchmarkAgent):
    def act(self, observation, task, history=None):
        # observation.screenshot holds PNG bytes; task.instruction says what to do.
        # Return one action per step. This agent gives up at once.
        return BenchmarkAction(type="done")


results = evaluate_agent_on_benchmark(MyAgent(), WAAMockAdapter(num_tasks=5))
print(compute_metrics(results)["success_rate"])
```

This prints `0.0`. The agent reports that it's done without doing anything, and
the checker scores what the agent did. On WAA, the checker inspects the VM's
files, settings, and app state. To run the same agent on a real Windows VM,
replace `WAAMockAdapter` with `WAALiveAdapter`.

![Benchmark viewer](https://raw.githubusercontent.com/OpenAdaptAI/openadapt-evals/main/animations/benchmark-viewer.webp)

## Run on Windows Agent Arena

You need a running WAA server that has the `/evaluate` endpoint this package
adds. `oa-vm pool-create` builds one on Azure (the default) or AWS, and billing
starts when the VM does. The
[CLI reference](https://github.com/OpenAdaptAI/openadapt-evals/blob/main/docs/CLI.md)
covers credentials, `pool-wait`, and the per-worker files that the pool commands
require.

With the server reachable at `localhost:5001` and `ANTHROPIC_API_KEY` set:

```bash
openadapt-evals run --agent api-claude --task 04d9aeaf-7bed-4024-bedb-e10e6f00eb7f-WOS
oa-vm pool-cleanup -y    # deletes the VMs; until you run it, they keep billing
```

`run` scores each task with WAA's own checker and opens an HTML viewer of the
run when it finishes. Task IDs come from WAA's `test_small.json` and
`test_all.json`. The live adapter rejects mock IDs such as `notepad_1`.

## Evaluate a compiled workflow on WAA

`openadapt-eval-flow` replays compiled OpenAdapt workflows on WAA tasks. Without
`--live`, it only estimates cost: it starts no VM and makes no network calls.

```bash
openadapt-eval-flow --mode replay --tasks 154 --dry-run
```

```
  154 tasks:
    Azure VM-hours:        2.82 vm-hours @ $0.19/hr  = $0.54
    Agent token cost:      $0.00  (paid tasks=0.0, 0 steps each)
    -> TOTAL:              $0.54   ($0.0035/task)
    Pure-agent baseline:   $39.06   (22 steps/task, all paid)
    Savings vs baseline:   $38.53

  HARD GUARDRAILS (enforced on any --live paid run):
    per-run cap:      $0.50
    total cap:        $5.00
    per-task tokens:  60,000
    billing-abort:    after 2 consecutive errors
```

With `--live`, it runs each task's WAA setup steps, replays that task's compiled
bundle, and scores the result with WAA's checker. Per-task results go to
`flow_waa_results/results.json`. A live run needs
`pip install 'openadapt-evals[flow]'`, a running WAA server, and one compiled
bundle per task. It refuses to start if a task has no bundle or no WAA checker
config.

## Does a compiled workflow survive a UI change?

The latest published comparison ran OpenAdapt's compiled replay and two
Playwright scripts, one that finds elements by position and one by name, on a
synthetic medical-records web app (MockMed). Each arm ran three times per
condition. `theme` restyles the app. `rename` changes the `Open` button to
`View` and `Save Encounter` to `Submit Encounter`.

| Condition | Compiled replay | Playwright, by position | Playwright, by name |
|---|---|---|---|
| `clean` | 3/3 | 3/3 | 3/3 |
| `theme` | 3/3 | 3/3 | 3/3 |
| `rename` | 3/3 | 0/3 | 0/3 |

A separate screenshot and OCR check confirmed each saved record. After the
rename, both Playwright scripts stopped at the first renamed button and wrote
nothing. Compiled replay completed all three runs, with no wrong writes and no
model calls. Compiled replay is slower. In the `clean` condition it took a
median of 6.4 seconds per run, against 0.20 seconds for the Playwright scripts.
Where an application has a stable API or selectors, those are still the faster
choice.

Measured 2026-08-29 against Flow 1.34.0 on macOS with headless Chromium. Flow
1.35.0 and 1.35.1 shipped later, and Flow 1.35.1 has not been re-measured. The
full report, timings, and dependency list are in
[`current_flow_v1_34_0_local_20260829`](https://github.com/OpenAdaptAI/openadapt-evals/tree/main/docs/eval_results/current_flow_v1_34_0_local_20260829).

## Check whether a reward pays for wrong writes

```bash
python -m openadapt_evals.extradup kill-scan
```

ExtraDup applies five kinds of wrong write to a MockMed record: a duplicate
record, an extra field, a missing field, a form that was never submitted, and a
"Saved" banner with nothing saved. It then asks two reward functions whether to
pay, three times for each case. A reward that only looks at the screen paid all
15 wrong writes. A reward that reads the stored record paid none of them, and
paid all 3 correct writes. The scan runs offline in about a second. To score
your own checker, see the
[ExtraDup README](https://github.com/OpenAdaptAI/openadapt-evals/blob/main/openadapt_evals/extradup/README.md).

## Also in this package

- A harness that runs record, compile, replay, repair, and verify across
  environments, with export to [Inspect AI](https://inspect.aisi.org.uk/).
- Agents for Claude, GPT, Qwen3-VL, and HTTP endpoints, including a planner and
  grounder agent that separates what to do from where to click.
- A middleware that removes personal data from screenshots before an agent
  sees them.
- A GRPO trainer and an OpenEnv-compatible environment.

Runbooks for these are in
[docs/WORKFLOWS.md](https://github.com/OpenAdaptAI/openadapt-evals/blob/main/docs/WORKFLOWS.md).

## Limits

- The published results cover one synthetic web workflow on one macOS host. No
  Windows desktop app, RDP or Citrix session, or real customer application is
  in them, and there is no published WAA comparison of compiled replay with an
  agent yet.
- `openadapt-eval-flow --mode hybrid` (replay with an agent fallback) estimates
  cost but doesn't run.
- The included benchmarks are WAA, live and mock, and local desktop runs through
  `LocalAdapter`. Others, such as OSWorld or WebArena, need a new
  `BenchmarkAdapter`.
- Deployment thresholds, tuned adversary parameters, per-system checking
  recipes, and real customer data stay private.
- How results are tied to an exact release, kept current, and kept separate
  from production sign-off is in
  [docs/COMPLIANCE.md](https://github.com/OpenAdaptAI/openadapt-evals/blob/main/docs/COMPLIANCE.md).

## Contributing

```bash
git clone https://github.com/OpenAdaptAI/openadapt-evals.git
cd openadapt-evals
uv sync --extra dev
uv run pytest tests/ -v
```

Every dependency installs from PyPI, so you don't need other OpenAdapt
repositories checked out next to this one. To work against a local copy of one,
install it into the environment after syncing, for example
`uv pip install -e ../openadapt-ml`, and don't commit a `path` source for it.

Use a branch and a pull request; don't push to `main`. PR titles use
[Conventional Commits](https://www.conventionalcommits.org/), because
`python-semantic-release` reads them to pick the version bump.
[CLAUDE.md](https://github.com/OpenAdaptAI/openadapt-evals/blob/main/CLAUDE.md)
has the development conventions and the WAA workflow.

## License

[MIT](https://opensource.org/licenses/MIT)
