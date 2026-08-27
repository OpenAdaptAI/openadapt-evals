from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest

from openadapt_evals.infrastructure.windows_worker_task_contract import (
    TASK_CONDITION_DOMAIN,
    TASK_SELECTOR_DOMAIN,
    WorkerTaskContractError,
    canonical_json,
    consume_task_contract,
    derive_task_condition,
    derive_task_selector,
    validate_task_condition,
    validate_task_selector,
)

ROOT = Path(__file__).resolve().parents[1]


def _sha(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _selector(
    *,
    campaign: str | None = None,
    source: str | None = None,
    ordinal: int = 7,
) -> dict[str, str | int]:
    return derive_task_selector(
        campaign_artifact_sha256=campaign or _sha("campaign"),
        task_source_sha256=source or _sha("private-task-source"),
        task_ordinal=ordinal,
    ).as_mapping()


def _condition(
    selector: dict[str, str | int],
    *,
    source: str | None = None,
    ordinal: int = 3,
) -> dict[str, str | int]:
    task_id = selector["task_id_sha256"]
    assert isinstance(task_id, str)
    return derive_task_condition(
        task_id_sha256=task_id,
        condition_source_sha256=source or _sha("private-condition-source"),
        condition_ordinal=ordinal,
    ).as_mapping()


def _consume(
    selector: object,
    condition: object,
    *,
    campaign: str | None = None,
    task_source: str | None = None,
    task_ordinal: int = 7,
    condition_source: str | None = None,
    condition_ordinal: int = 3,
):
    return consume_task_contract(
        selector,
        condition,
        campaign_artifact_sha256=campaign or _sha("campaign"),
        task_source_sha256=task_source or _sha("private-task-source"),
        task_ordinal=task_ordinal,
        condition_source_sha256=condition_source
        or _sha("private-condition-source"),
        condition_ordinal=condition_ordinal,
    )


def test_exact_central_domains_projections_and_vectors_are_frozen() -> None:
    selector = _selector()
    condition = _condition(selector)

    assert TASK_SELECTOR_DOMAIN == b"OpenAdapt qualification worker task selector v1\0"
    assert TASK_CONDITION_DOMAIN == (
        b"OpenAdapt qualification worker task condition v1\0"
    )
    assert canonical_json(
        {key: selector[key] for key in selector if key != "task_id_sha256"}
    ) == (
        b'{"campaign_artifact_sha256":"sha256:3dc260b2472062d9c57b'
        b'd930b02f23831d917b8f3e3234b6d63964a53c31d3aa","schema_version"'
        b':"openadapt.qualification-worker-task-selector/v1","task_ordinal"'
        b':7,"task_source_sha256":"sha256:8057301060c8a6a36e2b425e4d26'
        b'eb10a6d110cdaffe5c80ebe1c515286c3e17"}'
    )
    assert selector["task_id_sha256"] == (
        "sha256:3e688825cd4e6ce312d15f47ddb1d3fa57441e3b0c3a5ca9ccc2f1f285a52cc7"
    )
    assert canonical_json(
        {
            key: condition[key]
            for key in condition
            if key != "task_condition_sha256"
        }
    ) == (
        b'{"condition_ordinal":3,"condition_source_sha256":"sha256:'
        b'b9079b50782122c328dae360cb2d9766601668d1e1842bc4f73d0a0404b'
        b'f38df","schema_version":"openadapt.qualification-worker-task-condition'
        b'/v1","task_id_sha256":"sha256:3e688825cd4e6ce312d15f47ddb1d3'
        b'fa57441e3b0c3a5ca9ccc2f1f285a52cc7"}'
    )
    assert condition["task_condition_sha256"] == (
        "sha256:e09987d522fd290c2d07994428027bebd5deabcf2156258dd9633a465095b16f"
    )


def test_local_schemas_are_byte_exact_central_copies() -> None:
    expected = {
        "qualification-worker-task-selector.schema.json": (
            "8fccacea4fc0a083eb5d6cf8e6f95465bfc749bc366ff6985d296535ef034797"
        ),
        "qualification-worker-task-condition.schema.json": (
            "046e234401babac2d33384e4ffd939039b5fc2f735a99c8d989f7eb776824a88"
        ),
    }
    for name, digest in expected.items():
        schema = (ROOT / "openadapt_evals" / "schemas" / name).read_bytes()
        assert hashlib.sha256(schema).hexdigest() == digest


def test_exact_contract_is_consumed() -> None:
    selector = _selector()
    condition = _condition(selector)

    contract = _consume(selector, condition)

    assert contract.selector.as_mapping() == selector
    assert contract.condition.as_mapping() == condition


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("task_source_sha256", _sha("substituted-task-source")),
        ("task_ordinal", 8),
    ],
)
def test_unrederived_task_substitution_is_refused(
    field: str,
    replacement: str | int,
) -> None:
    selector = _selector()
    selector[field] = replacement

    with pytest.raises(WorkerTaskContractError, match="task identity differs"):
        validate_task_selector(selector)


