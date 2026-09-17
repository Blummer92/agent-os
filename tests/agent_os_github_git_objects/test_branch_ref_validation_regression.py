import pytest

from scripts.agent_os_github_git_objects.models import require_branch


@pytest.mark.parametrize(
    "branch",
    (
        "agent/foo.lock/bar",
        "agent/topic.lock/nested",
    ),
)
def test_require_branch_rejects_internal_lock_components(branch: str) -> None:
    with pytest.raises(ValueError, match="branch is malformed"):
        require_branch(branch)


def test_require_branch_still_rejects_terminal_lock_component() -> None:
    with pytest.raises(ValueError, match="branch is malformed"):
        require_branch("agent/topic.lock")


@pytest.mark.parametrize("branch", ("agent/topic", "agent/foo.locked/bar", "feature/a-b_c.1"))
def test_require_branch_preserves_valid_branches(branch: str) -> None:
    assert require_branch(branch) == branch


def test_require_branch_preserves_protected_branch_behavior() -> None:
    with pytest.raises(ValueError, match="protected branches are not supported"):
        require_branch("main")
    assert require_branch("main", allow_protected=True) == "main"
