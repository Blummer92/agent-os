import pytest

from scripts.agent_os_execution_checkpoint.mutation_intent import compute_mutation_intent_id


def _intent(target_ref: str) -> str:
    return compute_mutation_intent_id(
        repository="Blummer92/agent-os",
        issue_number=2529,
        execution_id="execution-2529",
        checkpoint_stage="repository-write",
        target_ref=target_ref,
        content_digest="a" * 64,
        parent_checkpoint_id=None,
    )


def test_valid_target_ref_remains_deterministic() -> None:
    assert _intent("agent/2529-ref-guard") == _intent("agent/2529-ref-guard")


@pytest.mark.parametrize(
    "target_ref",
    ("agent/foo.lock/bar", "agent//topic", "agent/../topic", "agent/topic.lock"),
)
def test_git_invalid_target_refs_fail_closed(target_ref: str) -> None:
    with pytest.raises(ValueError, match="target_ref is malformed"):
        _intent(target_ref)
