"""Regression matrix for #2274 fail-safe SHA validator reconciliation."""

import pytest

from scripts.agent_os_issue_labels.pr_branch_refresh_actions_runner import _sha40 as refresh_sha40
from scripts.agent_os_pr_remediation.aggregate_failure_provenance import _sha as aggregate_sha
from scripts.agent_os_pr_remediation.ci_evidence_recovery import _sha40 as recovery_sha40
from scripts.agent_os_pr_remediation.coordination import _sha40 as coordination_sha40
from scripts.agent_os_pr_remediation.normalization import _sha as normalization_sha
from scripts.agent_os_pr_remediation.preflight import _validate_sha as preflight_sha
from scripts.agent_os_pr_remediation.models import EvidenceValidationError

LOWER = "a" * 40
UPPER = "A" * 40
MIXED = "aA" * 20
INVALID_VALUES = (UPPER, MIXED, "a" * 39, "a" * 41, "g" * 40, "", None, 123, b"a" * 40)


@pytest.mark.parametrize(
    ("validator", "error_type"),
    [
        (recovery_sha40, EvidenceValidationError),
        (coordination_sha40, EvidenceValidationError),
        (refresh_sha40, ValueError),
        (aggregate_sha, EvidenceValidationError),
        (normalization_sha, EvidenceValidationError),
        (preflight_sha, EvidenceValidationError),
    ],
)
def test_reconciled_sha_validators_preserve_lowercase_and_reject_noncanonical_inputs(validator, error_type):
    assert validator(LOWER, "sha") == LOWER
    for value in INVALID_VALUES:
        with pytest.raises(error_type):
            validator(value, "sha")


@pytest.mark.parametrize(
    ("validator", "error_type", "message"),
    [
        (recovery_sha40, EvidenceValidationError, "sha must be a 40-character hexadecimal SHA"),
        (coordination_sha40, EvidenceValidationError, "sha must be a 40-character hexadecimal SHA"),
        (refresh_sha40, ValueError, "sha must be a lowercase 40-character SHA"),
        (aggregate_sha, EvidenceValidationError, "sha must be a 40-character hexadecimal SHA"),
        (normalization_sha, EvidenceValidationError, "sha must be a 40-character hexadecimal SHA"),
        (preflight_sha, EvidenceValidationError, "sha must be a 40-character hexadecimal SHA"),
    ],
)
def test_reconciled_sha_validators_preserve_pinned_failure_messages(validator, error_type, message):
    with pytest.raises(error_type, match=f"^{message}$"):
        validator(UPPER, "sha")
