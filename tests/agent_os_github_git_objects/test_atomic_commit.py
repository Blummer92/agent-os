from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from scripts.agent_os_github_git_objects.atomic_commit import (
    execute_atomic_commit_from_blobs,
    prepare_atomic_commit_from_blobs,
)
from scripts.agent_os_github_git_objects.models import (
    AtomicCommitConfirmation,
    AtomicCommitPlan,
    AtomicCommitReason,
    AtomicCommitRequest,
    AtomicCommitStatus,
    GitBlobSnapshot,
    GitChangedFile,
    GitCommitSnapshot,
    GitCompareSnapshot,
    GitRefSnapshot,
    GitTreeEntry,
    GitTreeSnapshot,
    MutationState,
)
from scripts.agent_os_github_git_objects.transport import GitObjectTransportError

REPOSITORY = "Blummer92/agent-os"
BRANCH = "agent/917-two-phase-planning-binding"
HEAD = "69987c9ec3d09e39607cd0f8a939377ac85015ab"
PARENT = "1" * 40
PARENT_TREE = "2" * 40
CREATED_TREE = "3" * 40
CREATED_COMMIT = "4" * 40
PRODUCTION_BLOB = "6285bf2cdece4a9cabcb0573d9bce8ca5f7122ec"
TEST_BLOB = "e956bb877f440967f235827d662e44540ac30713"
WRONG_BLOB = "662085175946ddf9b15c8d91581ac3b0e6c3ad49"
PRODUCTION_PATH = "scripts/agent_os_candidate_packet/stage_models.py"
TEST_PATH = "tests/agent_os_candidate_packet/test_readiness_stage.py"


class FakeTransport:
    def __init__(self) -> None:
        self.head = HEAD
        self.calls: list[tuple] = []
        self.blobs = {PRODUCTION_BLOB, TEST_BLOB}
        self.compare_snapshot = GitCompareSnapshot(
            status="ahead",
            ahead_by=1,
            behind_by=0,
            total_commits=1,
            changed_files=(
                GitChangedFile(PRODUCTION_PATH, "modified", PRODUCTION_BLOB),
                GitChangedFile(TEST_PATH, "modified", TEST_BLOB),
            ),
            additions=120,
            deletions=4,
        )
        self.error_by_operation: dict[str, GitObjectTransportError] = {}
        self.move_before_final_guard = False
        self.post_update_override: str | None = None
        self.ref_reads = 0

    def _maybe_error(self, operation: str) -> None:
        error = self.error_by_operation.get(operation)
        if error is not None:
            raise error

    def get_ref(self, repository: str, branch: str) -> GitRefSnapshot:
        self._maybe_error("get-ref")
        self.ref_reads += 1
        if self.move_before_final_guard and self.ref_reads == 3:
            self.head = "5" * 40
        if self.post_update_override is not None and self.ref_reads >= 4:
            self.head = self.post_update_override
        self.calls.append(("get_ref", repository, branch, self.head))
        return GitRefSnapshot(repository, branch, self.head)

    def get_commit(self, repository: str, commit_sha: str) -> GitCommitSnapshot:
        self._maybe_error("get-commit")
        self.calls.append(("get_commit", repository, commit_sha))
        return GitCommitSnapshot(commit_sha, PARENT_TREE, (PARENT,))

    def get_tree(self, repository: str, tree_sha: str, *, recursive: bool = False):
        self._maybe_error("get-tree")
        self.calls.append(("get_tree", repository, tree_sha, recursive))
        return GitTreeSnapshot(
            tree_sha,
            (
                GitTreeEntry(PRODUCTION_PATH, "100644", "blob", PRODUCTION_BLOB),
                GitTreeEntry(TEST_PATH, "100644", "blob", TEST_BLOB),
            ),
            False,
        )

    def get_blob(self, repository: str, blob_sha: str) -> GitBlobSnapshot:
        self._maybe_error("get-blob")
        self.calls.append(("get_blob", repository, blob_sha))
        if blob_sha not in self.blobs:
            raise GitObjectTransportError("get-blob", "not-found")
        return GitBlobSnapshot(blob_sha, 1, "none")

    def create_tree(self, repository: str, *, base_tree_sha: str, entries):
        self._maybe_error("create-tree")
        self.calls.append(("create_tree", repository, base_tree_sha, entries))
        return CREATED_TREE

    def create_commit(self, repository: str, *, tree_sha: str, parent_sha: str, message: str):
        self._maybe_error("create-commit")
        self.calls.append(("create_commit", repository, tree_sha, parent_sha, message))
        return CREATED_COMMIT

    def compare(self, repository: str, *, base_sha: str, head_sha: str) -> GitCompareSnapshot:
        self._maybe_error("compare")
        self.calls.append(("compare", repository, base_sha, head_sha))
        return self.compare_snapshot

    def update_ref(self, repository: str, *, branch: str, commit_sha: str, force: bool = False):
        self._maybe_error("update-ref")
        assert force is False
        self.calls.append(("update_ref", repository, branch, commit_sha, force))
        self.head = commit_sha
        return GitRefSnapshot(repository, branch, commit_sha)


