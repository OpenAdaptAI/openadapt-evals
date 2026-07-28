"""Version-bound, arm-independent oracle contracts for published evidence.

The actor and the oracle answer different questions.  An actor reports whether
it completed its control path.  An oracle observes the resulting state.  This
module keeps those inputs separate, evaluates every expected field explicitly,
and derives the benchmark failure taxonomy from both signals.

Published evidence can bind an oracle contract to exact verifier and runner
files.  :func:`validate_evidence_document` re-hashes those files.  A verifier
change therefore invalidates the evidence instead of silently changing the
meaning of an old success rate.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ORACLE_STATUSES = {"confirmed", "refuted", "unavailable"}


class OracleContractError(ValueError):
    """An oracle contract or one of its retained results is invalid."""


def canonical_sha256(value: Any) -> str:
    """Hash a JSON-compatible value with one stable canonical encoding."""

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    """Return the SHA-256 digest of one file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_relative_path(path: Path, root: Path, *, context: str) -> str:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise OracleContractError(f"{context}: path escapes the evaluation repository") from exc
    if not resolved.is_file():
        raise OracleContractError(f"{context}: file does not exist: {relative}")
    return relative.as_posix()


def _file_binding(path: Path, root: Path, *, context: str) -> dict[str, str]:
    return {
        "path": _safe_relative_path(path, root, context=context),
        "sha256": file_sha256(path),
    }


def _validate_expected_fields(fields: object) -> list[dict[str, Any]]:
    if not isinstance(fields, list) or not fields:
        raise OracleContractError("oracle contract requires a non-empty expected_fields list")
    validated: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, item in enumerate(fields):
        context = f"expected_fields[{index}]"
        if not isinstance(item, dict):
            raise OracleContractError(f"{context}: expected an object")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise OracleContractError(f"{context}: name must be a non-empty string")
        if name in names:
            raise OracleContractError(f"{context}: duplicate field name {name!r}")
        names.add(name)
        if item.get("comparison") != "exact":
            raise OracleContractError(
                f"{context}: the decision comparison must be exact; "
                "put OCR tolerance in the observation method"
            )
        expected = item.get("expected")
        if isinstance(expected, (dict, list)):
            raise OracleContractError(f"{context}: expected must be one scalar value")
        if item.get("required") is not True:
            raise OracleContractError(f"{context}: every published success field must be required")
        purpose = item.get("purpose")
        if purpose not in {"effect", "identity", "wrong_effect_absence"}:
            raise OracleContractError(f"{context}: unknown purpose {purpose!r}")
        observation = item.get("observation")
        if not isinstance(observation, dict) or not isinstance(observation.get("method"), str):
            raise OracleContractError(f"{context}: observation method is required")
        validated.append(item)
    return validated


def _validate_wrong_action_rules(
    rules: object,
    *,
    field_names: set[str],
) -> list[dict[str, list[str]]]:
    if not isinstance(rules, list) or not rules:
        raise OracleContractError("oracle contract requires wrong_action_rules")
    validated: list[dict[str, list[str]]] = []
    for index, rule in enumerate(rules):
        context = f"wrong_action_rules[{index}]"
        if not isinstance(rule, dict):
            raise OracleContractError(f"{context}: expected an object")
        if set(rule) - {"all_pass", "any_fail"}:
            raise OracleContractError(f"{context}: unknown rule field")
        all_pass = rule.get("all_pass", [])
        any_fail = rule.get("any_fail", [])
        if (
            not isinstance(all_pass, (list, tuple))
            or not isinstance(any_fail, (list, tuple))
            or not any_fail
        ):
            raise OracleContractError(f"{context}: any_fail must name at least one field")
        names = [*all_pass, *any_fail]
        if not all(isinstance(name, str) and name in field_names for name in names):
            raise OracleContractError(f"{context}: rule names an unknown field")
        validated.append({"all_pass": list(all_pass), "any_fail": list(any_fail)})
    return validated


@dataclass(frozen=True)
class OracleVerdict:
    """One field-level oracle result, independent of the actor self-report."""

    status: str
    field_results: tuple[dict[str, Any], ...]
    wrong_action: bool
    error_type: str | None = None

    @property
    def success(self) -> bool:
        """Return true only when every required field passed."""

        return self.status == "confirmed"

    def model_dump(self, *, exclude: set[str] | None = None) -> dict[str, Any]:
        """Provide the small interface used by the Flow benchmark helpers."""

        payload: dict[str, Any] = {
            "success": self.success,
            "oracle_status": self.status,
            "oracle_fields": [dict(item) for item in self.field_results],
            "wrong_action": self.wrong_action,
            "oracle_error_type": self.error_type,
        }
        for key in exclude or set():
            payload.pop(key, None)
        return payload