def test_rederived_task_source_substitution_is_refused() -> None:
    selector = _selector(source=_sha("substituted-task-source"))
    condition = _condition(selector)

    with pytest.raises(WorkerTaskContractError, match="selector source differs"):
        _consume(selector, condition)


def test_rederived_task_ordinal_substitution_is_refused() -> None:
    selector = _selector(ordinal=8)
    condition = _condition(selector)

    with pytest.raises(WorkerTaskContractError, match="selector ordinal differs"):
        _consume(selector, condition)


def test_rederived_campaign_substitution_is_refused() -> None:
    selector = _selector(campaign=_sha("substituted-campaign"))
    condition = _condition(selector)

    with pytest.raises(WorkerTaskContractError, match="selector campaign differs"):
        _consume(selector, condition)


@pytest.mark.parametrize(
    ("source", "ordinal", "message"),
    [
        (_sha("substituted-condition-source"), 3, "condition source differs"),
        (_sha("private-condition-source"), 4, "condition ordinal differs"),
    ],
)
def test_rederived_condition_substitution_is_refused(
    source: str,
    ordinal: int,
    message: str,
) -> None:
    selector = _selector()
    condition = _condition(selector, source=source, ordinal=ordinal)

    with pytest.raises(WorkerTaskContractError, match=message):
        _consume(selector, condition)


def test_condition_task_mismatch_is_refused() -> None:
    selector = _selector()
    other_selector = _selector(ordinal=8)
    condition = _condition(other_selector)

    with pytest.raises(WorkerTaskContractError, match="different task identity"):
        _consume(selector, condition)


def test_closed_shapes_invalid_digests_and_ordinals_are_refused() -> None:
    selector = _selector()
    condition = _condition(selector)

    extra_selector = deepcopy(selector)
    extra_selector["task_name"] = "must-not-cross-boundary"
    with pytest.raises(WorkerTaskContractError, match="closed object"):
        validate_task_selector(extra_selector)

    extra_condition = deepcopy(condition)
    extra_condition["condition"] = {"private": "must-not-cross-boundary"}
    with pytest.raises(WorkerTaskContractError, match="closed object"):
        validate_task_condition(extra_condition)

    for invalid in (0, -1, True, "1"):
        with pytest.raises(WorkerTaskContractError, match="positive integer"):
            derive_task_selector(
                campaign_artifact_sha256=_sha("campaign"),
                task_source_sha256=_sha("private-task-source"),
                task_ordinal=invalid,  # type: ignore[arg-type]
            )

    with pytest.raises(WorkerTaskContractError, match="source identity is invalid"):
        derive_task_condition(
            task_id_sha256=selector["task_id_sha256"],  # type: ignore[arg-type]
            condition_source_sha256="sha256:" + "A" * 64,
            condition_ordinal=3,
        )
