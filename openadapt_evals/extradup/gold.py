"""Gold write specs for ExtraDup.

Each spec is one CREATE. Mutants that change cardinality or add a field
are gold FAIL. Duplicate-CREATE is killed by ``|new(M)| = |spec(M)|``,
not by field-value inclusion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class WriteSpec:
    """One intended CREATE against a system of record.

    ``expected_new`` is ``|spec(M)|``. ``allowed_fields`` is every key a
    legitimate write may persist, including store-assigned identity. A field
    outside this set is Extra-Field.
    """

    env: str
    collection: str
    fields: Mapping[str, str]
    expected_new: int
    allowed_fields: frozenset[str]
    extra_field: str
    extra_value: str
    omit_field: str


# MockMed triage-save, the same synthetic encounter the Flow fault server
# persists at GET /api/db. All values are fake.
MOCKMED_GOLD = WriteSpec(
    env="mockmed",
    collection="encounters",
    fields={
        "patient_id": "p1",
        "type": "Triage",
        "note": "Follow-up in 2 weeks; BP recheck.",
    },
    expected_new=1,
    allowed_fields=frozenset(
        {"id", "patient_id", "type", "note", "source", "key"}
    ),
    extra_field="priority",
    extra_value="stat",
    omit_field="note",
)


# OpenEMR-shaped local patient CREATE. Mirrors the ``patient_data`` row
# the pinned openemr_local fixture writes; this kit does not start Docker.
OPENEMR_GOLD = WriteSpec(
    env="openemr_local",
    collection="patient_data",
    fields={
        "pubpid": "MRN-0042",
        "fname": "Taylor",
        "lname": "Duplicate",
    },
    expected_new=1,
    allowed_fields=frozenset(
        {"id", "pid", "pubpid", "fname", "lname", "source"}
    ),
    extra_field="occupation",
    extra_value="Hardware",
    omit_field="lname",
)


GOLD_SPECS: tuple[WriteSpec, ...] = (MOCKMED_GOLD, OPENEMR_GOLD)
