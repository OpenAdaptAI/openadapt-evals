"""Consume exact central task and condition identities for Windows workers.

This module has no campaign discovery behavior.  The caller must supply the
campaign artifact, task-source, and condition-source digests from its trusted
campaign input.  A task name, path, or benchmark label is not an identity.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

TASK_SELECTOR_DOMAIN = b"OpenAdapt qualification worker task selector v1\0"
TASK_CONDITION_DOMAIN = b"OpenAdapt qualification worker task condition v1\0"
TASK_SELECTOR_SCHEMA = "openadapt.qualification-worker-task-selector/v1"
TASK_CONDITION_SCHEMA = "openadapt.qualification-worker-task-condition/v1"

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_TASK_SELECTOR_FIELDS = {
    "schema_version",
    "campaign_artifact_sha256",
    "task_source_sha256",
    "task_ordinal",
    "task_id_sha256",
}
_TASK_CONDITION_FIELDS = {
    "schema_version",
    "task_id_sha256",
    "condition_source_sha256",
    "condition_ordinal",
    "task_condition_sha256",
}


class WorkerTaskContractError(ValueError):
    """A worker task or condition identity is invalid or differs."""


@dataclass(frozen=True)
class WorkerTaskSelector:
    """One validated remote-safe task selector."""

    schema_version: str
    campaign_artifact_sha256: str
    task_source_sha256: str
    task_ordinal: int
    task_id_sha256: str

    def as_mapping(self) -> dict[str, str | int]:
        """Return the exact closed selector object."""

        return {
            "schema_version": self.schema_version,
            "campaign_artifact_sha256": self.campaign_artifact_sha256,
            "task_source_sha256": self.task_source_sha256,
            "task_ordinal": self.task_ordinal,
            "task_id_sha256": self.task_id_sha256,
        }


@dataclass(frozen=True)
class WorkerTaskCondition:
    """One validated remote-safe condition bound to a task identity."""

    schema_version: str
    task_id_sha256: str
    condition_source_sha256: str
    condition_ordinal: int
    task_condition_sha256: str

    def as_mapping(self) -> dict[str, str | int]:
        """Return the exact closed condition object."""

        return {
            "schema_version": self.schema_version,
            "task_id_sha256": self.task_id_sha256,
            "condition_source_sha256": self.condition_source_sha256,
            "condition_ordinal": self.condition_ordinal,
            "task_condition_sha256": self.task_condition_sha256,
        }


@dataclass(frozen=True)
class WorkerTaskContract:
    """One validated task and its exact validated condition."""

    selector: WorkerTaskSelector
    condition: WorkerTaskCondition


def load_task_contracts(path: Path) -> list[WorkerTaskContract]:
    """Load exact task contracts from one local protected input file."""

    if path.is_symlink() or not path.is_file():
        raise WorkerTaskContractError("worker task contract path is not a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerTaskContractError("worker task contract file is invalid") from exc
    if not isinstance(value, list) or not value:
        raise WorkerTaskContractError("worker task contract list is invalid")
    contracts: list[WorkerTaskContract] = []
    for entry in value:
        wrapper = _closed_mapping(entry, {"selector", "condition"}, "task contract")
        selector = validate_task_selector(wrapper["selector"])
        condition = validate_task_condition(wrapper["condition"])
        if condition.task_id_sha256 != selector.task_id_sha256:
            raise WorkerTaskContractError(
                "worker task condition selects a different task identity"
            )
        contracts.append(WorkerTaskContract(selector=selector, condition=condition))
    return contracts


def canonical_json(value: object) -> bytes:
    """Return canonical compact sorted UTF-8 JSON bytes."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _domain_digest(domain: bytes, value: object) -> str:
    return "sha256:" + hashlib.sha256(domain + canonical_json(value)).hexdigest()


