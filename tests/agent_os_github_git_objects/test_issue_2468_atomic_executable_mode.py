from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock

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
)
from scripts.agent_os_github_git_objects.transport import PyGithubGitObjectTransport

REPOSITORY = "Blummer92/agent-os"
BRANCH = "agent/2468-executable-git-tree-mode"
HEAD = "1" * 40
PARENT = "2" * 40
PARENT_TREE = "3" * 40
BLOB = "4" * 40
PLAIN_BLOB = "5" * 40
PATH = "scripts/example.sh"
PLAIN_PATH = "scripts/example.txt"


def _derive(kind: str, *parts: object) -> str:
    """Return a deterministic Git-like object identity for the offline fixture."""
    canonical = json.dumps([kind, *parts], sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


class ExecutableModeTransport:
    """Offline transport whose read-back uses the real tree-response parser.

    ``get_tree`` deliberately re-serializes each created tree into a GitHub-shaped
    payload and parses it with `PyGithubGitObjectTransport`. A fixture that
    short-circuits read-back cannot observe a parser that drops or rewrites
    executable entries, which is precisely how the #2468 defect survived.
    """

    def __init__(self) -> None:
        self.head = HEAD
        self.trees: dict[str, tuple[GitTreeEntry, ...]] = {}
        self.commit_trees: dict[str, str] = {}
        self.read_back_modes: dict[str, str] = {}

    def get_ref(self, repository: str, branch: str) -> GitRefSnapshot:
        """Return the current branch head."""
        return GitRefSnapshot(repository, branch, self.head)

    def get_commit(self, repository: str, commit_sha: str) -> GitCommitSnapshot:
        """Return the fixed parent-tree identity for this fixture."""
        return GitCommitSnapshot(commit_sha, PARENT_TREE, (PARENT,))

    def get_tree(self, repository: str, tree_sha: str, *, recursive: bool = False):
        """Parse a GitHub-shaped tree response through the production parser."""
        payload = {
            "sha": tree_sha,
            "truncated": False,
            "tree": [
                {"path": entry.path, "mode": entry.mode, "type": entry.type, "sha": entry.sha}
                for entry in self.trees.get(tree_sha, ())
            ],
        }
        client = MagicMock()
        client.requester.requestJsonAndCheck.return_value = ({"Status": "200 OK"}, payload)
        snapshot = PyGithubGitObjectTransport(client).get_tree(
            repository, tree_sha, recursive=recursive
        )
        self.read_back_modes = {entry.path: entry.mode for entry in snapshot.entries}
        return snapshot

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


def _publish(transport: ExecutableModeTransport, entries: tuple[GitTreeEntry, ...]):
    """Drive the full guarded plan/confirm/execute publication path."""
    request = AtomicCommitRequest(
        repository=REPOSITORY,
        branch=BRANCH,
        expected_head_sha=HEAD,
        allowed_paths=tuple(entry.path for entry in entries),
        entries=entries,
        message="test executable mode",
        invocation_id="issue-2468",
    )
    plan, planned = prepare_atomic_commit_from_blobs(request, transport)
    assert plan is not None
    assert planned.status is AtomicCommitStatus.PLANNED
    confirmation = AtomicCommitConfirmation(
        invocation_id=request.invocation_id,
        operation_fingerprint=plan.operation_fingerprint,
        repository=request.repository,
        branch=request.branch,
        expected_head_sha=request.expected_head_sha,
        confirmed=True,
    )
    return execute_atomic_commit_from_blobs(plan, confirmation, transport)


def test_atomic_publication_preserves_executable_mode() -> None:
    """A 100755 entry must stay executable from creation through the ref update."""
    transport = ExecutableModeTransport()
    entry = GitTreeEntry(PATH, "100755", "blob", BLOB)

    result = _publish(transport, (entry,))

    assert result.status is AtomicCommitStatus.REF_UPDATED
    assert result.created_tree_sha is not None
    assert result.created_commit_sha is not None
    # The created tree kept the executable mode on write ...
    assert transport.trees[result.created_tree_sha] == (entry,)
    # ... the production parser kept it on read-back ...
    assert transport.read_back_modes == {PATH: "100755"}
    # ... and the guarded ref update actually completed against that commit.
    assert result.ending_branch_sha == result.created_commit_sha
    assert transport.head == result.created_commit_sha


def test_atomic_publication_preserves_mixed_regular_file_modes() -> None:
    """Executable support must not disturb ordinary 100644 publication."""
    transport = ExecutableModeTransport()
    entries = (
        GitTreeEntry(PATH, "100755", "blob", BLOB),
        GitTreeEntry(PLAIN_PATH, "100644", "blob", PLAIN_BLOB),
    )

    result = _publish(transport, entries)

    assert result.status is AtomicCommitStatus.REF_UPDATED
    assert result.created_tree_sha is not None
    assert transport.trees[result.created_tree_sha] == entries
    assert transport.read_back_modes == {PATH: "100755", PLAIN_PATH: "100644"}
    assert transport.head == result.created_commit_sha
