from __future__ import annotations

import pytest

from instructional_workflow_contracts import (
    AuthorityEvidence,
    ContractValidationError,
    ValidationResult,
    ValidationStatus,
    resolve_status,
    validate_reason_code,
)


@pytest.mark.parametrize(
    "reason_code",
    [
        "lp-pacing-insufficient-instruction-time",
        "lp-evidence-insufficient-comparable-runs",
        "lp-pathway-speed-only-eligibility",
    ],
)
def test_lp_reason_namespace_is_syntax_only(reason_code: str) -> None:
    assert validate_reason_code(reason_code) == reason_code

    result = ValidationResult(
        status=ValidationStatus.INVALID,
        record=None,
        reason_codes=(reason_code,),
    )
    assert result.reason_codes == (reason_code,)
    assert result.authority == AuthorityEvidence()

    with pytest.raises(ContractValidationError) as caught:
        resolve_status((reason_code,))
    assert caught.value.reason_code == "handoff-invalid"


@pytest.mark.parametrize(
    "reason_code",
    [
        "lp",
        "lp-",
        "LP-pacing-insufficient-instruction-time",
        "lp-Pacing-insufficient-instruction-time",
        "lp-pacing invalid",
        "lp-" + "x" * 125,
    ],
)
def test_lp_reason_namespace_rejects_malformed_values(reason_code: str) -> None:
    with pytest.raises((ContractValidationError, ValueError)):
        validate_reason_code(reason_code)


@pytest.mark.parametrize(
    "reason_code",
    [
        "source-invalid",
        "handoff-invalid",
        "manual-review-inspection",
        "material-invalid",
        "quality-invalid",
    ],
)
def test_existing_reason_namespaces_remain_accepted(reason_code: str) -> None:
    assert validate_reason_code(reason_code) == reason_code


def test_lp_reason_ordering_and_duplicate_rejection_remain_canonical() -> None:
    result = ValidationResult(
        status=ValidationStatus.INVALID,
        record=None,
        reason_codes=(
            "lp-pathway-speed-only-eligibility",
            "lp-evidence-insufficient-comparable-runs",
        ),
    )
    assert result.reason_codes == (
        "lp-evidence-insufficient-comparable-runs",
        "lp-pathway-speed-only-eligibility",
    )

    with pytest.raises(ContractValidationError) as caught:
        ValidationResult(
            status=ValidationStatus.INVALID,
            record=None,
            reason_codes=(
                "lp-evidence-insufficient-comparable-runs",
                "lp-evidence-insufficient-comparable-runs",
            ),
        )
    assert caught.value.reason_code == "handoff-duplicate"
