"""Regression matrix for #2274 fail-safe SHA validator reconciliation."""

import pytest

from scripts.agent_os_issue_labels.pr_branch_refresh_actions_runner import _sha40 as refresh_sha40
from scripts.agent_os_pr_remediation.ci_evidence_recovery import _sha40 as recovery_sha40
from scripts.agent_os_pr_remediation.coordination import _sha40 as coordination_sha40
from scripts.agent_os_pr_remediation.models import EvidenceValidationError

LOWER = "a" * 40
UPPER = "A" * 40
MIXED = "aA" * 20


@pytest.mark.parametrize(
    ("validator", "error_type"),
    [
        (recovery_sha40, EvidenceValidationError),
        (coordination_sha40, EvidenceValidationError),
        (refresh_sha40, ValueError),
    ],
)
def test_reconciled_sha_validators_preserve_lowercase_and_reject_noncanonical_inputs(validator, error_type):
    assert validator(LOWER, "sha") == LOWER

    invalid_values = (
        UPPER,
        MIXED,
        "a" * 39,
        "a" * 41,
        "g" * 40,
        "",
        None,
        123,
        b"a" * 40,
    )
    for value in invalid_values:
        with pytest.raises(error_type):
            validator(value, "sha")