def _derive(kind: str, *parts: object) -> str:
    """Content-addressed stand-in for real Git object hashing (40 lowercase hex)."""
    canonical = json.dumps([kind, *parts], sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


class DeterministicTransport:
    """Offline transport deriving tree/commit identities from content alone.

    Unlike ``FakeTransport`` it returns canned SHAs for nothing: the derived
    tree SHA is a pure function of the exact base tree and the ordered entries
    it is asked to create, so equivalent semantic inputs are provably
    equivalent tree operations rather than merely equal fingerprints.
    """

    def __init__(self) -> None:
        self.refs = {BRANCH: HEAD}
        self.tree_requests: list[tuple[str, tuple[tuple[str, str, str, str], ...]]] = []
        self.ref_updates: list[tuple[str, str]] = []
        self.trees: dict[str, tuple[GitTreeEntry, ...]] = {}
        self.commit_trees: dict[str, str] = {}

    def get_ref(self, repository: str, branch: str) -> GitRefSnapshot:
        return GitRefSnapshot(repository, branch, self.refs[branch])

    def get_commit(self, repository: str, commit_sha: str) -> GitCommitSnapshot:
        return GitCommitSnapshot(commit_sha, PARENT_TREE, (PARENT,))

    def get_tree(self, repository: str, tree_sha: str, *, recursive: bool = False):
        return GitTreeSnapshot(tree_sha, self.trees.get(tree_sha, ()), False)

    def get_blob(self, repository: str, blob_sha: str) -> GitBlobSnapshot:
        return GitBlobSnapshot(blob_sha, 1, "none")

    def create_tree(self, repository: str, *, base_tree_sha: str, entries):
        shape = tuple(
            (entry.path, entry.mode, entry.type, entry.sha) for entry in entries
        )
        self.tree_requests.append((base_tree_sha, shape))
        derived = _derive("tree", base_tree_sha, shape)
        self.trees[derived] = tuple(entries)
        return derived

    def create_commit(self, repository: str, *, tree_sha: str, parent_sha: str, message: str):
        derived = _derive("commit", tree_sha, parent_sha, message)
        self.commit_trees[derived] = tree_sha
        return derived

    def compare(self, repository: str, *, base_sha: str, head_sha: str) -> GitCompareSnapshot:
        entries = self.trees[self.commit_trees[head_sha]]
        return GitCompareSnapshot(
            status="ahead",
            ahead_by=1,
            behind_by=0,
            total_commits=1,
            changed_files=tuple(
                GitChangedFile(entry.path, "modified", entry.sha) for entry in entries
            ),
            additions=len(entries),
            deletions=0,
        )

    def update_ref(self, repository: str, *, branch: str, commit_sha: str, force: bool = False):
        assert force is False
        self.ref_updates.append((branch, commit_sha))
        self.refs[branch] = commit_sha
        return GitRefSnapshot(repository, branch, commit_sha)


def request(**overrides) -> AtomicCommitRequest:
    values = dict(
        repository=REPOSITORY,
        branch=BRANCH,
        expected_head_sha=HEAD,
        allowed_paths=(PRODUCTION_PATH, TEST_PATH),
        entries=(
            GitTreeEntry(PRODUCTION_PATH, "100644", "blob", PRODUCTION_BLOB),
            GitTreeEntry(TEST_PATH, "100644", "blob", TEST_BLOB),
        ),
        message="[Standards] Add explicit issue planning context",
        invocation_id="issue-917-publication",
    )
    values.update(overrides)
    return AtomicCommitRequest(**values)


def confirmation(plan, **overrides) -> AtomicCommitConfirmation:
    values = dict(
        invocation_id=plan.request.invocation_id,
        operation_fingerprint=plan.operation_fingerprint,
        repository=plan.request.repository,
        branch=plan.request.branch,
        expected_head_sha=plan.request.expected_head_sha,
        confirmed=True,
    )
    values.update(overrides)
    return AtomicCommitConfirmation(**values)


def prepared(transport: FakeTransport | None = None):
    transport = transport or FakeTransport()
    plan, result = prepare_atomic_commit_from_blobs(request(), transport)
    assert plan is not None
    assert result.reason is AtomicCommitReason.PLAN_READY
    return transport, plan


def test_917_fixture_uses_exact_parent_tree_blobs_and_non_force_ref_update() -> None:
    transport, plan = prepared()
    result = execute_atomic_commit_from_blobs(plan, confirmation(plan), transport)

    assert result.status is AtomicCommitStatus.REF_UPDATED
    assert result.reason is AtomicCommitReason.REF_UPDATED
    assert result.starting_branch_sha == HEAD
    assert result.ending_branch_sha == CREATED_COMMIT
    assert result.parent_tree_sha == PARENT_TREE
    assert result.created_tree_sha == CREATED_TREE
    assert result.created_commit_sha == CREATED_COMMIT
    assert result.changed_paths == tuple(sorted((PRODUCTION_PATH, TEST_PATH)))
    assert result.additions == 120
    assert result.deletions == 4
    assert result.force_used is False
    assert result.merge_authorized is False
    assert result.issue_mutation_authorized is False
    assert result.workflow_mutation_authorized is False

    blob_calls = [call[2] for call in transport.calls if call[0] == "get_blob"]
    # Verified once while planning and independently again before any write.
    assert blob_calls == [PRODUCTION_BLOB, TEST_BLOB, PRODUCTION_BLOB, TEST_BLOB]
    assert WRONG_BLOB not in blob_calls
    tree_calls = [call for call in transport.calls if call[0] == "create_tree"]
    commit_calls = [call for call in transport.calls if call[0] == "create_commit"]
    assert len(tree_calls) == 1
    assert tree_calls[0][2] == PARENT_TREE
    assert tuple(entry.sha for entry in tree_calls[0][3]) == (PRODUCTION_BLOB, TEST_BLOB)
    assert len(commit_calls) == 1
    assert commit_calls[0][2:] == (
        CREATED_TREE,
        HEAD,
        "[Standards] Add explicit issue planning context",
    )
    compare_index = next(i for i, call in enumerate(transport.calls) if call[0] == "compare")
    update_index = next(i for i, call in enumerate(transport.calls) if call[0] == "update_ref")
    assert compare_index < update_index
    assert transport.calls[update_index][-1] is False


def test_equivalent_inputs_derive_identical_tree_operations() -> None:
    ordered = (
        GitTreeEntry(PRODUCTION_PATH, "100644", "blob", PRODUCTION_BLOB),
        GitTreeEntry(TEST_PATH, "100644", "blob", TEST_BLOB),
    )
    runs = []
    for entries, allowed_paths in (
        (ordered, (PRODUCTION_PATH, TEST_PATH)),
        (tuple(reversed(ordered)), (TEST_PATH, PRODUCTION_PATH)),
    ):
        transport = DeterministicTransport()
        plan, planned = prepare_atomic_commit_from_blobs(
            request(entries=entries, allowed_paths=allowed_paths), transport
        )
        assert plan is not None
        assert planned.reason is AtomicCommitReason.PLAN_READY
        result = execute_atomic_commit_from_blobs(plan, confirmation(plan), transport)
        assert result.status is AtomicCommitStatus.REF_UPDATED
        runs.append((transport, plan, result))

    (first, first_plan, first_result), (second, second_plan, second_result) = runs

    # Exact base tree and identical ordered tree entries were submitted.
    assert first.tree_requests == second.tree_requests
    assert len(first.tree_requests) == 1
    assert first.tree_requests[0][0] == PARENT_TREE == first_plan.parent_tree_sha
    assert first.tree_requests[0][1] == (
        (PRODUCTION_PATH, "100644", "blob", PRODUCTION_BLOB),
        (TEST_PATH, "100644", "blob", TEST_BLOB),
    )

    # Identical derived tree, commit, and fingerprint.
    assert first_result.created_tree_sha == second_result.created_tree_sha
    assert first_result.created_commit_sha == second_result.created_commit_sha
    assert first_plan.operation_fingerprint == second_plan.operation_fingerprint
    assert first.trees[first_result.created_tree_sha] == second.trees[
        second_result.created_tree_sha
    ]

    # Exactly one ref movement, on the requested branch, to the derived commit.
    assert first.ref_updates == second.ref_updates
    assert first.ref_updates == [(BRANCH, first_result.created_commit_sha)]
    assert first.refs == {BRANCH: first_result.created_commit_sha}


def test_prepared_plan_success_path_still_updates_ref() -> None:
    transport, plan = prepared()
    result = execute_atomic_commit_from_blobs(plan, confirmation(plan), transport)
    assert result.status is AtomicCommitStatus.REF_UPDATED
    assert result.mutation_state is MutationState.CONFIRMED
    assert result.parent_tree_sha == PARENT_TREE
    assert result.unattached_objects == ()


def test_plan_with_unrelated_parent_tree_performs_zero_writes() -> None:
    transport, plan = prepared()
    forged = AtomicCommitPlan(plan.request, "a" * 40, plan.operation_fingerprint)
    result = execute_atomic_commit_from_blobs(forged, confirmation(forged), transport)
    assert result.reason is AtomicCommitReason.PLAN_PROVENANCE_MISMATCH
    assert result.status is AtomicCommitStatus.BLOCKED
    assert result.mutation_state is MutationState.NOT_ATTEMPTED
    assert result.unattached_objects == ()
    assert not any(
        call[0].startswith("create_") or call[0] == "update_ref" for call in transport.calls
    )


def test_plan_with_forged_fingerprint_performs_zero_writes() -> None:
    transport, plan = prepared()
    forged = AtomicCommitPlan(plan.request, plan.parent_tree_sha, "b" * 64)
    result = execute_atomic_commit_from_blobs(forged, confirmation(forged), transport)
    assert result.reason is AtomicCommitReason.PLAN_PROVENANCE_MISMATCH
    assert result.mutation_state is MutationState.NOT_ATTEMPTED
    assert not any(
        call[0].startswith("create_") or call[0] == "update_ref" for call in transport.calls
    )


def test_plan_whose_blob_evidence_no_longer_verifies_performs_zero_writes() -> None:
    transport, plan = prepared()
    transport.blobs.remove(TEST_BLOB)
    result = execute_atomic_commit_from_blobs(plan, confirmation(plan), transport)
    assert result.reason is AtomicCommitReason.BLOB_MISSING_OR_MISMATCHED
    assert result.mutation_state is MutationState.NOT_ATTEMPTED
    assert not any(
        call[0].startswith("create_") or call[0] == "update_ref" for call in transport.calls
    )


def test_plan_bound_to_moved_head_performs_zero_writes() -> None:
    transport, plan = prepared()
    transport.head = "6" * 40
    result = execute_atomic_commit_from_blobs(plan, confirmation(plan), transport)
    assert result.reason is AtomicCommitReason.CONCURRENCY_STOP
    assert not any(
        call[0].startswith("create_") or call[0] == "update_ref" for call in transport.calls
    )


def test_request_and_result_are_immutable() -> None:
    item = request()
    with pytest.raises(FrozenInstanceError):
        item.branch = "other"
    transport, plan = prepared()
    result = execute_atomic_commit_from_blobs(plan, confirmation(plan), transport)
    with pytest.raises(FrozenInstanceError):
        result.merge_authorized = True


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"repository": "owner"}, "repository"),
        ({"branch": "main"}, "protected"),
        ({"branch": "bad..branch"}, "branch"),
        ({"expected_head_sha": "A" * 40}, "SHA"),
        ({"entries": ()}, "entries"),
        ({"allowed_paths": (PRODUCTION_PATH,)}, "exactly match"),
        ({"message": ""}, "message"),
        ({"invocation_id": "bad\nvalue"}, "invocation_id"),
    ],
)
def test_invalid_requests_fail_before_transport(overrides, message) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        request(**overrides)


