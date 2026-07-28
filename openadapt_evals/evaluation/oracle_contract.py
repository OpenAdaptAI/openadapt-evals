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
import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ORACLE_STATUSES = {"confirmed", "refuted", "unavailable"}
DEPENDENCY_BINDING_RE = re.compile(
    r"^(?P<distribution>[A-Za-z0-9][A-Za-z0-9_.-]*)==(?P<version>[^;\s]+);"
    r"module_sha256=(?P<sha256>[0-9a-f]{64})$"
)


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
    if not any(item["purpose"] == "effect" for item in validated):
        raise OracleContractError("oracle contract requires at least one effect field")
    return validated


def _validate_dimension(values: object, *, name: str) -> list[str]:
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(value, str) and value for value in values)
        or len(values) != len(set(values))
    ):
        raise OracleContractError(f"{name} must be a non-empty unique string list")
    return values


def _validate_dependency_versions(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise OracleContractError("oracle dependency versions are missing")
    dependencies: dict[str, str] = {}
    for module_name, binding in value.items():
        if (
            not isinstance(module_name, str)
            or not module_name
            or not isinstance(binding, str)
            or DEPENDENCY_BINDING_RE.fullmatch(binding) is None
            or "unknown" in binding.lower()
        ):
            raise OracleContractError(
                "dependency_versions must bind each module to an exact distribution, "
                "version, and module SHA-256"
            )
        dependencies[module_name] = binding
    return dict(sorted(dependencies.items()))


def _validate_observation_provider(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise OracleContractError("oracle observation provider is missing")
    required = ("distribution", "version", "module", "path_in_artifact", "sha256")
    if not all(isinstance(value.get(key), str) and value[key] for key in required):
        raise OracleContractError(
            "observation_provider requires distribution, version, module, "
            "path_in_artifact, and SHA-256"
        )
    path = Path(value["path_in_artifact"])
    if path.is_absolute() or ".." in path.parts:
        raise OracleContractError("observation_provider path_in_artifact is unsafe")
    if not SHA256_RE.fullmatch(value["sha256"]):
        raise OracleContractError("oracle observation provider is not exact-bound")
    artifact_sha = value.get("artifact_sha256")
    if artifact_sha is not None and not SHA256_RE.fullmatch(str(artifact_sha)):
        raise OracleContractError("observation_provider artifact SHA-256 is invalid")
    return {key: str(item) for key, item in value.items()}


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
    validated_arms = _validate_dimension(list(arms), name="arms")
    fields = _validate_expected_fields([dict(item) for item in expected_fields])
    rules = _validate_wrong_action_rules(
        [dict(item) for item in wrong_action_rules],
        field_names={item["name"] for item in fields},
    )
    dependencies = _validate_dependency_versions(dict(dependency_versions))
    provider = _validate_observation_provider(dict(observation_provider))

    contract: dict[str, Any] = {
        "schema_version": 1,
        "expected_fields": fields,
        "decision": {
            "success": "all_required_fields_exact",
            "wrong_action_rules": rules,
        },
        "arm_independence": {
            "same_contract_for_arms": validated_arms,
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
    validated_arms = _validate_dimension(list(arms), name="arms")
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
    if independence.get("same_contract_for_arms") != validated_arms:
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
    _validate_observation_provider(bindings.get("observation_provider"))
    dependencies = _validate_dependency_versions(bindings.get("dependency_versions"))
    if canonical_sha256(dependencies) != bindings.get("dependency_versions_sha256"):
        raise OracleContractError("oracle dependency version digest does not match")

    retained_digest = contract.get("contract_sha256")
    unsigned = dict(contract)
    unsigned.pop("contract_sha256", None)
    if canonical_sha256(unsigned) != retained_digest:
        raise OracleContractError("oracle contract digest does not match")


def _nonnegative_number(value: object, *, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OracleContractError(f"{context}: expected a non-negative finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise OracleContractError(f"{context}: expected a non-negative finite number")
    return result


def _nearest_rank(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _expected_aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    steady = [float(row["steady_wall_s"]) for row in rows]
    end_to_end = [float(row["end_to_end_wall_s"]) for row in rows]
    taxonomy = Counter(row["primary_outcome"] for row in rows)
    return {
        "n": len(rows),
        "task_success_count": sum(row["success"] is True for row in rows),
        "task_success_rate": sum(row["success"] is True for row in rows) / len(rows),
        "reported_complete_count": sum(row["reported_complete"] is True for row in rows),
        "silent_incorrect_success_count": taxonomy["silent_incorrect_success"],
        "wrong_action_count": sum(row["wrong_action"] is True for row in rows),
        "over_halt_count": taxonomy["over_halt"],
        "halt_or_error_count": taxonomy["halt_or_error"],
        "oracle_indeterminate_count": taxonomy["oracle_indeterminate"],
        "failure_taxonomy": dict(sorted(taxonomy.items())),
        "steady_wall_s_median": statistics.median(steady),
        "steady_wall_s_p95_nearest_rank": _nearest_rank(steady, 0.95),
        "end_to_end_wall_s_median": statistics.median(end_to_end),
        "end_to_end_wall_s_p95_nearest_rank": _nearest_rank(end_to_end, 0.95),
        "browser_oracle_teardown_overhead_s_median": statistics.median(
            row["end_to_end_wall_s"] - row["steady_wall_s"] for row in rows
        ),
        "model_calls_total": sum(row["api_calls"] for row in rows),
        "model_cost_usd_total": round(sum(row["cost_usd"] for row in rows), 8),
    }


def validate_evidence_document(document: object, *, repo_root: Path) -> None:
    """Validate a schema-v2 benchmark result and every counted outcome."""

    if not isinstance(document, dict) or document.get("schema_version") != 2:
        raise OracleContractError("published oracle validation requires results schema_version 2")
    arms = _validate_dimension(document.get("arms"), name="arms")
    oracle = document.get("oracle")
    if not isinstance(oracle, dict):
        raise OracleContractError("results require a structured oracle object")
    contract = oracle.get("contract")
    validate_oracle_contract(contract, repo_root=repo_root, arms=arms)
    assert isinstance(contract, dict)
    expected_fields = contract["expected_fields"]
    rules = contract["decision"]["wrong_action_rules"]
    bindings = contract["bindings"]

    source = document.get("source")
    if not isinstance(source, dict):
        raise OracleContractError("results require exact source bindings")
    evals_source = source.get("evals")
    if (
        not isinstance(evals_source, dict)
        or evals_source.get("commit") != bindings["evals_commit"]
        or evals_source.get("tracked_clean") is not True
    ):
        raise OracleContractError("results Evals source does not match the oracle contract")
    if source.get("runner_sha256") != bindings["runner"]["sha256"]:
        raise OracleContractError("results runner does not match the oracle contract")
    flow_source = source.get("flow")
    provider = bindings["observation_provider"]
    if not isinstance(flow_source, dict):
        raise OracleContractError("results require an exact Flow source")
    flow_version = flow_source.get("version")
    flow_commit = flow_source.get("commit")
    flow_artifact = flow_source.get("artifact")
    flow_tags = flow_source.get("tags")
    release_tag = f"v{flow_version}"
    if (
        not isinstance(flow_version, str)
        or not flow_version
        or not COMMIT_RE.fullmatch(str(flow_commit))
        or flow_source.get("tracked_clean") is not True
        or flow_source.get("release_tag") != release_tag
        or not isinstance(flow_tags, list)
        or not all(isinstance(tag, str) for tag in flow_tags)
        or release_tag not in flow_tags
        or not isinstance(flow_artifact, dict)
        or not isinstance(flow_artifact.get("filename"), str)
        or not flow_artifact["filename"].endswith(".whl")
        or not SHA256_RE.fullmatch(str(flow_artifact.get("sha256", "")))
        or flow_artifact.get("import_mode") != "locally extracted published wheel"
    ):
        raise OracleContractError("results require a release-tagged exact Flow source and wheel")
    if provider.get("distribution") != "openadapt-flow" or provider.get("version") != flow_version:
        raise OracleContractError("observation provider does not match the measured Flow release")
    if provider.get("artifact_sha256") != flow_artifact["sha256"]:
        raise OracleContractError("observation provider does not match the measured Flow wheel")

    environment = document.get("environment")
    if not isinstance(environment, dict):
        raise OracleContractError("results require exact environment provenance")
    chromium = environment.get("chromium")
    if (
        not isinstance(environment.get("platform"), str)
        or not environment["platform"]
        or not isinstance(environment.get("python"), str)
        or not environment["python"]
        or not isinstance(environment.get("playwright"), str)
        or not environment["playwright"]
        or not isinstance(chromium, dict)
        or not isinstance(chromium.get("version"), str)
        or not chromium["version"]
        or not SHA256_RE.fullmatch(str(chromium.get("executable_sha256", "")))
    ):
        raise OracleContractError("results environment provenance is incomplete")
    playwright_binding = bindings["dependency_versions"].get("playwright")
    playwright_match = (
        DEPENDENCY_BINDING_RE.fullmatch(playwright_binding)
        if isinstance(playwright_binding, str)
        else None
    )
    if (
        playwright_match is None
        or playwright_match.group("distribution") != "playwright"
        or playwright_match.group("version") != environment["playwright"]
    ):
        raise OracleContractError("Playwright environment does not match the dependency binding")

    rows = document.get("runs")
    if not isinstance(rows, list) or not rows:
        raise OracleContractError("results require counted runs")
    conditions = _validate_dimension(document.get("conditions"), name="conditions")
    trials = document.get("trials_per_arm_condition")
    if isinstance(trials, bool) or not isinstance(trials, int) or trials < 3:
        raise OracleContractError("results require at least three trials per arm and condition")
    for index, row in enumerate(rows):
        context = f"runs[{index}]"
        if not isinstance(row, dict):
            raise OracleContractError(f"{context}: expected an object")
        if row.get("arm") not in arms or row.get("condition") not in conditions:
            raise OracleContractError(f"{context}: unknown arm or condition")
        if isinstance(row.get("trial"), bool) or not isinstance(row.get("trial"), int):
            raise OracleContractError(f"{context}: trial must be an integer")
        if type(row.get("reported_complete")) is not bool:
            raise OracleContractError(f"{context}: reported_complete must be a boolean")
        if type(row.get("wrong_action")) is not bool:
            raise OracleContractError(f"{context}: wrong_action must be a boolean")
        if type(row.get("success")) is not bool:
            raise OracleContractError(f"{context}: success must be a boolean")
        for field_name in ("steady_wall_s", "end_to_end_wall_s", "cost_usd"):
            _nonnegative_number(row.get(field_name), context=f"{context}.{field_name}")
        api_calls = row.get("api_calls")
        if isinstance(api_calls, bool) or not isinstance(api_calls, int) or api_calls < 0:
            raise OracleContractError(f"{context}.api_calls: expected a non-negative integer")
        if row["end_to_end_wall_s"] < row["steady_wall_s"]:
            raise OracleContractError(f"{context}: end-to-end time is less than steady time")
        if not SHA256_RE.fullmatch(str(row.get("note_sha256", ""))):
            raise OracleContractError(f"{context}: note SHA-256 is missing")
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
        error_type = row.get("oracle_error_type")
        if retained.status == "unavailable":
            if not isinstance(error_type, str) or not error_type:
                raise OracleContractError(f"{context}: unavailable oracle requires an error type")
        elif error_type is not None:
            raise OracleContractError(f"{context}: scored oracle cannot retain an error type")
        screenshot_sha = row.get("final_screenshot_sha256")
        if retained.status != "unavailable" and not SHA256_RE.fullmatch(str(screenshot_sha or "")):
            raise OracleContractError(f"{context}: scored result requires a final screenshot hash")
        if screenshot_sha is not None and not SHA256_RE.fullmatch(str(screenshot_sha)):
            raise OracleContractError(f"{context}: invalid final screenshot hash")
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
            expected_counts = _expected_aggregate(cell)
            retained_counts = arm_aggregate.get(condition)
            if not isinstance(retained_counts, dict) or any(
                retained_counts.get(key) != value for key, value in expected_counts.items()
            ):
                raise OracleContractError(
                    f"{arm}/{condition}: aggregate does not match counted outcomes"
                )
