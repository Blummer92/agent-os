"""Regression matrix for #2370 strict lowercase commit-SHA identity.

Every listed `scripts/agent_os_pr_remediation/` commit-SHA validator must accept
exactly 40 lowercase hexadecimal characters and *reject* non-canonical casing
rather than normalize it with `.lower()`. Silent case-widening turns a
non-canonical commit identity into an accepted one, which defeats the exact-head
correctness boundary these validators exist to enforce.

Each validator keeps its own exception type, message, and return contract, so the
matrix pins those per module instead of asserting a shared contract that #2370
explicitly does not create.
"""

from __future__ import annotations

import pytest

from scripts.agent_os_pr_remediation import (
    code_review_benchmark,
    evidence_assembly,
    merge_evidence_summary,
    review_coverage,
    review_evidence,
    review_findings,
)
from scripts.agent_os_pr_remediation.models import EvidenceValidationError

LOWER = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
UPPER = LOWER.upper()
MIXED = "A1b2c3d4e5f60718293a4b5c6d7e8f9012345678"

SHA_MESSAGE = "must be a 40-character hexadecimal SHA"

# (id, module, callable taking one value, field name used in the pinned message,
#  message fragment raised when the value is not usable text)
VALIDATORS = [
    (
        "review_coverage",
        lambda value: review_coverage._sha(value, "current_head_sha"),
        "current_head_sha",
        "must be a bounded non-empty string",
    ),
    (
        "review_findings",
        lambda value: review_findings._sha(value, "current_head_sha"),
        "current_head_sha",
        "must be a bounded non-empty string",
    ),
    (
        "review_evidence",
        lambda value: review_evidence._sha(value, "current_head"),
        "current_head",
        "must be a bounded non-empty string",
    ),
    (
        "evidence_assembly",
        lambda value: evidence_assembly._sha(value, "head_sha"),
        "head_sha",
        "must be exactly str",
    ),
    (
        "code_review_benchmark",
        lambda value: code_review_benchmark._sha(value),
        "source_head_sha",
        "must be a bounded non-empty string",
    ),
    (
        "merge_evidence_summary",
        lambda value: merge_evidence_summary._sha(value, "source_head_sha"),
        "source_head_sha",
        "must be a bounded non-empty string",
    ),
]

VALIDATOR_IDS = [item[0] for item in VALIDATORS]
VALIDATOR_CASES = [pytest.param(*item[1:], id=item[0]) for item in VALIDATORS]


@pytest.mark.parametrize(("validate", "field", "text_message"), VALIDATOR_CASES)
def test_canonical_lowercase_sha_is_accepted_unchanged(validate, field, text_message) -> None:
    """A canonical identity must survive validation byte-for-byte."""
    assert validate(LOWER) == LOWER


@pytest.mark.parametrize("value", [UPPER, MIXED], ids=["uppercase", "mixed-case"])
@pytest.mark.parametrize(("validate", "field", "text_message"), VALIDATOR_CASES)
def test_non_canonical_casing_is_rejected_not_normalized(
    validate, field, text_message, value
) -> None:
    """Uppercase and mixed case must raise, never be lowered into acceptance."""
    with pytest.raises(EvidenceValidationError) as excinfo:
        validate(value)
    assert str(excinfo.value) == f"{field} {SHA_MESSAGE}"


@pytest.mark.parametrize(
    "value",
    [LOWER[:39], LOWER + "0", LOWER[:39] + "g", LOWER[:39] + "z", LOWER[:39] + "-"],
    ids=["short", "long", "non-hex-g", "non-hex-z", "non-hex-dash"],
)
@pytest.mark.parametrize(("validate", "field", "text_message"), VALIDATOR_CASES)
def test_malformed_length_and_non_hex_are_rejected(validate, field, text_message, value) -> None:
    """Length and alphabet failures keep the validator's own pinned message."""
    with pytest.raises(EvidenceValidationError) as excinfo:
        validate(value)
    assert str(excinfo.value) == f"{field} {SHA_MESSAGE}"


@pytest.mark.parametrize(
    "value",
    [None, 0, 1234567890, b"a" * 40, LOWER.encode(), [], {}],
    ids=["none", "zero", "int", "bytes", "encoded-bytes", "list", "dict"],
)
@pytest.mark.parametrize(("validate", "field", "text_message"), VALIDATOR_CASES)
def test_malformed_types_are_rejected_by_the_local_contract(
    validate, field, text_message, value
) -> None:
    """Non-string input is refused by each module's existing type guard."""
    with pytest.raises(EvidenceValidationError) as excinfo:
        validate(value)
    assert text_message in str(excinfo.value)


