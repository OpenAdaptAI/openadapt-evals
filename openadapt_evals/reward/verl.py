"""verl reward manager backed by certified reward receipts.

verl offers two hooks. The per-sample hook is
``custom_reward_function.path`` / ``.name`` with the signature
``compute_score(data_source, solution_str, ground_truth, extra_info=None)``
(https://verl.readthedocs.io/en/latest/preparation/reward_function.html).
That hook sees one sample at a time and must return a number, so it cannot
drop an unscored episode from its group: whatever it returns lands in the
reward tensor and moves the group mean.

The batch hook is a reward manager. verl registers managers by name with
``@register("...")`` in ``verl.workers.reward_manager`` and selects one with
``reward_model.reward_manager``; the trainer constructs it as
``cls(tokenizer=..., num_examine=..., compute_score=..., reward_fn_key=...,
**reward_kwargs)`` and calls ``manager(data, return_dict=True)``, expecting
``{"reward_tensor": ..., "reward_extra_info": {...}}`` where the tensor has
the response shape and the reward sits at each response's last valid token
(https://github.com/volcengine/verl/blob/main/verl/workers/reward_manager/naive.py).
GRPO then groups samples by ``non_tensor_batch["uid"]`` and takes the mean
and std per group
(``compute_grpo_outcome_advantage`` in
https://github.com/volcengine/verl/blob/main/verl/trainer/ppo/core_algos.py).

``CertifiedRewardManager`` is that batch hook. It fetches one receipt per
sample, applies the trainer-side checks, and gives every unscored sample the
mean of its scored ``uid`` group-mates so its advantage is zero. The
per-sample flags go out in ``reward_extra_info``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from openadapt_types.reward import RewardCertificateV1

from openadapt_evals.reward.receipts import (
    EpisodeDescriptor,
    HttpRewardEndpoint,
    RewardEndpointError,
    RewardSource,
    ScoredEpisode,
    assess_receipt,
    fetch_receipts,
    fill_unscored_with_group_mean,
    require_certified_or_unscored,
)

logger = logging.getLogger(__name__)

REWARD_MANAGER_NAME = "openadapt_certified"

try:  # verl is optional; the manager is duck-typed without it.
    from verl.workers.reward_manager.abstract import AbstractRewardManager as _Base
except ImportError:  # pragma: no cover - exercised only where verl is absent
    _Base = object  # type: ignore[misc, assignment]


class CertifiedRewardManager(_Base):
    """A verl reward manager that scores from certified receipts.

    Configure through ``reward_model.reward_kwargs`` (verl passes them as
    keyword arguments):

    .. code-block:: yaml

        reward_model:
          reward_manager: openadapt_certified
          reward_kwargs:
            endpoint_url: http://reward-worker:8080
            reward_contract_digest: sha256:...
            policy_checkpoint_id: policy.checkpoint.0001
            require_certified: true

    Each sample's ``extra_info`` must carry ``episode_id`` (and may carry
    ``task_id``). The policy update comes from ``data.meta_info["global_steps"]``
    when verl sets it, else from ``policy_update``.
    """

    def __init__(
        self,
        tokenizer: Any = None,
        num_examine: int = 0,
        compute_score: Any = None,
        reward_fn_key: str = "data_source",
        *,
        source: RewardSource | None = None,
        endpoint_url: str | None = None,
        reward_contract_digest: str,
        policy_checkpoint_id: str,
        require_certified: bool = True,
        certificate: RewardCertificateV1 | None = None,
        policy_update: int | Callable[[], int] | None = None,
        episode_id_key: str = "episode_id",
        task_id_key: str | None = "task_id",
        environment_id: str | None = None,
        on_endpoint_error: str = "raise",
        **_ignored: Any,
    ) -> None:
        if source is None:
            if endpoint_url is None:
                raise ValueError("pass source= or endpoint_url=")
            source = HttpRewardEndpoint(endpoint_url)
        if on_endpoint_error not in {"raise", "unscored"}:
            raise ValueError("on_endpoint_error must be 'raise' or 'unscored'")
        self.tokenizer = tokenizer
        self.num_examine = num_examine
        self.reward_fn_key = reward_fn_key
        self.source = source
        self.reward_contract_digest = reward_contract_digest
        self.policy_checkpoint_id = policy_checkpoint_id
        self.require_certified = require_certified
        self.certificate = certificate
        self._policy_update = policy_update
        self.episode_id_key = episode_id_key
        self.task_id_key = task_id_key
        self.environment_id = environment_id
        self.on_endpoint_error = on_endpoint_error
        if compute_score is not None:
            logger.warning("compute_score is ignored: rewards come from receipts")
        if not require_certified:
            logger.warning(
                "require_certified=False: rewards from this manager may be "
                "development_only and are never certified"
            )

    # -- pure part ----------------------------------------------------------------------

    def policy_update(self, meta_info: dict[str, Any] | None) -> int:
        if callable(self._policy_update):
            return int(self._policy_update())
        if self._policy_update is not None:
            return int(self._policy_update)
        step = (meta_info or {}).get("global_steps")
        if step is None:
            raise ValueError(
                "policy_update is unknown: pass policy_update= or set data.meta_info['global_steps']"
            )
        return int(step)

    def score_batch(
        self,
        extra_infos: Sequence[dict[str, Any]],
        group_ids: Sequence[Any],
        policy_update: int,
    ) -> tuple[list[float | None], dict[str, list[Any]], list[ScoredEpisode | None]]:
        """Score one batch without touching tensors.

        Returns the per-sample reward (``None`` only for a group with no
        scored member), the ``reward_extra_info`` columns, and the scored
        episodes.
        """

        descriptors = [
            EpisodeDescriptor(
                episode_id=str(info[self.episode_id_key]),
                policy_checkpoint_id=self.policy_checkpoint_id,
                policy_update=policy_update,
                reward_contract_digest=self.reward_contract_digest,
                task_id=str(info[self.task_id_key])
                if self.task_id_key and self.task_id_key in info
                else None,
                environment_id=self.environment_id,
            )
            for info in extra_infos
        ]
        receipts = self._fetch(descriptors)
        scored: list[ScoredEpisode | None] = []
        for receipt, descriptor in zip(receipts, descriptors):
            if receipt is None:
                scored.append(None)
                continue
            episode = assess_receipt(
                receipt,
                policy_update=policy_update,
                expected_contract_digest=self.reward_contract_digest,
                expected_episode_id=descriptor.episode_id,
                certificate=self.certificate,
            )
            if self.require_certified:
                require_certified_or_unscored(episode)
            scored.append(episode)
        values = [episode.scalar if episode is not None else None for episode in scored]
        rewards = fill_unscored_with_group_mean(values, list(group_ids))
        extra: dict[str, list[Any]] = {}
        for episode, reward in zip(scored, rewards):
            record = episode.metadata() if episode is not None else {"reward_unscored": True}
            record["reward_group_unscored"] = reward is None
            for key, value in record.items():
                extra.setdefault(key, []).append(value)
        dropped = sum(1 for value in values if value is None)
        if dropped:
            logger.info("dropped %d of %d episodes as unscored", dropped, len(values))
        return rewards, extra, scored

    def _fetch(self, descriptors: Sequence[EpisodeDescriptor]) -> list[Any]:
        if self.on_endpoint_error == "raise":
            return fetch_receipts(self.source, descriptors)
        receipts: list[Any] = []
        for descriptor in descriptors:
            try:
                receipts.append(self.source.fetch(descriptor))
            except RewardEndpointError as exc:
                logger.error("episode %s dropped, no receipt: %s", descriptor.episode_id, exc)
                receipts.append(None)
        return receipts

    # -- verl entry point -----------------------------------------------------------

    def __call__(self, data: Any, return_dict: bool = False) -> Any:
        import torch

        responses = data.batch["responses"]
        prompt_length = data.batch["prompts"].shape[-1]
        valid_lengths = data.batch["attention_mask"][:, prompt_length:].sum(dim=-1)
        uids = list(data.non_tensor_batch["uid"])
        extra_infos = list(data.non_tensor_batch.get("extra_info", [{} for _ in uids]))
        update = self.policy_update(getattr(data, "meta_info", None))
        rewards, extra, _scored = self.score_batch(extra_infos, uids, update)

        reward_tensor = torch.zeros_like(responses, dtype=torch.float32)
        for index, reward in enumerate(rewards):
            length = int(valid_lengths[index].item())
            if length <= 0:
                continue
            # An all-unscored group has no mean to pin to; zero for every
            # member yields zero advantage, the same as a dropped group.
            reward_tensor[index, length - 1] = 0.0 if reward is None else float(reward)
        if return_dict:
            return {"reward_tensor": reward_tensor, "reward_extra_info": extra}
        return reward_tensor


def register_with_verl(name: str = REWARD_MANAGER_NAME) -> bool:
    """Register ``CertifiedRewardManager`` under ``name`` if verl is importable.

    Returns true on success. Call this from the training script before the
    trainer resolves ``reward_model.reward_manager``.
    """

    try:
        from verl.workers.reward_manager import register
    except ImportError:
        logger.warning("verl is not installed; CertifiedRewardManager was not registered")
        return False
    register(name)(CertifiedRewardManager)
    return True