@pytest.mark.parametrize(
    "entry",
    [
        ("../escape.py", "100644", "blob", PRODUCTION_BLOB),
        ("/absolute.py", "100644", "blob", PRODUCTION_BLOB),
        ("bad\npath.py", "100644", "blob", PRODUCTION_BLOB),
        (PRODUCTION_PATH, "100755", "blob", PRODUCTION_BLOB),
        (PRODUCTION_PATH, "100644", "tree", PRODUCTION_BLOB),
        (PRODUCTION_PATH, "100644", "blob", "f" * 39),
    ],
)
def test_invalid_tree_entries_are_rejected(entry) -> None:
    with pytest.raises((TypeError, ValueError)):
        GitTreeEntry(*entry)


def test_duplicate_paths_are_rejected() -> None:
    duplicate = GitTreeEntry(PRODUCTION_PATH, "100644", "blob", PRODUCTION_BLOB)
    with pytest.raises(ValueError, match="duplicate"):
        request(
            allowed_paths=(PRODUCTION_PATH, PRODUCTION_PATH),
            entries=(duplicate, duplicate),
        )


def test_initial_head_mismatch_performs_zero_writes() -> None:
    transport = FakeTransport()
    transport.head = "6" * 40
    plan, result = prepare_atomic_commit_from_blobs(request(), transport)
    assert plan is None
    assert result.reason is AtomicCommitReason.INITIAL_HEAD_MISMATCH
    assert not any(call[0].startswith("create_") or call[0] == "update_ref" for call in transport.calls)


