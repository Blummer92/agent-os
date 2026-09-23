from dataclasses import replace

from scripts.agent_os_github_git_objects.models import (
    AtomicCommitReason,
    AtomicCommitResult,
    AtomicCommitStatus,
    MutationState,
)
from scripts.agent_os_github_git_objects.publication_recovery import (
    ContentsFailureEvidence,
    RecoveryStatus,
    admit_atomic_recovery,
    admit_pr_creation_after_recovery,
)


HEAD = "a" * 40
NEW = "b" * 40
PATHS = ("alpha.txt", "nested/beta.txt")


def failure(state: MutationState = MutationState.FAILED_BEFORE_SIDE_EFFECT) -> ContentsFailureEvidence:
    return ContentsFailureEvidence(
        repository="Blummer92/agent-os",
        branch="agent/2460-publication-recovery",
        expected_head_sha=HEAD,
        paths=PATHS,
        mutation_state=state,
        error_class="contents-update-failed",
    )


def successful_result() -> AtomicCommitResult:
    return AtomicCommitResult(
        status=AtomicCommitStatus.REF_UPDATED,
        reason=AtomicCommitReason.REF_UPDATED,
        operation_fingerprint="c" * 64,
        starting_branch_sha=HEAD,
        ending_branch_sha=NEW,
        parent_tree_sha="d" * 40,
        created_tree_sha="e" * 40,
        created_commit_sha=NEW,
        changed_paths=PATHS,
        mutation_state=MutationState.CONFIRMED,
        execution_attempted=True,
        ref_update_attempted=True,
    )


def test_proven_pre_side_effect_failure_can_use_existing_atomic_writer() -> None:
    decision = admit_atomic_recovery(failure(), observed_branch_sha=HEAD, replacement_paths=PATHS)
    assert decision.status is RecoveryStatus.ADMITTED
    assert decision.use_atomic_git_objects is True
    assert decision.pr_creation_allowed is False


def test_uncertain_contents_failure_requires_readback_not_blind_fallback() -> None:
    decision = admit_atomic_recovery(
        failure(MutationState.UNCERTAIN), observed_branch_sha=HEAD, replacement_paths=PATHS
    )
    assert decision.status is RecoveryStatus.UNCERTAIN
    assert decision.use_atomic_git_objects is False
    assert decision.pr_creation_allowed is False


def test_moved_head_or_changed_path_set_blocks_fallback() -> None:
    moved = admit_atomic_recovery(failure(), observed_branch_sha="f" * 40, replacement_paths=PATHS)
    changed = admit_atomic_recovery(failure(), observed_branch_sha=HEAD, replacement_paths=("alpha.txt",))
    assert moved.status is RecoveryStatus.BLOCKED
    assert changed.status is RecoveryStatus.BLOCKED


def test_pr_creation_requires_confirmed_branch_advance_and_exact_paths() -> None:
    decision = admit_pr_creation_after_recovery(failure(), successful_result())
    assert decision.status is RecoveryStatus.ADMITTED
    assert decision.pr_creation_allowed is True


def test_pr_creation_fails_closed_on_unconfirmed_or_mismatched_publication() -> None:
    unconfirmed = replace(successful_result(), mutation_state=MutationState.UNCERTAIN)
    wrong_paths = replace(successful_result(), changed_paths=("alpha.txt",))
    unchanged = replace(successful_result(), ending_branch_sha=HEAD)
    for result in (unconfirmed, wrong_paths, unchanged):
        decision = admit_pr_creation_after_recovery(failure(), result)
        assert decision.pr_creation_allowed is False
        assert decision.status in {RecoveryStatus.BLOCKED, RecoveryStatus.UNCERTAIN}
