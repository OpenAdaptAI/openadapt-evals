# Training against a certified reward

`openadapt_evals.reward` wires a TRL GRPO trainer or a verl trainer to a reward
endpoint that answers with a signed `RewardEvidenceReceiptV1` from
`openadapt-types`. The receipt says what an independent oracle read at the end
of one episode, at what tier, and under which certificate. The adapters turn
that into the scalar the trainer expects and refuse the three shortcuts that
make a reward lie: scoring an unreadable outcome as 0, calling a tier-0 read
certified, and training past a certificate's expiry.

The reward worker (oracle read, judge, signing, the HTTP route) lives in
`openadapt-flow`. This package only consumes what it emits. For tests and the
proof below, `openadapt_evals.reward.devsigner` builds receipts from the same
contract with a throwaway ed25519 key.

## What today's certificate is

There is exactly one certificate scope in use today: **synthetic**. It is
calibrated on the MockMed ExtraDup rollouts in this repository and it bounds
those rollouts and nothing else. A **production** scope needs the Phase-1
calibration described in
[`docs/preregistrations/PREREGISTRATION_CERTIFIED_REWARD_RL_2026_08_25.md`](../preregistrations/PREREGISTRATION_CERTIFIED_REWARD_RL_2026_08_25.md),
which is not published. Nothing in this package labels a reward `certified`
without a scope on the receipt, and it logs the scope beside every certified
receipt so a training log cannot hide which one it trained on.

## Wiring TRL