def test_missing_blob_fails_closed() -> None:
    transport = FakeTransport()
    transport.blobs.remove(TEST_BLOB)
    plan, result = prepare_atomic_commit_from_blobs(request(), transport)
    assert plan is None
    assert result.reason is AtomicCommitReason.BLOB_MISSING_OR_MISMATCHED
    assert result.execution_attempted is False


@pytest.mark.parametrize(
    ("confirmation_value", "reason"),
    [
        (None, AtomicCommitReason.CONFIRMATION_MISSING),
        ("cancelled", AtomicCommitReason.CONFIRMATION_CANCELLED),
        ("mismatched", AtomicCommitReason.CONFIRMATION_MISMATCHED),
    ],
)
def test_confirmation_failures_perform_zero_writes(confirmation_value, reason) -> None:
    transport, plan = prepared()
    if confirmation_value is None:
        supplied = None
    elif confirmation_value == "cancelled":
        supplied = confirmation(plan, confirmed=False)
    else:
        supplied = confirmation(plan, operation_fingerprint="a" * 64)
    result = execute_atomic_commit_from_blobs(plan, supplied, transport)
    assert result.reason is reason
    assert not any(call[0].startswith("create_") or call[0] == "update_ref" for call in transport.calls)


def test_repeat_fingerprint_is_rejected_during_planning() -> None:
    transport, plan = prepared()
    second_request = request(prior_fingerprints=(plan.operation_fingerprint,))
    second_plan, result = prepare_atomic_commit_from_blobs(second_request, FakeTransport())
    assert second_plan is None
    assert result.reason is AtomicCommitReason.REPEAT_INVOCATION


