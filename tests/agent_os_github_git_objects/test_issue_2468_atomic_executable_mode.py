from __future__ import annotations

import hashlib
import json

from scripts.agent_os_github_git_objects.atomic_commit import (
    execute_atomic_commit_from_blobs,
    prepare_atomic_commit_from_blobs,
)
from scripts.agent_os_github_git_objects.models import (
    AtomicCommitConfirmation,
    AtomicCommitRequest,
    AtomicCommitStatus,
    GitBlobSnapshot,
    GitChangedFile,
    GitCommitSnapshot,
    GitCompareSnapshot,
    GitRefSnapshot,
    GitTreeEntry,
    GitTreeSnapshot,
)

REPOSITORY = "Blummer92/agent-os"
BRANCH = "agent/2468-executable-git-tree-mode"
HEAD = "1" * 40
PARENT = "2" * 40
PARENT_TREE = "3" * 40
BLOB = "4" * 40
PATH = "scripts/example.sh"


def _derive(kind: str, *parts: object) -> str:
    """Return a deterministic Git-like object identity for the offline fixture."""
    canonical = json.dumps([kind, *parts], sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


class ExecutableModeTransport:
    """Offline transport that preserves the exact entries supplied to create_tree."""

    def __init__(self) -> None:
        self.head = HEAD
        self.trees: dict[str, tuple[GitTreeEntry, ...]] = {}
        self.commit_trees: dict[str, str] = {}

    def get_ref(self, repository: str, branch: str) -> GitRefSnapshot:
        """Return the current branch head."""
        return GitRefSnapshot(repository, branch, self.head)

    def get_commit(self, repository: str, commit_sha: str) -> GitCommitSnapshot:
        """Return the fixed parent-tree identity for this fixture."""
        return GitCommitSnapshot(commit_sha, PARENT_TREE, (PARENT,))

    def get_tree(self, repository: str, tree_sha: str, *, recursive: bool = False):
        """Return created tree entries so readback can verify their modes."""
        return GitTreeSnapshot(tree_sha, self.trees.get(tree_sha, ()), False)

    def get_blob(self, repository: str, blob_sha: str) -> GitBlobSnapshot:
        """Return the one allowed blob snapshot."""
        return GitBlobSnapshot(blob_sha, 1, "none")

    def create_tree(self, repository: str, *, base_tree_sha: str, entries):
        """Create a deterministic tree while retaining exact entry modes."""
        shape = tuple((entry.path, entry.mode, entry.type, entry.sha) for entry in entries)
        tree_sha = _derive("tree", base_tree_sha, shape)
        self.trees[tree_sha] = tuple(entries)
        return tree_sha

    def create_commit(self, repository: str, *, tree_sha: str, parent_sha: str, message: str):
        """Create a deterministic commit pointing at the created tree."""
        commit_sha = _derive("commit", tree_sha, parent_sha, message)
        self.commit_trees[commit_sha] = tree_sha
        return commit_sha

    def compare(self, repository: str, *, base_sha: str, head_sha: str) -> GitCompareSnapshot:
        """Project the created tree into the bounded changed-file evidence."""
        entries = self.trees[self.commit_trees[head_sha]]
        return GitCompareSnapshot(
            status="ahead",
            ahead_by=1,
            behind_by=0,
            total_commits=1,
            changed_files=tuple(
                GitChangedFile(entry.path, "modified", entry.sha) for entry in entries
            ),
            additions=1,
            deletions=0,
        )

    def update_ref(self, repository: str, *, branch: str, commit_sha: str, force: bool = False):
        """Advance only the requested non-protected fixture branch without force."""
        assert force is False
        self.head = commit_sha
        return GitRefSnapshot(repository, branch, commit_sha)


def test_atomic_publication_preserves_executable_mode() -> None:
    """A 100755 entry must remain executable through tree creation and readback."""
    transport = ExecutableModeTransport()
    request = AtomicCommitRequest(
        repository=REPOSITORY,
        branch=BRANCH,
        expected_head_sha=HEAD,
        allowed_paths=(PATH,),
        entries=(GitTreeEntry(PATH, "100755", "blob", BLOB),),
        message="test executable mode",
        invocation_id="issue-2468",
    )

    plan, planned = prepare_atomic_commit_from_blobs(request, transport)
    assert plan is not None
    confirmation = AtomicCommitConfirmation(
        invocation_id=request.invocation_id,
        operation_fingerprint=plan.operation_fingerprint,
        repository=request.repository,
        branch=request.branch,
        expected_head_sha=request.expected_head_sha,
        confirmed=True,
    )
    result = execute_atomic_commit_from_blobs(plan, confirmation, transport)

    assert planned.status is AtomicCommitStatus.PLANNED
    assert result.status is AtomicCommitStatus.REF_UPDATED
    assert result.created_tree_sha is not None
    assert transport.trees[result.created_tree_sha] == (
        GitTreeEntry(PATH, "100755", "blob", BLOB),
    )