def evaluate_expected_fields(
    observed: Mapping[str, Any],
    expected_fields: Sequence[Mapping[str, Any]],
    wrong_action_rules: Sequence[Mapping[str, Sequence[str]]],
) -> OracleVerdict:
    """Evaluate each expected field with strict type-preserving equality."""

    fields = _validate_expected_fields([dict(item) for item in expected_fields])
    rules = _validate_wrong_action_rules(
        [dict(item) for item in wrong_action_rules],
        field_names={item["name"] for item in fields},
    )
    results: list[dict[str, Any]] = []
    pass_by_name: dict[str, bool] = {}
    unavailable = False
    for field in fields:
        name = field["name"]
        if name not in observed:
            unavailable = True
            result = {
                "name": name,
                "expected": field["expected"],
                "observed": None,
                "status": "unavailable",
                "passed": False,
            }
        else:
            actual = observed[name]
            expected = field["expected"]
            passed = type(actual) is type(expected) and actual == expected
            pass_by_name[name] = passed
            result = {
                "name": name,
                "expected": expected,
                "observed": actual,
                "status": "confirmed" if passed else "refuted",
                "passed": passed,
            }
        results.append(result)

    if unavailable:
        return OracleVerdict(
            status="unavailable",
            field_results=tuple(results),
            wrong_action=False,
            error_type="observation_unavailable",
        )

    wrong_action = any(
        all(pass_by_name[name] for name in rule["all_pass"])
        and any(not pass_by_name[name] for name in rule["any_fail"])
        for rule in rules
    )
    status = "confirmed" if all(pass_by_name.values()) else "refuted"
    return OracleVerdict(
        status=status,
        field_results=tuple(results),
        wrong_action=wrong_action,
    )


def unavailable_verdict(
    expected_fields: Sequence[Mapping[str, Any]],
    *,
    error_type: str,
) -> OracleVerdict:
    """Return an unscored oracle result without inventing an absent effect."""

    fields = _validate_expected_fields([dict(item) for item in expected_fields])
    return OracleVerdict(
        status="unavailable",
        field_results=tuple(
            {
                "name": field["name"],
                "expected": field["expected"],
                "observed": None,
                "status": "unavailable",
                "passed": False,
            }
            for field in fields
        ),
        wrong_action=False,
        error_type=error_type,
    )


def classify_outcome(
    *,
    actor_reported_complete: bool,
    oracle_status: str,
    wrong_action: bool,
) -> str:
    """Derive the counted outcome from independent actor and oracle signals."""

    if type(actor_reported_complete) is not bool:
        raise OracleContractError("actor_reported_complete must be a boolean")
    if oracle_status not in ORACLE_STATUSES:
        raise OracleContractError(f"unknown oracle status {oracle_status!r}")
    if oracle_status == "unavailable":
        return "oracle_indeterminate"
    if oracle_status == "confirmed":
        return "correct" if actor_reported_complete else "over_halt"
    if actor_reported_complete:
        return "silent_incorrect_success"
    return "wrong_action_after_halt_or_error" if wrong_action else "halt_or_error"


def build_oracle_contract(
    *,
    repo_root: Path,
    verifier_file: Path,
    runner_file: Path,
    evals_commit: str,
    arms: Sequence[str],
    expected_fields: Sequence[Mapping[str, Any]],
    wrong_action_rules: Sequence[Mapping[str, Sequence[str]]],
    observation_provider: Mapping[str, Any],
    dependency_versions: Mapping[str, str],
) -> dict[str, Any]:
    """Build one exact, public oracle contract for a counted campaign."""

    if not COMMIT_RE.fullmatch(evals_commit):
        raise OracleContractError("evals_commit must be a full Git commit")
    if not arms or len(set(arms)) != len(arms):
        raise OracleContractError("arms must be a non-empty unique list")
    fields = _validate_expected_fields([dict(item) for item in expected_fields])
    rules = _validate_wrong_action_rules(
        [dict(item) for item in wrong_action_rules],
        field_names={item["name"] for item in fields},
    )
    dependencies = dict(sorted(dependency_versions.items()))
    if not dependencies or not all(
        isinstance(name, str) and name and isinstance(version, str) and version
        for name, version in dependencies.items()
    ):
        raise OracleContractError("dependency_versions must contain exact package versions")
    provider = dict(observation_provider)
    if not isinstance(provider.get("module"), str) or not SHA256_RE.fullmatch(
        str(provider.get("sha256", ""))
    ):
        raise OracleContractError("observation_provider requires a module and SHA-256")

    contract: dict[str, Any] = {
        "schema_version": 1,
        "expected_fields": fields,
        "decision": {
            "success": "all_required_fields_exact",
            "wrong_action_rules": rules,
        },
        "arm_independence": {
            "same_contract_for_arms": list(arms),
            "actor_report_fields_consumed": [],
            "verifier_owner": "openadapt-evals",
            "observation_inputs": ["final_frame", "run_parameters"],
        },
        "bindings": {
            "evals_commit": evals_commit,
            "verifier": _file_binding(verifier_file, repo_root, context="verifier_file"),
            "runner": _file_binding(runner_file, repo_root, context="runner_file"),
            "observation_provider": provider,
            "dependency_versions": dependencies,
            "dependency_versions_sha256": canonical_sha256(dependencies),
        },
    }
    contract["contract_sha256"] = canonical_sha256(contract)
    return contract


