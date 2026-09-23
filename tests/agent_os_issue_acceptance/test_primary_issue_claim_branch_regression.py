import pytest

from scripts.agent_os_issue_acceptance.issue_operational_state import PrimaryIssueClaim


SHA = "d" * 40


def make_claim(branch: str) -> PrimaryIssueClaim:
    return PrimaryIssueClaim(
        pull_request_number=2531,
        branch=branch,
        head_sha=SHA,
        state="draft",
    )


@pytest.mark.parametrize(
    "branch",
    (
        "agent/foo.lock/bar",
        "agent//topic",
        "agent/foo..bar",
        "agent/topic.lock",
        "agent/topic/.",
    ),
)
def test_primary_issue_claim_rejects_noncanonical_git_refs(branch: str) -> None:
    with pytest.raises(ValueError, match="branch is malformed or protected"):
        make_claim(branch)


def test_primary_issue_claim_rejects_protected_main() -> None:
    with pytest.raises(ValueError, match="branch is malformed or protected"):
        make_claim("main")


def test_primary_issue_claim_preserves_valid_deterministic_identity() -> None:
    first = make_claim("agent/2531-canonical-ref")
    second = make_claim("agent/2531-canonical-ref")

    assert first.claim_id == second.claim_id
    assert first.branch == "agent/2531-canonical-ref"
