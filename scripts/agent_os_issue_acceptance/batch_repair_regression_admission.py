"""Deterministic regression-evidence admission for bounded bulk PR repair.

This module classifies already-supplied evidence only. It does not inspect diffs,
run tests, perform semantic review, grant merge authority, or mutate any system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class RegressionEvidenceKind(str, Enum):
    PROSE_EXISTENCE = "prose-existence"
    POLICY_STRUCTURE = "policy-structure"
    EXECUTABLE_CONTRACT = "executable-contract"
    EXTERNAL_CONFORMANCE = "external-conformance"
    UNKNOWN = "unknown"


class RegressionAdmission(str, Enum):
    REPAIR_REQUIRED = "repair-required"
    ADMISSIBLE = "admissible"
    CONFORMANCE_HANDOFF_REQUIRED = "conformance-handoff-required"
    MANUAL_REVIEW = "manual-review"


@dataclass(frozen=True, slots=True)
class RegressionEvidence:
    kind: RegressionEvidenceKind
    changed_test_only: bool
    governed_contract_is_prose: bool = False
    executable_contract_exercised: bool = False
    external_owner_confirmed: bool = False
    conformance_fixture_present: bool = False

    def __post_init__(self) -> None:
        if type(self.kind) is not RegressionEvidenceKind:
            raise TypeError("kind must be RegressionEvidenceKind")
        for name in (
            "changed_test_only",
            "governed_contract_is_prose",
            "executable_contract_exercised",
            "external_owner_confirmed",
            "conformance_fixture_present",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must use built-in bool")


@dataclass(frozen=True, slots=True)
class RegressionAdmissionResult:
    admission: RegressionAdmission
    reason_codes: tuple[str, ...]
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def evaluate_regression_admission(evidence: RegressionEvidence) -> RegressionAdmissionResult:
    """Classify whether supplied regression evidence is meaningful enough to advance.

    The caller remains responsible for code review, test execution, exact-head
    validation, and every later lifecycle or merge gate.
    """
    if type(evidence) is not RegressionEvidence:
        raise TypeError("evidence must be RegressionEvidence")

    if evidence.kind is RegressionEvidenceKind.PROSE_EXISTENCE:
        if evidence.governed_contract_is_prose:
            return _result(RegressionAdmission.ADMISSIBLE, "governed-policy-text-is-contract")
        return _result(RegressionAdmission.REPAIR_REQUIRED, "incidental-prose-does-not-prove-behavior")

    if evidence.kind is RegressionEvidenceKind.POLICY_STRUCTURE:
        if evidence.governed_contract_is_prose:
            return _result(RegressionAdmission.ADMISSIBLE, "policy-structure-is-governed-contract")
        return _result(RegressionAdmission.MANUAL_REVIEW, "policy-structure-ownership-unresolved")

    if evidence.kind is RegressionEvidenceKind.EXECUTABLE_CONTRACT:
        if evidence.executable_contract_exercised:
            return _result(RegressionAdmission.ADMISSIBLE, "smallest-executable-contract-exercised")
        return _result(RegressionAdmission.REPAIR_REQUIRED, "executable-contract-not-exercised")

    if evidence.kind is RegressionEvidenceKind.EXTERNAL_CONFORMANCE:
        if not evidence.external_owner_confirmed:
            return _result(RegressionAdmission.MANUAL_REVIEW, "external-owner-unresolved")
        if evidence.conformance_fixture_present:
            return _result(RegressionAdmission.ADMISSIBLE, "external-conformance-fixture-present")
        return _result(RegressionAdmission.CONFORMANCE_HANDOFF_REQUIRED, "external-conformance-fixture-missing")

    return _result(RegressionAdmission.MANUAL_REVIEW, "regression-evidence-kind-unknown")


def _result(admission: RegressionAdmission, *reasons: str) -> RegressionAdmissionResult:
    return RegressionAdmissionResult(admission=admission, reason_codes=tuple(reasons))