@pytest.mark.parametrize(("validate", "field", "text_message"), VALIDATOR_CASES)
def test_empty_string_is_rejected_by_each_local_contract(validate, field, text_message) -> None:
    """Empty input is refused, by whichever guard each module reaches first.

    `evidence_assembly` type-checks with `_exact(value, str, ...)`, so an empty
    string is a valid `str` there and fails the length guard instead of the text
    guard. #2370 preserves that per-module difference rather than unifying it.
    """
    with pytest.raises(EvidenceValidationError) as excinfo:
        validate("")
    expected = SHA_MESSAGE if text_message == "must be exactly str" else text_message
    assert expected in str(excinfo.value)


def test_every_listed_module_is_covered_by_this_matrix() -> None:
    """Guard against a listed #2370 surface silently dropping out of coverage."""
    assert VALIDATOR_IDS == [
        "review_coverage",
        "review_findings",
        "review_evidence",
        "evidence_assembly",
        "code_review_benchmark",
        "merge_evidence_summary",
    ]


@pytest.mark.parametrize("value", [UPPER, MIXED], ids=["uppercase", "mixed-case"])
def test_public_validation_evidence_seam_rejects_non_canonical_casing(value) -> None:
    """Strictness must reach the public seam, not only the module-local helper."""
    with pytest.raises(EvidenceValidationError) as excinfo:
        merge_evidence_summary.validation_evidence(
            name="aggregate",
            status=merge_evidence_summary.EvidenceStatus.PASSED,
            tested_sha=value,
        )
    assert str(excinfo.value) == f"tested_sha {SHA_MESSAGE}"


@pytest.mark.parametrize("value", [UPPER, MIXED], ids=["uppercase", "mixed-case"])
def test_public_invalidation_scope_seam_rejects_non_canonical_casing(value) -> None:
    """The review-evidence public seam must not accept a non-canonical head."""
    with pytest.raises(EvidenceValidationError) as excinfo:
        review_evidence.review_invalidation_scope(
            prior_reviewed_head=LOWER,
            current_head=value,
            changed_paths_since_review=("scripts/a.py",),
            material_change_kinds=("behavior",),
            previously_reviewed_paths=("scripts/a.py",),
        )
    assert str(excinfo.value) == f"current_head {SHA_MESSAGE}"


def test_optional_sha_seams_still_accept_none() -> None:
    """Strict casing must not break the existing optional-SHA return contract."""
    assert review_evidence._sha(None, "exact_tested_sha", optional=True) is None
    assert merge_evidence_summary._sha(None, "base_sha", optional=True) is None


@pytest.mark.parametrize("value", ["A" * 64, "a" * 63, "g" * 64], ids=["upper", "short", "non-hex"])
def test_sha256_fingerprint_normalization_is_unchanged(value) -> None:
    """#2370 is scoped to commit identity; SHA-256 digests keep their behavior.

    `_fingerprint` still lowercases, so an uppercase digest remains accepted.
    This pins the out-of-scope contract so the commit-SHA repair cannot quietly
    widen into metadata/fingerprint normalization.
    """
    if value == "A" * 64:
        assert merge_evidence_summary._fingerprint(value, "metadata_fingerprint") == "a" * 64
        return
    with pytest.raises(EvidenceValidationError) as excinfo:
        merge_evidence_summary._fingerprint(value, "metadata_fingerprint")
    assert str(excinfo.value) == "metadata_fingerprint must be a SHA-256 hexadecimal digest"


def test_no_listed_validator_retains_case_widening_normalization() -> None:
    """Fail loudly if a `.lower()` returns to a commit-SHA validator's body.

    A reader can restore `.lower()` in one module and every behavioral test above
    still passes for the other five, so this asserts the absence directly.
    """
    import inspect

    modules = {
        "review_coverage": review_coverage,
        "review_findings": review_findings,
        "review_evidence": review_evidence,
        "evidence_assembly": evidence_assembly,
        "code_review_benchmark": code_review_benchmark,
        "merge_evidence_summary": merge_evidence_summary,
    }
    offenders = [
        name for name, module in modules.items() if ".lower()" in inspect.getsource(module._sha)
    ]
    assert offenders == []
