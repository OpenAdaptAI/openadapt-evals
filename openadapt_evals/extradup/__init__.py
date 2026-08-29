"""ExtraDup: this trajectory is wrong; does your checker notice?

Public kit against MockMed and an OpenEMR-shaped local store. Does not
vendor AppWorld evaluation.py, does not unseal HOLDOUT, does not patch
WorkArena.
"""

from openadapt_evals.extradup.gold import MOCKMED_GOLD, OPENEMR_GOLD, WriteSpec
from openadapt_evals.extradup.mutations import OPERATORS, apply
from openadapt_evals.extradup.seal import REFUSED, VERIFIED, seal_verdict
from openadapt_evals.extradup.suite import (
    SUITE_LABEL,
    SUITE_NAME,
    CellReport,
    check_invariants,
    run_cell,
)

__all__ = [
    "CellReport",
    "MOCKMED_GOLD",
    "OPENEMR_GOLD",
    "OPERATORS",
    "REFUSED",
    "SUITE_LABEL",
    "SUITE_NAME",
    "VERIFIED",
    "WriteSpec",
    "apply",
    "check_invariants",
    "run_cell",
    "seal_verdict",
]
