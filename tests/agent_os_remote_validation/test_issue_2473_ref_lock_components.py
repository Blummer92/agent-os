from __future__ import annotations

import pytest

from scripts.agent_os_remote_validation.models import PrePrValidationSubject


SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST = "c" * 64


def _subject(branch: str) -> PrePrValidationSubject:
    return PrePrValidationSubject(
        invocation_id="issue-2473",
        base_sha=SHA_A,
        branch=branch,
        expected_source_sha=SHA_B,
        tested_sha=SHA_B,
        allowed_files=("scripts/agent_os_remote_validation/models.py",),
        forbidden_paths=(".github/workflows",),
        required_command_identities=("python -m pytest tests/agent_os_remote_validation",),
        approval_id="approval-2473",
        approval_revision=1,
        projection_id="projection-2473",
        implementation_contract_fingerprint=DIGEST,
        candidate_bound=True,
    )


@pytest.mark.parametrize("branch", ("agent/foo.lock", "agent/foo.lock/bar"))
def test_lock_components_are_rejected(branch: str) -> None:
    with pytest.raises(ValueError, match="branch is not canonical"):
        _subject(branch)


@pytest.mark.parametrize("branch", ("agent/foo-lock/bar", "agent/lock.foo/bar", "agent/topic"))
def test_valid_non_lock_components_remain_accepted(branch: str) -> None:
    assert _subject(branch).branch == branch


def test_protected_branch_behavior_remains_unchanged() -> None:
    with pytest.raises(ValueError, match="non-protected ref"):
        _subject("main")