def test_unexpected_third_path_leaves_tree_and_commit_unattached() -> None:
    transport, plan = prepared()
    transport.compare_snapshot = GitCompareSnapshot(
        status="ahead",
        ahead_by=1,
        behind_by=0,
        total_commits=1,
        changed_files=transport.compare_snapshot.changed_files
        + (GitChangedFile("unexpected.py", "modified", "7" * 40),),
        additions=121,
        deletions=4,
    )
    result = execute_atomic_commit_from_blobs(plan, confirmation(plan), transport)
    assert result.reason is AtomicCommitReason.UNATTACHED_VALIDATION_STOP
    assert result.unattached_objects == (CREATED_TREE, CREATED_COMMIT)
    assert not any(call[0] == "update_ref" for call in transport.calls)


@pytest.mark.parametrize(
    "snapshot",
    [
        GitCompareSnapshot("behind", 0, 1, 0, (), 0, 0),
        GitCompareSnapshot("ahead", 2, 0, 2, (), 0, 0),
        GitCompareSnapshot(
            "ahead",
            1,
            0,
            1,
            (GitChangedFile(PRODUCTION_PATH, "renamed", PRODUCTION_BLOB, "old.py"),),
            1,
            0,
        ),
        GitCompareSnapshot(
            "ahead",
            1,
            0,
            1,
            (
                GitChangedFile(PRODUCTION_PATH, "modified", "8" * 40),
                GitChangedFile(TEST_PATH, "modified", TEST_BLOB),
            ),
            1,
            0,
        ),
    ],
)
def test_invalid_compare_shapes_block_ref_update(snapshot) -> None:
    transport, plan = prepared()
    transport.compare_snapshot = snapshot
    result = execute_atomic_commit_from_blobs(plan, confirmation(plan), transport)
    assert result.reason is AtomicCommitReason.UNATTACHED_VALIDATION_STOP
    assert not any(call[0] == "update_ref" for call in transport.calls)


