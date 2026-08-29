"""ExtraDup kit: SoR cardinality kills Extra-NI; Seal must refuse it."""

from __future__ import annotations

import pytest

from openadapt_evals.extradup import (
    MOCKMED_GOLD,
    REFUSED,
    VERIFIED,
    apply,
    check_invariants,
    run_cell,
    seal_verdict,
)
from openadapt_evals.extradup.checkers import (
    field_inclusion_check,
    new_records,
    sor_check,
    visual_only_check,
)
from openadapt_evals.extradup.store import MockMedStore
from openadapt_evals.extradup.suite import main


def test_seal_verified_path_refuses_extra_ni_on_mockmed() -> None:
    """A Seal/VERIFIED path must refuse Extra-NI on MockMed.

    Duplicate-CREATE is gold FAIL. Field-inclusion still PASSes. VERIFIED
    is forbidden.
    """
    report = run_cell("mockmed:dup")
    assert report.gold == "FAIL"
    assert report.sor == "FAIL"
    assert report.new_count != report.spec_count
    assert report.field_inclusion == "PASS"
    assert report.visual_only == "PASS"
    assert report.seal == REFUSED
    assert report.seal != VERIFIED

    store = MockMedStore()
    before, after, _screen = apply(store, MOCKMED_GOLD, "dup")
    assert seal_verdict(MOCKMED_GOLD, before, after) == REFUSED
    assert "|new(M)|=" in ";".join(sor_check(MOCKMED_GOLD, before, after).reasons)


def test_dup_killed_by_cardinality_not_field_inclusion() -> None:
    store = MockMedStore()
    before, after, screen = apply(store, MOCKMED_GOLD, "dup")
    added = new_records(before, after)
    assert len(added) == 2
    assert MOCKMED_GOLD.expected_new == 1
    assert sor_check(MOCKMED_GOLD, before, after).verdict == "FAIL"
    assert field_inclusion_check(MOCKMED_GOLD, after).verdict == "PASS"
    assert visual_only_check(screen).verdict == "PASS"


def test_extra_field_killed_by_sor_not_inclusion() -> None:
    for cell in ("mockmed:extra", "openemr:extra"):
        report = run_cell(cell)
        assert report.gold == "FAIL"
        assert report.sor == "FAIL"
        assert report.field_inclusion == "PASS"
        assert report.visual_only == "PASS"
        assert report.seal == REFUSED
        assert any("extra field" in reason for reason in report.sor_reasons)


@pytest.mark.parametrize("operator", ["omit", "unsubmit", "claim"])
@pytest.mark.parametrize("env", ["mockmed", "openemr"])
def test_mutant_gold_is_fail(env: str, operator: str) -> None:
    report = run_cell(f"{env}:{operator}")
    assert report.gold == "FAIL"
    assert report.sor == "FAIL"
    assert report.seal == REFUSED
    assert report.visual_only == "PASS"


def test_control_is_verified() -> None:
    for env in ("mockmed", "openemr"):
        report = run_cell(f"{env}:control")
        assert report.gold == "PASS"
        assert report.sor == "PASS"
        assert report.seal == VERIFIED
        assert report.new_count == report.spec_count == 1


def test_openemr_shaped_dup_is_extra_ni() -> None:
    report = run_cell("openemr:dup")
    assert report.env == "openemr_local"
    assert report.gold == "FAIL"
    assert report.sor == "FAIL"
    assert report.field_inclusion == "PASS"
    assert report.seal == REFUSED


def test_check_invariants_hold() -> None:
    assert check_invariants() == []


def test_python_module_check() -> None:
    assert main(["check"]) == 0
    assert main(["list"]) == 0
    assert main(["run", "mockmed:dup"]) == 0
    assert main(["run", "mockmed:control"]) == 0
