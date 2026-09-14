"""Pure-local bridge from a verified implementation handoff to the Git-object writer."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import AtomicCommitRequest, GitTreeEntry, require_branch, require_path, require_repository, require_sha40

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class VerifiedHandoffEntry:
    path: str
    blob_sha: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", require_path(self.path))
        object.__setattr__(self, "blob_sha", require_sha40(self.blob_sha, "blob_sha"))


@dataclass(frozen=True, slots=True)
class VerifiedImplementationHandoff:
    repository: str
    branch: str
    expected_parent_sha: str
    artifact_sha256: str
    entries: tuple[VerifiedHandoffEntry, ...]
    commit_message: str
    invocation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", require_repository(self.repository))
        object.__setattr__(self, "branch", require_branch(self.branch))
        object.__setattr__(self, "expected_parent_sha", require_sha40(self.expected_parent_sha, "expected_parent_sha"))
        if not isinstance(self.artifact_sha256, str) or not _SHA256_RE.fullmatch(self.artifact_sha256):
            raise ValueError("artifact_sha256 must be lowercase SHA-256 hex")
        if not isinstance(self.entries, tuple) or not self.entries:
            raise ValueError("entries must be a non-empty tuple")
        paths = tuple(entry.path for entry in self.entries)
        if len(paths) != len(set(paths)):
            raise ValueError("entries contain duplicate paths")
        if not isinstance(self.commit_message, str) or not self.commit_message.strip():
            raise ValueError("commit_message must be non-empty text")
        if not isinstance(self.invocation_id, str) or not self.invocation_id.strip():
            raise ValueError("invocation_id must be non-empty text")


def atomic_request_from_verified_handoff(handoff: VerifiedImplementationHandoff) -> AtomicCommitRequest:
    """Project verified post-image blob identities into the existing atomic writer.

    This function does not parse or trust patch text and performs no I/O. The caller
    verifies the attached artifact hash and derives the post-image blob identities;
    the existing atomic-commit executor then independently rechecks the exact branch
    head and every blob before any ref update.
    """
    if not isinstance(handoff, VerifiedImplementationHandoff):
        raise TypeError("handoff must be VerifiedImplementationHandoff")
    ordered = tuple(sorted(handoff.entries, key=lambda entry: entry.path))
    return AtomicCommitRequest(
        repository=handoff.repository,
        branch=handoff.branch,
        expected_head_sha=handoff.expected_parent_sha,
        allowed_paths=tuple(entry.path for entry in ordered),
        entries=tuple(
            GitTreeEntry(path=entry.path, mode="100644", type="blob", sha=entry.blob_sha)
            for entry in ordered
        ),
        message=handoff.commit_message,
        invocation_id=handoff.invocation_id,
    )
