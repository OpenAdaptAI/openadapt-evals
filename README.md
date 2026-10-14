# openadapt-evals

[![Tests](https://github.com/OpenAdaptAI/openadapt-evals/actions/workflows/test.yml/badge.svg)](https://github.com/OpenAdaptAI/openadapt-evals/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/openadapt-evals.svg)](https://pypi.org/project/openadapt-evals/)
[![Python](https://img.shields.io/pypi/pyversions/openadapt-evals.svg)](https://pypi.org/project/openadapt-evals/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

openadapt-evals measures how well a GUI agent, or a workflow that OpenAdapt
compiled from one recorded demonstration, completes desktop tasks. It runs each
task, scores the result with the benchmark's own checker rather than the
agent's claim of success, and saves scores and step-by-step traces you can
compare across runs. For
[Windows Agent Arena](https://microsoft.github.io/WindowsAgentArena/) (WAA), it
can also create and delete the Windows VMs the benchmark needs, in your own
Azure or AWS account.

Use it to:

- Score a GUI agent you're building on WAA tasks
- Check whether a change to OpenAdapt made replay better or worse
- Compare a compiled workflow with a model-driven agent on the same tasks

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

It logs each step, then prints a summary:

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

The mock agent clicks the button that the mock checker looks for, so every task
passes and this run only shows that the install works. `Outcomes` counts the
attempts the checker scored. A VM or checker outage counts as an error and is
left out of the success rate.

Scores, traces, and screenshots go to a run folder under `benchmark_results/`.
To browse them, pass that folder's name to the viewer:

```bash
openadapt-evals view --run-name <run-folder>
```

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
files, settings, and app state.

To run the same agent on a real Windows VM (set up in the next section), use
the live adapter and name the WAA tasks. The live adapter has no task list of
its own, so without `task_ids` it runs nothing.

```python
from openadapt_evals import WAALiveAdapter, WAALiveConfig

adapter = WAALiveAdapter(WAALiveConfig(server_url="http://localhost:5001"))
results = evaluate_agent_on_benchmark(
    MyAgent(), adapter, task_ids=["04d9aeaf-7bed-4024-bedb-e10e6f00eb7f-WOS"]
)
```

![Benchmark viewer](https://raw.githubusercontent.com/OpenAdaptAI/openadapt-evals/main/animations/benchmark-viewer.webp)

## Run on Windows Agent Arena

You need a Windows VM running the WAA server, plus the scoring server this
package adds next to it. `oa-vm pool-create --workers 1` builds one on Azure
(the default) or AWS (`--cloud aws`), and billing starts when the VM does.
Without `--workers`, it builds three. The
[CLI reference](https://github.com/OpenAdaptAI/openadapt-evals/blob/main/docs/CLI.md)
covers credentials, `pool-wait`, and the per-worker files that the pool commands
require.

`oa-vm pool-status` shows the VM's IP address. Forward the two servers to your
machine and leave this running:

```bash
ssh -N -L 5001:localhost:5000 -L 5050:localhost:5051 azureuser@<vm-ip>   # ubuntu@ on AWS
```

Then, in another terminal with `ANTHROPIC_API_KEY` set:

```bash
openadapt-evals run --agent api-claude --task 04d9aeaf-7bed-4024-bedb-e10e6f00eb7f-WOS
oa-vm pool-cleanup -y    # deletes the VMs; until you run it, they keep billing
```

`run` scores each task with WAA's own checker and opens an HTML viewer of the
run when it finishes. Task IDs come from WAA's `test_small.json` and
`test_all.json`. The live adapter rejects test IDs such as `notepad_1` and
`mock_chrome_001`.

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
```

The estimate assumes one minute of VM time per replayed task and 22 model steps
per task for the agent baseline. Neither number comes from a WAA run of this
package.

With `--live`, it runs each task's WAA setup steps, replays that task's compiled
workflow, and scores the result with WAA's checker. Per-task results go to
`flow_waa_results/results.json`. A live run needs Python 3.12 or earlier,
`pip install 'openadapt-evals[flow]'`, a running WAA server, and a `--bundles`
folder with one subfolder per task ID that holds that task's compiled
`workflow.json`. It refuses to start if a task has no compiled workflow or no
WAA checker config.

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
median of 6.8 seconds per run, against 0.29 seconds for the Playwright scripts.
Where an application has a stable API or selectors, those are still the faster
choice.

Measured 2026-10-14 against Flow 1.35.1 on macOS with headless Chromium. The
full report, timings, and dependency list are in
[`current_flow_v1_35_1_local_20261014`](https://github.com/OpenAdaptAI/openadapt-evals/tree/main/docs/eval_results/current_flow_v1_35_1_local_20261014).

## Check whether a reward pays for wrong writes

```bash
python -m openadapt_evals.extradup kill-scan
```

ExtraDup applies five kinds of wrong write to a MockMed record: a duplicate
record, an extra field, a missing field, a form that was never submitted, and a
"Saved" banner with nothing saved. It then asks two built-in reference rewards
whether to pay, three times for each case. The first pays whenever the screen
looks finished, so it paid all 15 wrong writes. The second reads the stored
record. It paid none of the wrong writes and all 3 correct ones. The scan runs
offline in about a second. To score your own checker, see the
[ExtraDup README](https://github.com/OpenAdaptAI/openadapt-evals/blob/main/openadapt_evals/extradup/README.md).

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
database. [`adapters/toy.py`](https://github.com/OpenAdaptAI/openadapt-evals/blob/main/openadapt_evals/verifier_audit/adapters/toy.py)
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
- WAA scoring of `openadapt-eval-flow --live` replays has been tested with
  fakes only, not yet against a WAA VM. Its `--mode hybrid` (replay with an
  agent fallback) estimates cost but doesn't run.
- The spending caps that `openadapt-eval-flow` prints are checked only by
  `HybridFlowAgent`, which the command doesn't run. A live replay records each
  task's model calls and estimated model cost in `results.json` but doesn't
  stop at a cap.
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
uv run pytest tests/ -q -m "not heavy and not gpu and not vm" \
  -k "not (test_demo_format_and_persistence or test_synthetic_demos)"
```

That's the selection CI runs. The tests it leaves out need ML packages, a GPU,
a WAA VM, or recordings and demo files that aren't in the repository.

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