def test_created_tree_blob_mismatch_blocks_ref_update() -> None:
    transport, plan = prepared()

    def bad_tree(repository: str, tree_sha: str, *, recursive: bool = False):
        transport.calls.append(("get_tree", repository, tree_sha, recursive))
        return GitTreeSnapshot(
            tree_sha,
            (
                GitTreeEntry(PRODUCTION_PATH, "100644", "blob", "8" * 40),
                GitTreeEntry(TEST_PATH, "100644", "blob", TEST_BLOB),
            ),
            False,
        )

    transport.get_tree = bad_tree
    result = execute_atomic_commit_from_blobs(plan, confirmation(plan), transport)
    assert result.reason is AtomicCommitReason.UNATTACHED_VALIDATION_STOP
    assert result.unattached_objects == (CREATED_TREE, CREATED_COMMIT)
    assert not any(call[0] == "update_ref" for call in transport.calls)


def test_branch_movement_before_ref_update_reports_unattached_objects() -> None:
    transport, plan = prepared()
    transport.move_before_final_guard = True
    result = execute_atomic_commit_from_blobs(plan, confirmation(plan), transport)
    assert result.reason is AtomicCommitReason.CONCURRENCY_STOP
    assert result.unattached_objects == (CREATED_TREE, CREATED_COMMIT)
    assert not any(call[0] == "update_ref" for call in transport.calls)


@pytest.mark.parametrize(
    ("operation", "state", "reason"),
    [
        ("create-tree", MutationState.FAILED_BEFORE_SIDE_EFFECT, AtomicCommitReason.TREE_CREATE_FAILED),
        ("create-tree", MutationState.UNCERTAIN, AtomicCommitReason.TREE_CREATE_UNCERTAIN),
        ("create-commit", MutationState.FAILED_BEFORE_SIDE_EFFECT, AtomicCommitReason.COMMIT_CREATE_FAILED),
        ("create-commit", MutationState.UNCERTAIN, AtomicCommitReason.COMMIT_CREATE_UNCERTAIN),
        ("update-ref", MutationState.FAILED_BEFORE_SIDE_EFFECT, AtomicCommitReason.REF_UPDATE_FAILED),
        ("update-ref", MutationState.UNCERTAIN, AtomicCommitReason.REF_UPDATE_UNCERTAIN),
    ],
)
def test_write_failure_and_uncertainty_are_distinguished(operation, state, reason) -> None:
    transport, plan = prepared()
    transport.error_by_operation[operation] = GitObjectTransportError(
        operation, "simulated", mutation_state=state
    )
    result = execute_atomic_commit_from_blobs(plan, confirmation(plan), transport)
    assert result.reason is reason
    assert result.mutation_state is state
    assert result.retry_allowed is False


def test_post_update_mismatch_is_uncertain() -> None:
    transport, plan = prepared()
    transport.post_update_override = "9" * 40
    result = execute_atomic_commit_from_blobs(plan, confirmation(plan), transport)
    assert result.reason is AtomicCommitReason.POST_UPDATE_MISMATCH
    assert result.status is AtomicCommitStatus.UNCERTAIN
    assert result.mutation_state is MutationState.UNCERTAIN
    assert len(result.unattached_objects) == 2


def test_transport_interface_has_no_unrelated_mutation_surface() -> None:
    from scripts.agent_os_github_git_objects.transport import GitHubGitObjectTransport

    public = {name for name in dir(GitHubGitObjectTransport) if not name.startswith("_")}
    assert public == {
        "compare",
        "create_commit",
        "create_tree",
        "get_blob",
        "get_commit",
        "get_ref",
        "get_tree",
        "update_ref",
    }
    assert not public & {
        "merge",
        "create_issue",
        "update_issue",
        "create_pull_request",
        "dispatch_workflow",
        "update_settings",
        "request",
        "graphql",
    }