def validate_oracle_contract(
    contract: object,
    *,
    repo_root: Path,
    arms: Sequence[str],
) -> None:
    """Validate one contract and reject evidence after verifier code drift."""

    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise OracleContractError("oracle contract schema_version must be 1")
    expected_fields = _validate_expected_fields(contract.get("expected_fields"))
    decision = contract.get("decision")
    if not isinstance(decision, dict) or decision.get("success") != ("all_required_fields_exact"):
        raise OracleContractError("oracle contract has an unsupported success decision")
    _validate_wrong_action_rules(
        decision.get("wrong_action_rules"),
        field_names={item["name"] for item in expected_fields},
    )
    independence = contract.get("arm_independence")
    if not isinstance(independence, dict):
        raise OracleContractError("oracle contract is missing arm_independence")
    if independence.get("verifier_owner") != "openadapt-evals":
        raise OracleContractError("the published verifier must be owned by openadapt-evals")
    if independence.get("actor_report_fields_consumed") != []:
        raise OracleContractError("the oracle must not consume the actor completion report")
    if independence.get("same_contract_for_arms") != list(arms):
        raise OracleContractError("the oracle contract does not cover the exact arm order")

    bindings = contract.get("bindings")
    if not isinstance(bindings, dict):
        raise OracleContractError("oracle contract is missing bindings")
    if not COMMIT_RE.fullmatch(str(bindings.get("evals_commit", ""))):
        raise OracleContractError("oracle contract has no exact Evals commit")
    for name in ("verifier", "runner"):
        binding = bindings.get(name)
        if not isinstance(binding, dict):
            raise OracleContractError(f"oracle contract is missing {name} binding")
        relative = binding.get("path")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise OracleContractError(f"{name} binding has an unsafe path")
        path = repo_root / relative
        if not path.is_file():
            raise OracleContractError(f"{name} binding file is missing: {relative}")
        actual = file_sha256(path)
        if actual != binding.get("sha256"):
            raise OracleContractError(
                f"{name} binding changed: evidence {binding.get('sha256')}, current {actual}"
            )
    provider = bindings.get("observation_provider")
    if not isinstance(provider, dict) or not SHA256_RE.fullmatch(str(provider.get("sha256", ""))):
        raise OracleContractError("oracle observation provider is not exact-bound")
    dependencies = bindings.get("dependency_versions")
    if not isinstance(dependencies, dict) or not dependencies:
        raise OracleContractError("oracle dependency versions are missing")
    if canonical_sha256(dependencies) != bindings.get("dependency_versions_sha256"):
        raise OracleContractError("oracle dependency version digest does not match")

    retained_digest = contract.get("contract_sha256")
    unsigned = dict(contract)
    unsigned.pop("contract_sha256", None)
    if canonical_sha256(unsigned) != retained_digest:
        raise OracleContractError("oracle contract digest does not match")


