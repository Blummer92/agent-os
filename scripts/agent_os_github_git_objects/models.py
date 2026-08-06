"""Typed, immutable models for guarded Git database operations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Literal

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_ALLOWED_COMPARE_STATUSES = frozenset({"added", "modified"})


def require_sha40(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SHA40_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase 40-character hexadecimal SHA")
    return value


def require_repository(value: object) -> str:
    if not isinstance(value, str) or value != value.strip() or not _REPOSITORY_RE.fullmatch(value):
        raise ValueError("repository must be a trimmed owner/repository string")
    owner, repository = value.split("/", 1)
    if owner in {".", ".."} or repository in {".", ".."} or _CONTROL_RE.search(value):
        raise ValueError("repository is malformed")
    return value


def require_branch(value: object, *, allow_protected: bool = False) -> str:
    if not isinstance(value, str) or value != value.strip() or not _BRANCH_RE.fullmatch(value):
        raise ValueError("branch is malformed")
    if (
        value.startswith(("refs/", "/", "."))
        or value.endswith(("/", ".", ".lock"))
        or "//" in value
        or ".." in value
        or "@{" in value
        or any(character in value for character in " ~^:?*[\\")
        or _CONTROL_RE.search(value)
    ):
        raise ValueError("branch is malformed")
    if not allow_protected and value in {"main", "master"}:
        raise ValueError("protected branches are not supported")
    return value


def require_path(value: object) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise ValueError("path must be a non-empty trimmed string")
    if value.startswith("/") or "\\" in value or _CONTROL_RE.search(value):
        raise ValueError("path is malformed")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("path traversal is not allowed")
    normalized = str(path)
    if normalized != value:
        raise ValueError("path must be canonical POSIX text")
    return value


@dataclass(frozen=True, slots=True)
class GitRefSnapshot:
    repository: str
    branch: str
    commit_sha: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", require_repository(self.repository))
        object.__setattr__(self, "branch", require_branch(self.branch, allow_protected=True))
        object.__setattr__(self, "commit_sha", require_sha40(self.commit_sha, "commit_sha"))


@dataclass(frozen=True, slots=True)
class GitCommitSnapshot:
    sha: str
    tree_sha: str
    parent_shas: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha", require_sha40(self.sha, "sha"))
        object.__setattr__(self, "tree_sha", require_sha40(self.tree_sha, "tree_sha"))
        if not isinstance(self.parent_shas, tuple):
            raise TypeError("parent_shas must be a tuple")
        object.__setattr__(
            self,
            "parent_shas",
            tuple(require_sha40(value, "parent_sha") for value in self.parent_shas),
        )


@dataclass(frozen=True, slots=True)
class GitTreeEntry:
    path: str
    mode: Literal["100644"]
    type: Literal["blob"]
    sha: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", require_path(self.path))
        if self.mode != "100644":
            raise ValueError("only ordinary 100644 files are supported")
        if self.type != "blob":
            raise ValueError("only blob entries are supported")
        object.__setattr__(self, "sha", require_sha40(self.sha, "blob_sha"))


@dataclass(frozen=True, slots=True)
class GitTreeSnapshot:
    sha: str
    entries: tuple[GitTreeEntry, ...]
    truncated: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha", require_sha40(self.sha, "tree_sha"))
        if not isinstance(self.entries, tuple):
            raise TypeError("entries must be a tuple")
        paths = [entry.path for entry in self.entries]
        if len(paths) != len(set(paths)):
            raise ValueError("tree contains duplicate paths")
        if type(self.truncated) is not bool:
            raise TypeError("truncated must be bool")


@dataclass(frozen=True, slots=True)
class GitBlobSnapshot:
    sha: str
    size: int
    encoding: str
    content: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha", require_sha40(self.sha, "blob_sha"))
        if type(self.size) is not int or self.size < 0:
            raise ValueError("blob size must be a non-negative integer")
        if self.encoding not in {"utf-8", "base64", "none"}:
            raise ValueError("blob encoding is unsupported")
        if self.content is not None and not isinstance(self.content, str):
            raise TypeError("blob content must be text or None")


@dataclass(frozen=True, slots=True)
class GitChangedFile:
    path: str
    status: str
    blob_sha: str
    previous_path: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", require_path(self.path))
        if self.status not in _ALLOWED_COMPARE_STATUSES | {"removed", "renamed"}:
            raise ValueError("changed-file status is unsupported")
        object.__setattr__(self, "blob_sha", require_sha40(self.blob_sha, "blob_sha"))
        if self.previous_path is not None:
            object.__setattr__(self, "previous_path", require_path(self.previous_path))


@dataclass(frozen=True, slots=True)
class GitCompareSnapshot:
    status: str
    ahead_by: int
    behind_by: int
    total_commits: int
    changed_files: tuple[GitChangedFile, ...]
    additions: int
    deletions: int

    def __post_init__(self) -> None:
        if self.status not in {"ahead", "behind", "diverged", "identical"}:
            raise ValueError("compare status is unsupported")
        for name in ("ahead_by", "behind_by", "total_commits", "additions", "deletions"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.changed_files, tuple):
            raise TypeError("changed_files must be a tuple")
        paths = [item.path for item in self.changed_files]
        if len(paths) != len(set(paths)):
            raise ValueError("compare result contains duplicate paths")


class MutationState(str, Enum):
    NOT_ATTEMPTED = "not-attempted"
    FAILED_BEFORE_SIDE_EFFECT = "failed-before-side-effect"
    UNCERTAIN = "uncertain"
    CONFIRMED = "confirmed"


class AtomicCommitStatus(str, Enum):
    PLANNED = "planned"
    REF_UPDATED = "ref-updated"
    BLOCKED = "blocked"
    UNCERTAIN = "uncertain"


class AtomicCommitReason(str, Enum):
    PLAN_READY = "plan-ready"
    REF_UPDATED = "ref-updated"
    INVALID_REQUEST = "invalid-request"
    INITIAL_HEAD_MISMATCH = "initial-head-mismatch"
    COMMIT_SHAPE_UNSUPPORTED = "commit-shape-unsupported"
    BLOB_MISSING_OR_MISMATCHED = "blob-missing-or-mismatched"
    CONFIRMATION_MISSING = "confirmation-missing"
    CONFIRMATION_CANCELLED = "confirmation-cancelled"
    CONFIRMATION_MISMATCHED = "confirmation-mismatched"
    REPEAT_INVOCATION = "repeat-invocation"
    CONCURRENCY_STOP = "concurrency-stop"
    TREE_CREATE_FAILED = "tree-create-failed"
    TREE_CREATE_UNCERTAIN = "tree-create-uncertain"
    COMMIT_CREATE_FAILED = "commit-create-failed"
    COMMIT_CREATE_UNCERTAIN = "commit-create-uncertain"
    UNATTACHED_VALIDATION_STOP = "unattached-validation-stop"
    REF_UPDATE_FAILED = "ref-update-failed"
    REF_UPDATE_UNCERTAIN = "ref-update-uncertain"
    POST_UPDATE_MISMATCH = "post-update-mismatch"
    TRANSPORT_FAILURE = "transport-failure"


@dataclass(frozen=True, slots=True)
class AtomicCommitRequest:
    repository: str
    branch: str
    expected_head_sha: str
    allowed_paths: tuple[str, ...]
    entries: tuple[GitTreeEntry, ...]
    message: str
    invocation_id: str
    prior_fingerprints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", require_repository(self.repository))
        object.__setattr__(self, "branch", require_branch(self.branch))
        object.__setattr__(
            self, "expected_head_sha", require_sha40(self.expected_head_sha, "expected_head_sha")
        )
        if not isinstance(self.allowed_paths, tuple) or not self.allowed_paths:
            raise ValueError("allowed_paths must be a non-empty tuple")
        allowed = tuple(sorted(require_path(path) for path in self.allowed_paths))
        if len(allowed) != len(set(allowed)):
            raise ValueError("allowed_paths contains duplicates")
        if not isinstance(self.entries, tuple) or not self.entries:
            raise ValueError("entries must be a non-empty tuple")
        entry_paths = tuple(sorted(entry.path for entry in self.entries))
        if len(entry_paths) != len(set(entry_paths)):
            raise ValueError("entries contain duplicate paths")
        if entry_paths != allowed:
            raise ValueError("entries must exactly match allowed_paths")
        if not isinstance(self.message, str) or self.message != self.message.strip() or not self.message:
            raise ValueError("message must be non-empty trimmed text")
        if len(self.message.encode("utf-8")) > 4096 or _CONTROL_RE.search(self.message):
            raise ValueError("message is oversized or contains control characters")
        if not isinstance(self.invocation_id, str) or self.invocation_id != self.invocation_id.strip() or not self.invocation_id:
            raise ValueError("invocation_id must be non-empty trimmed text")
        if len(self.invocation_id) > 256 or _CONTROL_RE.search(self.invocation_id):
            raise ValueError("invocation_id is malformed")
        if not isinstance(self.prior_fingerprints, tuple):
            raise TypeError("prior_fingerprints must be a tuple")
        for fingerprint in self.prior_fingerprints:
            if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                raise ValueError("prior_fingerprints must contain SHA-256 hex strings")
        object.__setattr__(self, "allowed_paths", allowed)
        object.__setattr__(self, "entries", tuple(sorted(self.entries, key=lambda item: item.path)))


@dataclass(frozen=True, slots=True)
class AtomicCommitPlan:
    request: AtomicCommitRequest
    parent_tree_sha: str
    operation_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "parent_tree_sha", require_sha40(self.parent_tree_sha, "parent_tree_sha"))
        if not re.fullmatch(r"[0-9a-f]{64}", self.operation_fingerprint):
            raise ValueError("operation_fingerprint must be SHA-256 hex")


@dataclass(frozen=True, slots=True)
class AtomicCommitConfirmation:
    invocation_id: str
    operation_fingerprint: str
    repository: str
    branch: str
    expected_head_sha: str
    confirmed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.invocation_id, str) or not self.invocation_id:
            raise ValueError("invocation_id is required")
        if not re.fullmatch(r"[0-9a-f]{64}", self.operation_fingerprint):
            raise ValueError("operation_fingerprint must be SHA-256 hex")
        object.__setattr__(self, "repository", require_repository(self.repository))
        object.__setattr__(self, "branch", require_branch(self.branch))
        object.__setattr__(
            self, "expected_head_sha", require_sha40(self.expected_head_sha, "expected_head_sha")
        )
        if type(self.confirmed) is not bool:
            raise TypeError("confirmed must be bool")


@dataclass(frozen=True, slots=True)
class AtomicCommitResult:
    status: AtomicCommitStatus
    reason: AtomicCommitReason
    operation_fingerprint: str | None
    starting_branch_sha: str | None
    ending_branch_sha: str | None
    parent_tree_sha: str | None
    created_tree_sha: str | None
    created_commit_sha: str | None
    changed_paths: tuple[str, ...] = ()
    additions: int = 0
    deletions: int = 0
    confirmation_requested: bool = False
    confirmation_matched: bool = False
    execution_attempted: bool = False
    ref_update_attempted: bool = False
    mutation_state: MutationState = MutationState.NOT_ATTEMPTED
    unattached_objects: tuple[str, ...] = ()
    sanitized_diagnostic: str = ""
    retry_allowed: bool = False
    force_used: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_mutation_authorized: Literal[False] = field(default=False, init=False)
    workflow_mutation_authorized: Literal[False] = field(default=False, init=False)