TRL's `GRPOTrainer` accepts reward functions that take `prompts`, `completions`,
and every dataset column as keyword arguments and return one float per
completion ([TRL docs](https://huggingface.co/docs/trl/main/en/grpo_trainer),
"Using a custom reward function"). Your dataset needs an `episode_id` column
that names the rollout the oracle will read.

```python
from openadapt_evals.reward import HttpRewardEndpoint
from openadapt_evals.reward.trl import CertifiedRewardFunction

reward = CertifiedRewardFunction(
    HttpRewardEndpoint("http://reward-worker:8080"),
    reward_contract_digest="sha256:...",      # the contract every receipt must bind
    policy_checkpoint_id="policy.checkpoint.0001",
    num_generations=config.num_generations,   # TRL's group size
    certificate=certificate,                  # RewardCertificateV1 the trainer holds
)

trainer = GRPOTrainer(model=model, args=config, reward_funcs=[reward.as_async()], ...)
```

Pass `reward` itself for the synchronous path or `reward.as_async()` to let TRL
await it concurrently with other reward functions. The policy update is read
from `trainer_state.global_step`. After each batch, `reward.metadata_columns()`
returns per-sample columns (`reward_outcome`, `reward_certified`,
`reward_calibration_scope`, `reward_certificate_state`, `reward_unscored`) you
can log next to the scalars.

By default `require_certified=True`: a scored receipt that is not certified
raises `UncertifiedRewardError` and stops the run. That is deliberate. The
preregistration says an expired, un-renewed certificate halts the arm. Set
`require_certified=False` for a tier-0 or tier-1 development run; every such
receipt is then logged as `development_only` and never marked certified.

## Wiring verl

verl's per-sample hook (`custom_reward_function.path`,
[verl docs](https://verl.readthedocs.io/en/latest/preparation/reward_function.html))
sees one completion at a time and must return a number, so it cannot drop a
sample from its group. Use the reward manager instead. verl registers managers
by name and constructs the chosen one with `tokenizer`, `num_examine`,
`compute_score`, `reward_fn_key`, and `reward_model.reward_kwargs`
([naive.py](https://github.com/volcengine/verl/blob/main/verl/workers/reward_manager/naive.py)).

```python
from openadapt_evals.reward.verl import register_with_verl

register_with_verl()   # registers "openadapt_certified"; call before the trainer starts
```

```yaml
reward_model:
  reward_manager: openadapt_certified
  reward_kwargs:
    endpoint_url: http://reward-worker:8080
    reward_contract_digest: sha256:...
    policy_checkpoint_id: policy.checkpoint.0001
    require_certified: true
```

Each sample's `extra_info` must carry `episode_id`. The manager groups samples
by `non_tensor_batch["uid"]`, the same key verl's GRPO advantage uses, reads
the policy update from `meta_info["global_steps"]`, and returns the per-sample
flags in `reward_extra_info`.

## The unscored rule

`reconciliation_required` and `failed_platform` receipts carry no scalar. The
contract forbids turning them into 0.0, because 0.0 teaches the policy that an
unreadable store is a bad outcome when the policy may have done everything
right.

TRL lets a reward function return `None` for a sample, but with a single reward
function that `None` becomes `NaN`, the per-function rewards are combined with
`nansum`, and the sample trains as 0.0. Excluded from one function is not
dropped from the group.

So both adapters drop an unscored sample the only way a per-completion scalar
allows: the sample gets the mean reward of its scored group-mates. GRPO's
advantage is reward minus group mean, so that sample's advantage is exactly
zero, it contributes no policy gradient, and the scored samples' mean is
untouched. The group std shrinks a little because one term is zero, which
scales the scored advantages without changing their sign or order. A group
with no scored sample at all comes back as `None` in TRL (which logs a warning
and trains the group at zero advantage) and as zeros in verl, flagged
`reward_group_unscored`.

## The proof

`python -m openadapt_evals.reward.proof` runs scripted policies against the
in-memory MockMed store from `openadapt_evals.extradup` and scores every
rollout with two rewards through the same `assess_receipt` path the adapters
use. No model, no GPU. Three trials per condition on the seed schedule
`[101, 202, 303]`; the seed picks the banner wording and the receipt
identities. The committed output is
[`proof_2026-09-01.md`](proof_2026-09-01.md) and
[`proof_2026-09-01.json`](proof_2026-09-01.json); a test regenerates it and
fails if the committed file drifts from the code.

`visual_only` is a tier-0 reward that believes the saved banner, the filled
form, or the policy's claim. `certified_sor` is a tier-2 reward that runs
ExtraDup's `sor_check` (record count, no extra field, every spec field) behind
a self-signed synthetic-scope certificate. `oracle_outage` is not an ExtraDup
family: the write is correct but the store cannot be read, so the certified
reward answers `failed_platform`.

| condition | gold | reward | tier | trials | paid | silent incorrect success | over-refusal | unscored | certified | scope |
|---|---|---|---|---|---|---|---|---|---|---|
| control | PASS | visual_only | 0 | 3 | 3 | n/a | 0.00 | 0 | no | none |
| control | PASS | certified_sor | 2 | 3 | 3 | n/a | 0.00 | 0 | no | none |
| dup | FAIL | visual_only | 0 | 3 | 3 | 1.00 | n/a | 0 | no | none |
| dup | FAIL | certified_sor | 2 | 3 | 0 | 0.00 | n/a | 0 | no | none |
| extra | FAIL | visual_only | 0 | 3 | 3 | 1.00 | n/a | 0 | no | none |
| extra | FAIL | certified_sor | 2 | 3 | 0 | 0.00 | n/a | 0 | no | none |
| omit | FAIL | visual_only | 0 | 3 | 3 | 1.00 | n/a | 0 | no | none |
| omit | FAIL | certified_sor | 2 | 3 | 0 | 0.00 | n/a | 0 | no | none |
| unsubmit | FAIL | visual_only | 0 | 3 | 3 | 1.00 | n/a | 0 | no | none |
| unsubmit | FAIL | certified_sor | 2 | 3 | 0 | 0.00 | n/a | 0 | no | none |
| claim | FAIL | visual_only | 0 | 3 | 3 | 1.00 | n/a | 0 | no | none |
| claim | FAIL | certified_sor | 2 | 3 | 0 | 0.00 | n/a | 0 | no | none |
| oracle_outage | PASS | visual_only | 0 | 3 | 3 | n/a | 0.00 | 0 | no | none |
| oracle_outage | PASS | certified_sor | 2 | 3 | 0 | n/a | 0.00 | 3 | no | none |

The visual reward paid all 15 gold-FAIL rollouts. The certified reward paid
none of them and paid the 3 controls. Its certificate's epsilon, 0.181036, is
the exact one-sided 95% Clopper-Pearson upper bound from those 15 trials; it
was computed from the run, not chosen. The `certified` column reads `no` for
the tier-2 reward under openadapt-types 0.16.0 because that release has no
`calibration_scope` field on the receipt, and the adapter will not label a
receipt certified without a scope. When the field ships, the same run marks
the `certified_sor` rows `yes` with scope `synthetic`; the tests that assert
that are skipped until then.

The expiry check re-assesses the certified control receipts at policy update
100, the first update at which the certificate has expired: none stays
certified and the adapter logs three expiry warnings.

## What this does not show

It does not train anything, so it says nothing about how the two rewards
change a policy. It does not touch a real system of record. The bound is for
15 synthetic trials at one seed schedule and would move with either. The
reward worker that issues production receipts is a separate piece of work in
`openadapt-flow`; until it ships, the only receipts this package has seen were
signed by its own development key.