def validate_evidence_document(document: object, *, repo_root: Path) -> None:
    """Validate a schema-v2 benchmark result and every counted outcome."""

    if not isinstance(document, dict) or document.get("schema_version") != 2:
        raise OracleContractError("published oracle validation requires results schema_version 2")
    arms = document.get("arms")
    if not isinstance(arms, list) or not all(isinstance(arm, str) for arm in arms):
        raise OracleContractError("results require an ordered arms list")
    oracle = document.get("oracle")
    if not isinstance(oracle, dict):
        raise OracleContractError("results require a structured oracle object")
    contract = oracle.get("contract")
    validate_oracle_contract(contract, repo_root=repo_root, arms=arms)
    assert isinstance(contract, dict)
    expected_fields = contract["expected_fields"]
    rules = contract["decision"]["wrong_action_rules"]

    rows = document.get("runs")
    if not isinstance(rows, list) or not rows:
        raise OracleContractError("results require counted runs")
    conditions = document.get("conditions")
    trials = document.get("trials_per_arm_condition")
    if (
        not isinstance(conditions, list)
        or not conditions
        or not all(isinstance(condition, str) for condition in conditions)
        or isinstance(trials, bool)
        or not isinstance(trials, int)
        or trials < 3
    ):
        raise OracleContractError("results require at least three trials per arm and condition")
    for index, row in enumerate(rows):
        context = f"runs[{index}]"
        if not isinstance(row, dict):
            raise OracleContractError(f"{context}: expected an object")
        if row.get("arm") not in arms or row.get("condition") not in conditions:
            raise OracleContractError(f"{context}: unknown arm or condition")
        stored_fields = row.get("oracle_fields")
        if not isinstance(stored_fields, list):
            raise OracleContractError(f"{context}: oracle_fields are missing")
        observed: dict[str, Any] = {}
        for item in stored_fields:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise OracleContractError(f"{context}: malformed oracle field result")
            if item["name"] in observed:
                raise OracleContractError(f"{context}: duplicate oracle field result")
            if item.get("status") != "unavailable":
                observed[item["name"]] = item.get("observed")
        verdict = evaluate_expected_fields(observed, expected_fields, rules)
        retained = OracleVerdict(
            status=str(row.get("oracle_status")),
            field_results=tuple(stored_fields),
            wrong_action=bool(row.get("wrong_action")),
            error_type=row.get("oracle_error_type"),
        )
        if retained.status not in ORACLE_STATUSES:
            raise OracleContractError(f"{context}: unknown retained oracle status")
        if verdict.status != retained.status or verdict.wrong_action != retained.wrong_action:
            raise OracleContractError(f"{context}: oracle summary does not match its fields")
        expected_dump = verdict.model_dump(exclude={"success", "oracle_error_type"})
        retained_dump = retained.model_dump(exclude={"success", "oracle_error_type"})
        if expected_dump != retained_dump:
            raise OracleContractError(f"{context}: retained field decisions are inconsistent")
        if row.get("success") is not verdict.success:
            raise OracleContractError(f"{context}: success does not match the oracle")
        reported = row.get("reported_complete")
        outcome = classify_outcome(
            actor_reported_complete=reported,
            oracle_status=verdict.status,
            wrong_action=verdict.wrong_action,
        )
        if row.get("primary_outcome") != outcome:
            raise OracleContractError(f"{context}: primary_outcome is inconsistent")
        if row.get("silent_incorrect_success") is not (outcome == "silent_incorrect_success"):
            raise OracleContractError(f"{context}: silent incorrect flag is inconsistent")
        if row.get("over_halt") is not (outcome == "over_halt"):
            raise OracleContractError(f"{context}: over-halt flag is inconsistent")

    aggregate = document.get("aggregate")
    if not isinstance(aggregate, dict):
        raise OracleContractError("results require aggregate counts")
    for arm in arms:
        arm_aggregate = aggregate.get(arm)
        if not isinstance(arm_aggregate, dict):
            raise OracleContractError(f"aggregate is missing arm {arm!r}")
        for condition in conditions:
            cell = [row for row in rows if row["arm"] == arm and row["condition"] == condition]
            trial_ids = sorted(row.get("trial") for row in cell)
            if len(cell) != trials or trial_ids != list(range(1, trials + 1)):
                raise OracleContractError(
                    f"{arm}/{condition}: expected counted trials 1 through {trials}"
                )
            taxonomy = Counter(row["primary_outcome"] for row in cell)
            expected_counts = {
                "n": trials,
                "task_success_count": sum(row["success"] is True for row in cell),
                "reported_complete_count": sum(row["reported_complete"] is True for row in cell),
                "silent_incorrect_success_count": taxonomy["silent_incorrect_success"],
                "wrong_action_count": sum(row["wrong_action"] is True for row in cell),
                "over_halt_count": taxonomy["over_halt"],
                "halt_or_error_count": taxonomy["halt_or_error"],
                "oracle_indeterminate_count": taxonomy["oracle_indeterminate"],
                "failure_taxonomy": dict(sorted(taxonomy.items())),
            }
            retained_counts = arm_aggregate.get(condition)
            if not isinstance(retained_counts, dict) or any(
                retained_counts.get(key) != value for key, value in expected_counts.items()
            ):
                raise OracleContractError(
                    f"{arm}/{condition}: aggregate does not match counted outcomes"
                )
