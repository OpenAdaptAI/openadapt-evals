# openadapt-evals

[![Tests](https://github.com/OpenAdaptAI/openadapt-evals/actions/workflows/test.yml/badge.svg)](https://github.com/OpenAdaptAI/openadapt-evals/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/openadapt-evals.svg)](https://pypi.org/project/openadapt-evals/)
[![Python](https://img.shields.io/pypi/pyversions/openadapt-evals.svg)](https://pypi.org/project/openadapt-evals/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

You changed something in the compiler and you need to know whether it got
better or worse. This runs GUI agents and compiled OpenAdapt workflows against
a benchmark, scores them with the benchmark's own verifier instead of asking
the agent how it did, provisions the VMs that takes, and writes the numbers to
a file you can commit.

It's for people working on OpenAdapt, and for anyone who wants to measure a GUI
agent against [Windows Agent Arena](https://microsoft.github.io/WindowsAgentArena/).
You don't need it to record or replay a workflow, which is
[openadapt-flow](https://github.com/OpenAdaptAI/openadapt-flow).

[Docs](https://docs.openadapt.ai) ·
[CLI reference](docs/CLI.md) ·
[Workflows and layout](docs/WORKFLOWS.md) ·
[Evidence boundary](docs/eval_results/PRODUCTION_READINESS.md)

![Benchmark viewer](https://raw.githubusercontent.com/OpenAdaptAI/openadapt-evals/main/animations/benchmark-viewer.webp)

## Try it without a VM

```bash
pip install openadapt-evals
openadapt-evals mock --tasks 5
```

```
11:24:42 [INFO] Task 5/5: mock_file_explorer_001
11:24:42 [INFO] Step 0: Agent chose action: click
11:24:42 [INFO] Step 1: Agent signaled task completion
11:24:42 [INFO] [SUCCESS] Task mock_file_explorer_001 completed successfully (score: 1.00)
11:24:42 [INFO] Saved summary: 5/5 outcomes succeeded (100.0%); 0 errors across 5 attempts

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

Abridged output from 0.94.0. The mock adapter and its deterministic agent both
always succeed, so 100% here means the harness is wired up, and nothing else.
Apart from `audit-verifier` below, every other command in this repository can
cost money.

## Audit a benchmark's checker

If you build an agent benchmark, or train on rewards computed from one, its
checker decides what counts as success. `audit-verifier` tests that checker.
It takes each task's own correct solution, makes one edit to it, replays the
edited run from a fresh start state, reads the end state back, and only then
calls the benchmark's checker, unmodified. It lists every edit the checker
passed although the end state differs from the correct run's. It calls no
model.

```bash
pip install openadapt-evals
openadapt-evals audit-verifier --benchmark toy
```

```
[1/5] split-bill: FALSE ACCEPT (extra, extra-ni) (0s)
[2/5] split-bill-counted: no false accept (0s)
[3/5] queue-songs: FALSE ACCEPT (extra, extra-ni) (0s)
[4/5] like-songs: no false accept (0s)
[5/5] rename-profile: no false accept (0s)
Verifier audit: toy, 5 task(s), 5 audited, 0s

The verifier passed 4 edited run(s) whose end state is wrong:
  task         operator  end state compared with the reference run
  -----------  --------  ------------------------------------------
  split-bill   extra     toy.Notification +1, toy.PaymentRequest +1
  split-bill   extra-ni  toy.Notification +1, toy.PaymentRequest +1
  queue-songs  extra     toy.QueueEntry +1
  queue-songs  extra-ni  toy.QueueEntry +1

Per operator (each edited run counted once; operators are not pooled):
  operator     class          runs  killed  false accept  equivalent  unconfirmed  refused  error  invalid
  -----------  -------------  ----  ------  ------------  ----------  -----------  -------  -----  -------
  claim-only   postcondition     5       5             0           0            0        0      0        0
  omit         postcondition     5       5             0           0            0        0      0        0
  partial      postcondition     4       4             0           0            0        1      0        0
  wrong-value  postcondition     5       5             0           0            0        0      0        0
  extra        frame             5       1             2           2            0        0      0        0
  extra-ni     frame             3       1             2           0            0        2      0        0

false accept: the verifier passed the edited run, and the end state (read
  back before grading) differs from the reference run's.
equivalent: the edit left the end state unchanged, so the pass is correct.
```

`toy` is a small synthetic benchmark inside the package, so this runs offline
in under a second. Two of its five checkers compare the values of new records
without counting them, so a repeated write passes both.

Each operator makes one edit:

| Operator | Edit | A correct checker |
|---|---|---|
| `claim-only` | report success and write nothing | fails it |
| `omit` | drop the last write | fails it |
| `partial` | of the most repeated write, keep only the first | fails it |
| `wrong-value` | change one value in the last write | fails it |
| `extra` | repeat the last write | fails it, unless the repeat changed nothing |
| `extra-ni` | repeat the last write whose repeat changes the end state, found by replaying each candidate without calling the checker | fails it |

Each edited run gets one result. `killed` means the checker failed it.
`false accept` means the checker passed it and the end state differs from the
correct run's. `equivalent` means the edit left the end state unchanged, so
the pass is correct. `refused` means the task gave the operator nothing to
edit. `unconfirmed`, `error` and `invalid` mark runs that could not be checked
cleanly, for example because the unedited run itself failed. The command
exits 1 when it finds a false accept, so a CI job can run it. `--out
report.json` writes every run's result; the report holds record counts and
field names, not record values.

### AppWorld

[AppWorld](https://github.com/StonyBrookNLP/appworld) is not bundled. It
ships its task data and tests encrypted and asks that public copies stay
encrypted, so you install it yourself, once. It needs its own environment
because it pins pydantic 1:

```bash
uv venv --python 3.11 ~/.cache/appworld/venv
uv pip install --python ~/.cache/appworld/venv/bin/python appworld==0.1.3.post1
~/.cache/appworld/venv/bin/appworld install
~/.cache/appworld/venv/bin/appworld download data --root ~/.cache/appworld

openadapt-evals audit-verifier --benchmark appworld \
    --appworld-python ~/.cache/appworld/venv/bin/python \
    --appworld-root ~/.cache/appworld \
    --tasks 22cc237_1,396c5a2_1
```

```
[1/2] 22cc237_1: FALSE ACCEPT (extra, extra-ni) (43s)
[2/2] 396c5a2_1: FALSE ACCEPT (extra, extra-ni) (38s)
Verifier audit: appworld, 2 task(s), 2 audited, 81s

The verifier passed 4 edited run(s) whose end state is wrong:
  task       operator  end state compared with the reference run
  ---------  --------  ----------------------------------------------
  22cc237_1  extra     venmo.Notification +1, venmo.PaymentRequest +1
  22cc237_1  extra-ni  venmo.Notification +1, venmo.PaymentRequest +1
  396c5a2_1  extra     spotify.MusicPlayer: queue_song_ids changed
  396c5a2_1  extra-ni  spotify.MusicPlayer: queue_song_ids changed

Per operator (each edited run counted once; operators are not pooled):
  operator     class          runs  killed  false accept  equivalent  unconfirmed  refused  error  invalid
  -----------  -------------  ----  ------  ------------  ----------  -----------  -------  -----  -------
  claim-only   postcondition     2       2             0           0            0        0      0        0
  omit         postcondition     2       2             0           0            0        0      0        0
  partial      postcondition     1       1             0           0            0        1      0        0
  wrong-value  postcondition     2       2             0           0            0        0      0        0
  extra        frame             2       0             2           0            0        0      0        0
  extra-ni     frame             2       0             2           0            0        0      0        0

false accept: the verifier passed the edited run, and the end state (read
  back before grading) differs from the reference run's.
equivalent: the edit left the end state unchanged, so the pass is correct.
```

Task `22cc237_1` asks for Venmo payment requests to the people who still owe
their share of a dinner bill. Its tests check the receiver and amount of each
new request but never count the requests, so a run that sends the last
request twice passes. In `396c5a2_1` the tests compare the song queue as a
set, so a song queued twice passes. A task took 12 to 68 seconds in our runs
on an Apple silicon Mac. Without `--tasks`, the command audits the first 20
tasks of the `train` split; `--limit 0 --jobs 4` audits the whole split.

We ran the command on the 48 AppWorld tasks the paper audited (AppWorld
0.1.3.post1, data 0.1.0, `--jobs 4`, 426 seconds). It matched the paper's
result for all 48 unedited runs and all 288 operator runs, refusals included.
`extra` passed 39 of 48 runs. In 33 of them the repeat changed nothing; the
other 6 are false accepts, on the three variants of each task above. The
checkers killed every postcondition edit that applied.

### Your own benchmark

Write an adapter and pass it as `--benchmark yourpackage.module:YourAdapter`.
A run is a list of API calls (`{"method", "url", "data"}`), and an effect is
the records each table gained, lost or changed:

```python
from openadapt_evals.verifier_audit import CallPolicy, Delivery, Reference


class YourAdapter:
    name = "your-benchmark"
    ignore_fields = frozenset({"id", "created_at"})  # fields with no task meaning
    policy = CallPolicy()  # which calls sign in, which claim success

    def describe(self):
        return {"name": self.name}

    def task_ids(self, split, limit):
        ...

    def reference(self, task_id) -> Reference:
        ...  # run the task's own solution; record its calls and its effect

    def deliver(self, task_id, runs) -> list[Delivery]:
        ...  # per run: fresh start state, replay, read back, then grade
```

The readback must not use the checker's assertions. It may read the same
database. [`adapters/toy.py`](openadapt_evals/verifier_audit/adapters/toy.py)
is a complete adapter.

### Limits

- The operators are six fixed, hand-written edits, one per run. A killed edit
  shows only that the checker catches that edit. The command does not search
  for exploits, combine edits, or grade one task's run with another task's
  checker.
- A false accept means the end state differs from the correct run's. If a task
  leaves a field free, such as the wording of a note, a changed value there is
  not an error. The report names the field; `--ignore-fields table.field`
  excludes it.
- The benchmark needs resettable start states, a correct reference run,
  actions that can be replayed as API calls, and a deterministic checker.
  Checkers that call an LLM judge are out of scope. The paper's WorkArena
  (browser) runner is not included.
- Counts describe the tasks you ran. They are not rates.

The method and the full results are in "Verifier²: Finding Loopholes in
Verifiable Rewards" (NeurIPS 2026 workshop "Who Verifies the Agents?").

## Price a real run before you pay for it

`openadapt-eval-flow` is dry-run unless you pass `--live`. Dry runs provision
nothing, start no VM, and make no network calls:

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

Those caps aren't decoration. An early uncapped run cost real money, which is
how they got there.

## Drive it from Python

```python
from openadapt_evals import (
    ApiAgent, WAALiveAdapter, WAALiveConfig,
    evaluate_agent_on_benchmark, compute_metrics,
)

adapter = WAALiveAdapter(WAALiveConfig(server_url="http://localhost:5001"))
agent = ApiAgent(provider="anthropic")

results = evaluate_agent_on_benchmark(agent, adapter, task_ids=["notepad_1"])
print(f"Success rate: {compute_metrics(results)['success_rate']:.1%}")
```

## Run against a live WAA server

```bash
oa-vm pool-create --workers 1        # or --cloud aws
oa-vm pool-wait --qualification-dir ./proofs
openadapt-evals run --agent api-claude --task notepad_1
openadapt-evals view --run-name live_eval
oa-vm pool-cleanup -y                # stops billing
```

Forget the last line and the VM bills until you remember. `pool-wait`,
`pool-run`, and `pool-auto` require `--qualification-dir`, a directory holding
a fresh `<worker>.identity.json` and `<worker>.egress.json` for each worker;
they refuse to run without it. Most pool commands take `--cloud azure`
(the default) or `--cloud aws`, though `pool-logs`, `pool-vnc`, and `pool-exec`
do not. The rest of the `oa-vm`
subcommands, the `oa` and `openadapt-evals` command tables, and the
configuration and AWS SSO setup are in [docs/CLI.md](docs/CLI.md).

## What the current evidence says

Every published report pins one exact `openadapt-flow` wheel, so a Flow release
can invalidate a report without a single commit landing here.
`docs/eval_results/PUBLISHED_EVIDENCE.json` records which set is current and
which release it was measured against, and
`scripts/check_published_evidence_freshness.py` fails when that pin drifts. It
runs offline on every pull request and against PyPI on a daily schedule, and a
failed scheduled run opens an issue.

The current set is `current_flow_v1_34_0_local_20260829`, measured 2026-08-29
against Flow 1.34.0 on macOS with headless Chromium. Flow 1.35.0 and 1.35.1
shipped after it, and Flow 1.35.1 has not been re-measured, so these numbers
describe 1.34.0 only. The manifest accepts that gap until 2026-10-31. After
that date the daily check fails again until a new set is published. One
synthetic MockMed workflow, three arms, three runs each:

| Condition | Compiled replay | DOM positional | DOM name-scoped |
|---|---|---|---|
| `clean` | 3/3 | 3/3 | 3/3 |
| `theme` | 3/3 | 3/3 | 3/3 |
| `rename` | 3/3 | 0/3 | 0/3 |

The `rename` row is the one worth reading. It changes `Open` to `View` and
`Save Encounter` to `Submit Encounter`, and both Playwright selector controls
failed loudly at the first renamed locator before mutating anything. Those are
unsupported-drift halts, not silent wrong writes. Compiled replay is also
roughly thirty times slower per run than a working selector, 6.4s against
0.20s, which is the honest reminder that structural actuation should stay the
preferred tier wherever an application gives you one.

Zero silent incorrect successes, zero wrong actions, zero over-halts, zero
model calls, $0.00 across all 27 runs. Full report, caveats, and the dependency
freeze: [`docs/eval_results/current_flow_v1_34_0_local_20260829/`](docs/eval_results/current_flow_v1_34_0_local_20260829/).

Publish a new set rather than editing an old one. Superseded reports stay
reproducible against the wheel they were measured on, and none of the nine get
deleted.

## What this repository cannot tell you yet

- **There is no current Flow-versus-zero-shot number.** The word `current` on an
  evidence set means release-fresh, not production-accepted. No Azure WAA VM was
  started for the 1.34.0 set and no model was called.
- **The live WAA path is not finished.** `scripts/eval_flow_on_waa.py` leaves
  `WAALiveAdapter.evaluate` unwired on the replay path, so it cannot
  independently score success, and the hybrid live path returns before
  execution because its adapter isn't connected either. Wiring both is step one
  of any valid comparison run.
- **The evidence is local and synthetic.** Bundled MockMed, one workflow, one
  macOS host. No hosted lifecycle, no Windows UIA, no RDP, no Citrix, and no
  real customer application is represented anywhere in it.
- **Only two benchmark families exist.** `BenchmarkAdapter` is built to extend
  to OSWorld or WebArena. Today there is WAA, live and mock, and there is
  `LocalAdapter` for native desktop runs.
- **Some of it is deliberately absent.** Deployment-derived thresholds, tuned
  adversary parameters, per-system-of-record oracle recipes, and real customer
  datasets stay out of this open repository.

The missing acceptance tracks and the exit condition for each are written down
in [docs/eval_results/PRODUCTION_READINESS.md](docs/eval_results/PRODUCTION_READINESS.md).

## What else is in here

A meta-benchmark harness runs record, compile, replay, heal, verify across any
registered `Environment` and emits one metrics row per `(env, task, mode)`, and
exports to [Inspect AI](https://inspect.aisi.org.uk/). Thirteen agents ship,
including a dual-model `PlannerGrounderAgent` that separates what to do from
where to click, and a `ScrubMiddleware` strips PII before any agent sees a
screenshot. There's also a standalone GRPO trainer with no openadapt-ml
dependency, an OpenEnv-compatible environment, and a four-pass pipeline that
turns desktop recordings into structured workflows.

ExtraDup is the frozen duplicate-write kill-scan. Gold is FAIL when the
system of record has the wrong cardinality or an extra field. One command
scores the certified reward against a visual-only baseline, or a paid/not-paid
map from someone else's checker:

```text
python -m openadapt_evals.extradup kill-scan
```

It prints silent-incorrect-success on the FAIL mutants and honest-write on
the control. `execute_seal` and `production_seal` stay false; mutants stay off
the training reward. On the committed 2026-09-01 MockMed run, `visual_only`
paid 15/15 gold-FAIL and `certified_sor` paid 0/15 FAIL and 3/3 honest. See
[`openadapt_evals/extradup/README.md`](openadapt_evals/extradup/README.md)
and [docs/reward/README.md](docs/reward/README.md).

Runbooks for the demo-conditioned eval, the full evaluation runner, the UI-Venus
grounder endpoint, GRPO training, and writing your own agent are in
[docs/WORKFLOWS.md](docs/WORKFLOWS.md), along with the package tree.

## Contributing

```bash
git clone https://github.com/OpenAdaptAI/openadapt-evals.git
cd openadapt-evals
uv sync --extra dev
uv run pytest tests/ -v
```

Every dependency installs from PyPI, so you don't need other OpenAdapt
repositories checked out next to this one. To work against a local copy of
one, install it into the environment after syncing, for example
`uv pip install -e ../openadapt-ml`, and don't commit a `path` source for it.

This is research infrastructure and it moves fast. Branches and pull requests
only, never a direct push to `main`. PR titles need
[conventional commit](https://www.conventionalcommits.org/) format, because
`python-semantic-release` parses them to decide the version bump.
[CLAUDE.md](https://github.com/OpenAdaptAI/openadapt-evals/blob/main/CLAUDE.md)
has the development conventions and the WAA benchmark workflow.

## License

[MIT](https://opensource.org/licenses/MIT)