def _closed_mapping(
    value: object,
    fields: set[str],
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise WorkerTaskContractError(f"{label} is not a closed object")
    return value


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise WorkerTaskContractError(f"{label} is invalid")
    return value


def _require_positive_ordinal(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise WorkerTaskContractError(f"{label} is not a positive integer")
    return value


def task_selector_projection(
    *,
    campaign_artifact_sha256: str,
    task_source_sha256: str,
    task_ordinal: int,
) -> dict[str, str | int]:
    """Return the exact frozen central task-selector projection."""

    return {
        "schema_version": TASK_SELECTOR_SCHEMA,
        "campaign_artifact_sha256": campaign_artifact_sha256,
        "task_source_sha256": task_source_sha256,
        "task_ordinal": task_ordinal,
    }


def task_condition_projection(
    *,
    task_id_sha256: str,
    condition_source_sha256: str,
    condition_ordinal: int,
) -> dict[str, str | int]:
    """Return the exact frozen central task-condition projection."""

    return {
        "schema_version": TASK_CONDITION_SCHEMA,
        "task_id_sha256": task_id_sha256,
        "condition_source_sha256": condition_source_sha256,
        "condition_ordinal": condition_ordinal,
    }


def derive_task_selector(
    *,
    campaign_artifact_sha256: str,
    task_source_sha256: str,
    task_ordinal: int,
) -> WorkerTaskSelector:
    """Derive a task selector from caller-supplied exact source identities."""

    campaign = _require_digest(campaign_artifact_sha256, "campaign artifact identity")
    source = _require_digest(task_source_sha256, "task source identity")
    ordinal = _require_positive_ordinal(task_ordinal, "task ordinal")
    projection = task_selector_projection(
        campaign_artifact_sha256=campaign,
        task_source_sha256=source,
        task_ordinal=ordinal,
    )
    return WorkerTaskSelector(
        **projection,
        task_id_sha256=_domain_digest(TASK_SELECTOR_DOMAIN, projection),
    )


def derive_task_condition(
    *,
    task_id_sha256: str,
    condition_source_sha256: str,
    condition_ordinal: int,
) -> WorkerTaskCondition:
    """Derive a condition from caller-supplied exact source identities."""

    task = _require_digest(task_id_sha256, "task identity")
    source = _require_digest(condition_source_sha256, "condition source identity")
    ordinal = _require_positive_ordinal(condition_ordinal, "condition ordinal")
    projection = task_condition_projection(
        task_id_sha256=task,
        condition_source_sha256=source,
        condition_ordinal=ordinal,
    )
    return WorkerTaskCondition(
        **projection,
        task_condition_sha256=_domain_digest(TASK_CONDITION_DOMAIN, projection),
    )


def validate_task_selector(value: object) -> WorkerTaskSelector:
    """Validate one closed selector and rederive its exact identity."""

    selector = _closed_mapping(value, _TASK_SELECTOR_FIELDS, "worker task selector")
    if selector["schema_version"] != TASK_SELECTOR_SCHEMA:
        raise WorkerTaskContractError("worker task selector schema is invalid")
    expected = derive_task_selector(
        campaign_artifact_sha256=selector["campaign_artifact_sha256"],
        task_source_sha256=selector["task_source_sha256"],
        task_ordinal=selector["task_ordinal"],
    )
    identity = _require_digest(selector["task_id_sha256"], "task identity")
    if identity != expected.task_id_sha256:
        raise WorkerTaskContractError("worker task identity differs")
    return expected


def validate_task_condition(value: object) -> WorkerTaskCondition:
    """Validate one closed condition and rederive its exact identity."""

    condition = _closed_mapping(
        value,
        _TASK_CONDITION_FIELDS,
        "worker task condition",
    )
    if condition["schema_version"] != TASK_CONDITION_SCHEMA:
        raise WorkerTaskContractError("worker task condition schema is invalid")
    expected = derive_task_condition(
        task_id_sha256=condition["task_id_sha256"],
        condition_source_sha256=condition["condition_source_sha256"],
        condition_ordinal=condition["condition_ordinal"],
    )
    identity = _require_digest(
        condition["task_condition_sha256"],
        "task condition identity",
    )
    if identity != expected.task_condition_sha256:
        raise WorkerTaskContractError("worker task condition identity differs")
    return expected


def consume_task_contract(
    selector_value: object,
    condition_value: object,
    *,
    campaign_artifact_sha256: str,
    task_source_sha256: str,
    task_ordinal: int,
    condition_source_sha256: str,
    condition_ordinal: int,
) -> WorkerTaskContract:
    """Validate and bind a central task contract to trusted campaign inputs."""

    expected_selector = derive_task_selector(
        campaign_artifact_sha256=campaign_artifact_sha256,
        task_source_sha256=task_source_sha256,
        task_ordinal=task_ordinal,
    )
    selector = validate_task_selector(selector_value)
    condition = validate_task_condition(condition_value)

    if condition.task_id_sha256 != selector.task_id_sha256:
        raise WorkerTaskContractError(
            "worker task condition selects a different task identity"
        )
    if selector.campaign_artifact_sha256 != expected_selector.campaign_artifact_sha256:
        raise WorkerTaskContractError("worker task selector campaign differs")
    if selector.task_source_sha256 != expected_selector.task_source_sha256:
        raise WorkerTaskContractError("worker task selector source differs")
    if selector.task_ordinal != expected_selector.task_ordinal:
        raise WorkerTaskContractError("worker task selector ordinal differs")

    expected_condition = derive_task_condition(
        task_id_sha256=expected_selector.task_id_sha256,
        condition_source_sha256=condition_source_sha256,
        condition_ordinal=condition_ordinal,
    )
    if condition.condition_source_sha256 != expected_condition.condition_source_sha256:
        raise WorkerTaskContractError("worker task condition source differs")
    if condition.condition_ordinal != expected_condition.condition_ordinal:
        raise WorkerTaskContractError("worker task condition ordinal differs")
    if condition.task_condition_sha256 != expected_condition.task_condition_sha256:
        raise WorkerTaskContractError("worker task condition differs")

    return WorkerTaskContract(selector=selector, condition=condition)
