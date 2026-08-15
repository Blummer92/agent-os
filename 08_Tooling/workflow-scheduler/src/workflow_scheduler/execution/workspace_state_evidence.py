"""Complete, content-addressed workspace-state and changed-path evidence.

Extends the existing Git worktree inspection surface (``GitWorktreeAdapter``,
its injected ``GitRunner``/``PosixGitRunner``, and the bounded POSIX process
path) with an authoritative evidence model that never collapses staged,
unstaged, untracked, ignored, renamed/copied, deleted, conflicted, or
submodule-relevant Git state into a single ``clean`` boolean or a
filename-only set.

This module contains only immutable models, parsing/canonicalization,
identity, comparison, and composition. It creates no second Git runner,
worktree manager, subprocess framework, or cleanup subsystem, and it adds no
destructive Git command. Observation is read-only: it runs
``git status --porcelain=v2 -z`` and ``git worktree list --porcelain -z``
through a caller-supplied ``GitRunner`` exactly as ``GitWorktreeAdapter``
already does.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import time
from dataclasses import dataclass, field
from typing import Mapping

from scripts.agent_os_execution_capabilities.models import RepositoryIdentity
from workflow_scheduler.execution.git_worktree_adapter import (
    GitObservation,
    GitRunner,
    GitWorktreeAdapterError,
    _branch_name,
    _parse_porcelain,
)

MAX_GIT_OUTPUT_BYTES = 65_536
MAX_GIT_TIMEOUT_SECONDS = 30.0
MAX_TEXT_BYTES = 4096
MAX_REASON_BYTES = 512
MAX_STATUS_RECORDS = 512
MAX_REASON_CODES = 64

_OBSERVATION_KINDS = frozenset({"initial", "final"})
_PATH_CATEGORIES = frozenset(
    {
        "staged",
        "unstaged",
        "untracked",
        "ignored",
        "renamed",
        "copied",
        "deleted",
        "conflict",
        "submodule",
    }
)
_NON_DIRTY_CATEGORIES = frozenset({"ignored"})
_DIRTY_CATEGORIES = _PATH_CATEGORIES - _NON_DIRTY_CATEGORIES

INSPECTOR_IDENTITY = "agent-os-workspace-state-evidence"
INSPECTOR_VERSION = "1.0"


class WorkspaceStateEvidenceError(ValueError):
    """Raised for malformed, unresolved, or unsupported evidence input."""


def _bounded_text(value: object, *, maximum: int = MAX_TEXT_BYTES) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise WorkspaceStateEvidenceError("value must be NUL-free text")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise WorkspaceStateEvidenceError("value must be valid UTF-8 text") from exc
    if len(encoded) > maximum:
        raise WorkspaceStateEvidenceError("value exceeds the bounded byte length")
    return value


def _reason(value: object) -> str:
    raw = str(value).encode("utf-8", errors="replace")[:MAX_REASON_BYTES]
    return raw.decode("utf-8", errors="ignore")


def canonical_changed_path(raw: object) -> str:
    """The one canonical path-validation policy for every path-bearing record.

    Rejects absolute paths, traversal, malformed/noncanonical values, and
    control or NUL-bearing text. Never silently normalizes a noncanonical
    value -- normalization must not erase rename/copy source/destination
    identity, so a noncanonical path is rejected rather than rewritten.
    """
    if not isinstance(raw, str) or raw == "":
        raise WorkspaceStateEvidenceError("path must be non-empty text")
    if "\x00" in raw:
        raise WorkspaceStateEvidenceError("path contains an embedded NUL")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in raw):
        raise WorkspaceStateEvidenceError("path contains control characters")
    try:
        encoded = raw.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise WorkspaceStateEvidenceError("path must be valid UTF-8 text") from exc
    if len(encoded) > MAX_TEXT_BYTES:
        raise WorkspaceStateEvidenceError("path exceeds the bounded byte length")
    if raw.startswith("/") or raw.startswith("\\") or (len(raw) > 1 and raw[1] == ":"):
        raise WorkspaceStateEvidenceError("path must not be absolute")
    segments = raw.split("/")
    if "" in segments or "." in segments or ".." in segments:
        raise WorkspaceStateEvidenceError(
            "path must not contain empty, '.', or '..' segments"
        )
    if posixpath.normpath(raw) != raw:
        raise WorkspaceStateEvidenceError("path must be in canonical normalized form")
    return raw


@dataclass(frozen=True, slots=True, kw_only=True)
class WorktreeListRecord:
    """Public mirror of one ``git worktree list --porcelain -z`` record."""

    path: str
    head: str
    branch: str | None
    detached: bool
    bare: bool
    locked: bool
    lock_reason: str
    prunable: bool
    prunable_reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ChangedPathObservation:
    """One canonical, category-preserving changed-path record."""

    category: str
    path: str
    orig_path: str = ""
    index_status: str = ""
    worktree_status: str = ""
    submodule_state: str = ""
    rename_score: str = ""

    def __post_init__(self) -> None:
        if self.category not in _PATH_CATEGORIES:
            raise WorkspaceStateEvidenceError("unsupported changed-path category")
        canonical_changed_path(self.path)
        if self.orig_path:
            canonical_changed_path(self.orig_path)
        for name in ("index_status", "worktree_status", "submodule_state", "rename_score"):
            _bounded_text(getattr(self, name), maximum=16)
        if self.category in ("renamed", "copied") and not self.orig_path:
            raise WorkspaceStateEvidenceError(
                "rename/copy evidence must retain source identity"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "path": self.path,
            "orig_path": self.orig_path,
            "index_status": self.index_status,
            "worktree_status": self.worktree_status,
            "submodule_state": self.submodule_state,
            "rename_score": self.rename_score,
        }


def _sort_key(item: ChangedPathObservation) -> tuple[str, str, str]:
    return (item.path, item.orig_path, item.category)


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceStateObservation:
    """One complete, content-addressed workspace-state observation."""

    observation_kind: str
    repository_owner: str
    repository_name: str
    workspace_path: str
    branch: str
    expected_sha: str
    observed_sha: str
    lock_identity: str = ""
    worktree_record: WorktreeListRecord | None
    staged: tuple[ChangedPathObservation, ...] = ()
    unstaged: tuple[ChangedPathObservation, ...] = ()
    untracked: tuple[ChangedPathObservation, ...] = ()
    ignored: tuple[ChangedPathObservation, ...] = ()
    renamed: tuple[ChangedPathObservation, ...] = ()
    copied: tuple[ChangedPathObservation, ...] = ()
    deleted: tuple[ChangedPathObservation, ...] = ()
    conflict: tuple[ChangedPathObservation, ...] = ()
    submodule: tuple[ChangedPathObservation, ...] = ()
    inspector_identity: str = INSPECTOR_IDENTITY
    inspector_version: str = INSPECTOR_VERSION
    observed_at: str
    complete: bool
    reason_codes: tuple[str, ...] = ()
    evidence_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.observation_kind not in _OBSERVATION_KINDS:
            raise WorkspaceStateEvidenceError("unsupported observation_kind")
        for name in (
            "repository_owner",
            "repository_name",
            "workspace_path",
            "branch",
            "observed_at",
            "inspector_identity",
            "inspector_version",
        ):
            _bounded_text(getattr(self, name))
        for name in ("expected_sha", "observed_sha", "lock_identity"):
            _bounded_text(getattr(self, name))
        if len(self.reason_codes) > MAX_REASON_CODES:
            raise WorkspaceStateEvidenceError("reason_codes exceeds the bounded count")
        for code in self.reason_codes:
            _bounded_text(code, maximum=MAX_REASON_BYTES)
        for category_name in (
            "staged",
            "unstaged",
            "untracked",
            "ignored",
            "renamed",
            "copied",
            "deleted",
            "conflict",
            "submodule",
        ):
            entries = getattr(self, category_name)
            if not isinstance(entries, tuple) or not all(
                isinstance(entry, ChangedPathObservation) for entry in entries
            ):
                raise WorkspaceStateEvidenceError(
                    f"{category_name} must be a tuple of ChangedPathObservation"
                )
            for entry in entries:
                if entry.category != category_name:
                    raise WorkspaceStateEvidenceError(
                        f"{category_name} contains a record from a different category"
                    )
            ordered = tuple(sorted(entries, key=_sort_key))
            if entries != ordered:
                raise WorkspaceStateEvidenceError(
                    f"{category_name} is not in deterministic canonical order"
                )
        object.__setattr__(self, "evidence_id", "evidence:" + _digest(self.as_dict()))

    def as_dict(self) -> dict[str, object]:
        worktree = None
        if self.worktree_record is not None:
            worktree = {
                "path": self.worktree_record.path,
                "head": self.worktree_record.head,
                "branch": self.worktree_record.branch,
                "detached": self.worktree_record.detached,
                "bare": self.worktree_record.bare,
                "locked": self.worktree_record.locked,
                "lock_reason": self.worktree_record.lock_reason,
                "prunable": self.worktree_record.prunable,
                "prunable_reason": self.worktree_record.prunable_reason,
            }
        return {
            "observation_kind": self.observation_kind,
            "repository_owner": self.repository_owner,
            "repository_name": self.repository_name,
            "workspace_path": self.workspace_path,
            "branch": self.branch,
            "expected_sha": self.expected_sha,
            "observed_sha": self.observed_sha,
            "lock_identity": self.lock_identity,
            "worktree_record": worktree,
            "staged": [item.as_dict() for item in self.staged],
            "unstaged": [item.as_dict() for item in self.unstaged],
            "untracked": [item.as_dict() for item in self.untracked],
            "ignored": [item.as_dict() for item in self.ignored],
            "renamed": [item.as_dict() for item in self.renamed],
            "copied": [item.as_dict() for item in self.copied],
            "deleted": [item.as_dict() for item in self.deleted],
            "conflict": [item.as_dict() for item in self.conflict],
            "submodule": [item.as_dict() for item in self.submodule],
            "inspector_identity": self.inspector_identity,
            "inspector_version": self.inspector_version,
            "observed_at": self.observed_at,
            "complete": self.complete,
            "reason_codes": list(self.reason_codes),
        }

    @property
    def is_clean(self) -> bool:
        """Derived convenience value only; the underlying categories remain authoritative."""
        if not self.complete:
            return False
        return not any(
            getattr(self, category) for category in _DIRTY_CATEGORIES
        )

    @property
    def all_changed_paths(self) -> frozenset[str]:
        paths: set[str] = set()
        for category in _DIRTY_CATEGORIES:
            paths.update(item.path for item in getattr(self, category))
        return frozenset(paths)


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceLifecycleEvidence:
    """Bundles exactly one initial and one final workspace-state observation."""

    initial: WorkspaceStateObservation
    final: WorkspaceStateObservation
    validation_only: bool
    lifecycle_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.initial, WorkspaceStateObservation) or not isinstance(
            self.final, WorkspaceStateObservation
        ):
            raise WorkspaceStateEvidenceError(
                "initial and final must be WorkspaceStateObservation"
            )
        if self.initial.observation_kind != "initial":
            raise WorkspaceStateEvidenceError("initial observation has the wrong kind")
        if self.final.observation_kind != "final":
            raise WorkspaceStateEvidenceError("final observation has the wrong kind")
        if type(self.validation_only) is not bool:
            raise WorkspaceStateEvidenceError("validation_only must be a boolean")
        object.__setattr__(
            self,
            "lifecycle_id",
            "lifecycle:" + _digest(
                {
                    "initial": self.initial.evidence_id,
                    "final": self.final.evidence_id,
                    "validation_only": self.validation_only,
                }
            ),
        )

    @property
    def initial_blocks_validation(self) -> bool:
        """Dirty or incomplete initial state blocks before validation."""
        return not self.initial.complete or not self.initial.is_clean

    @property
    def final_prevents_success(self) -> bool:
        """Any final changed state (or incompleteness) prevents validation-only success."""
        return not self.final.complete or not self.final.is_clean

    @property
    def validation_only_success(self) -> bool:
        if not self.validation_only:
            return False
        return not self.initial_blocks_validation and not self.final_prevents_success

    def satisfies_expected_changed_paths(self, expected_changed_paths: frozenset[str]) -> bool:
        """Validation-only success requires the expected and observed sets to be empty."""
        if not self.validation_only_success:
            return False
        return not expected_changed_paths and not self.final.all_changed_paths


def _classify_ordinary(path: str, xy: str, sub: str) -> tuple[ChangedPathObservation, ...]:
    index_status, worktree_status = xy[0], xy[1]
    results: list[ChangedPathObservation] = []
    if index_status != ".":
        results.append(
            ChangedPathObservation(
                category="staged",
                path=path,
                index_status=index_status,
                worktree_status=worktree_status,
                submodule_state=sub,
            )
        )
    if worktree_status != ".":
        results.append(
            ChangedPathObservation(
                category="unstaged",
                path=path,
                index_status=index_status,
                worktree_status=worktree_status,
                submodule_state=sub,
            )
        )
    if index_status == "D" or worktree_status == "D":
        results.append(
            ChangedPathObservation(
                category="deleted",
                path=path,
                index_status=index_status,
                worktree_status=worktree_status,
                submodule_state=sub,
            )
        )
    if sub[0] == "S":
        results.append(
            ChangedPathObservation(
                category="submodule",
                path=path,
                index_status=index_status,
                worktree_status=worktree_status,
                submodule_state=sub,
            )
        )
    return tuple(results)


def _classify_rename_copy(
    path: str, orig_path: str, xy: str, sub: str, score: str
) -> tuple[ChangedPathObservation, ...]:
    index_status, worktree_status = xy[0], xy[1]
    if index_status not in ("R", "C"):
        raise WorkspaceStateEvidenceError("rename/copy record has an invalid index status")
    if len(score) < 2 or score[0] not in ("R", "C") or not score[1:].isdigit():
        raise WorkspaceStateEvidenceError("rename/copy record has a malformed score field")
    category = "renamed" if index_status == "R" else "copied"
    results = [
        ChangedPathObservation(
            category=category,
            path=path,
            orig_path=orig_path,
            index_status=index_status,
            worktree_status=worktree_status,
            submodule_state=sub,
            rename_score=score,
        )
    ]
    if worktree_status != ".":
        results.append(
            ChangedPathObservation(
                category="unstaged",
                path=path,
                index_status=index_status,
                worktree_status=worktree_status,
                submodule_state=sub,
            )
        )
    if worktree_status == "D":
        results.append(
            ChangedPathObservation(
                category="deleted",
                path=path,
                index_status=index_status,
                worktree_status=worktree_status,
                submodule_state=sub,
            )
        )
    if sub[0] == "S":
        results.append(
            ChangedPathObservation(
                category="submodule",
                path=path,
                index_status=index_status,
                worktree_status=worktree_status,
                submodule_state=sub,
            )
        )
    return tuple(results)


def _validate_submodule_field(sub: str) -> None:
    if len(sub) != 4 or sub[0] not in ("N", "S"):
        raise WorkspaceStateEvidenceError("malformed submodule state field")


def parse_status_porcelain_v2(raw: str) -> dict[str, tuple[ChangedPathObservation, ...]]:
    """Parse ``git status --porcelain=v2 -z`` output, failing closed on ambiguity.

    Unknown documented extensible ``#`` header lines are skipped forward-
    compatibly. Any other unsupported record type, truncated rename/copy
    pairing, malformed field, or duplicate/conflicting top-level path record
    raises ``WorkspaceStateEvidenceError`` rather than guessing.
    """
    buckets: dict[str, list[ChangedPathObservation]] = {
        category: [] for category in _PATH_CATEGORIES
    }
    if raw == "":
        return {category: () for category in _PATH_CATEGORIES}
    if raw[-1] != "\x00":
        raise WorkspaceStateEvidenceError("status output is missing terminal NUL framing")
    tokens = raw.split("\x00")[:-1]
    seen_paths: set[str] = set()
    record_count = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "":
            raise WorkspaceStateEvidenceError("empty status record encountered")
        record_count += 1
        if record_count > MAX_STATUS_RECORDS:
            raise WorkspaceStateEvidenceError("oversized evidence: too many status records")
        kind = token[0]
        if kind == "#":
            index += 1
            continue
        if kind == "1":
            fields = token.split(" ", 8)
            if len(fields) != 9:
                raise WorkspaceStateEvidenceError("malformed ordinary status record")
            _, xy, sub, _mH, _mI, _mW, _hH, _hI, path = fields
            if len(xy) != 2:
                raise WorkspaceStateEvidenceError("malformed ordinary status XY field")
            _validate_submodule_field(sub)
            path = canonical_changed_path(path)
            if path in seen_paths:
                raise WorkspaceStateEvidenceError("duplicate or conflicting status record")
            seen_paths.add(path)
            for entry in _classify_ordinary(path, xy, sub):
                buckets[entry.category].append(entry)
            index += 1
        elif kind == "2":
            fields = token.split(" ", 9)
            if len(fields) != 10:
                raise WorkspaceStateEvidenceError("malformed rename/copy status record")
            _, xy, sub, _mH, _mI, _mW, _hH, _hI, score, path = fields
            if len(xy) != 2:
                raise WorkspaceStateEvidenceError("malformed rename/copy status XY field")
            _validate_submodule_field(sub)
            path = canonical_changed_path(path)
            index += 1
            if index >= len(tokens):
                raise WorkspaceStateEvidenceError(
                    "truncated rename/copy record: missing source path"
                )
            orig_path = canonical_changed_path(tokens[index])
            index += 1
            if path in seen_paths:
                raise WorkspaceStateEvidenceError("duplicate or conflicting status record")
            seen_paths.add(path)
            for entry in _classify_rename_copy(path, orig_path, xy, sub, score):
                buckets[entry.category].append(entry)
        elif kind == "u":
            fields = token.split(" ", 10)
            if len(fields) != 11:
                raise WorkspaceStateEvidenceError("malformed unmerged status record")
            _, xy, sub, _m1, _m2, _m3, _mW, _h1, _h2, _h3, path = fields
            if len(xy) != 2:
                raise WorkspaceStateEvidenceError("malformed unmerged status XY field")
            _validate_submodule_field(sub)
            path = canonical_changed_path(path)
            if path in seen_paths:
                raise WorkspaceStateEvidenceError("duplicate or conflicting status record")
            seen_paths.add(path)
            buckets["conflict"].append(
                ChangedPathObservation(
                    category="conflict",
                    path=path,
                    index_status=xy[0],
                    worktree_status=xy[1],
                    submodule_state=sub,
                )
            )
            if sub[0] == "S":
                buckets["submodule"].append(
                    ChangedPathObservation(
                        category="submodule",
                        path=path,
                        index_status=xy[0],
                        worktree_status=xy[1],
                        submodule_state=sub,
                    )
                )
            index += 1
        elif kind in ("?", "!"):
            fields = token.split(" ", 1)
            if len(fields) != 2:
                raise WorkspaceStateEvidenceError("malformed untracked/ignored status record")
            path = canonical_changed_path(fields[1])
            if path in seen_paths:
                raise WorkspaceStateEvidenceError("duplicate or conflicting status record")
            seen_paths.add(path)
            category = "untracked" if kind == "?" else "ignored"
            buckets[category].append(
                ChangedPathObservation(category=category, path=path)
            )
            index += 1
        else:
            raise WorkspaceStateEvidenceError(f"unsupported status record type: {kind!r}")
    return {
        category: tuple(sorted(entries, key=_sort_key))
        for category, entries in buckets.items()
    }


def _observation_failure(observation: GitObservation, label: str) -> tuple[str, ...]:
    if observation.succeeded:
        return ()
    reasons = []
    if not observation.started:
        reasons.append(f"{label}:not-started")
    if observation.timed_out:
        reasons.append(f"{label}:timeout")
    if not observation.termination_confirmed:
        reasons.append(f"{label}:termination-unconfirmed")
    if observation.stdout_truncated or observation.stderr_truncated:
        reasons.append(f"{label}:truncated")
    if observation.return_code not in (0, None):
        reasons.append(f"{label}:nonzero-exit")
    if not reasons:
        reasons.append(_reason(f"{label}:{observation.reason or 'unavailable'}"))
    return tuple(reasons)


def build_workspace_state_observation(
    *,
    observation_kind: str,
    repository_identity: RepositoryIdentity,
    workspace_path: str,
    branch: str,
    expected_sha: str,
    lock_identity: str = "",
    worktree_list_observation: GitObservation,
    status_observation: GitObservation,
    observed_at: str = "",
) -> WorkspaceStateObservation:
    """Compose one complete observation from two already-executed Git calls.

    Both Git calls must already have been run through the existing bounded
    ``GitRunner``; this function performs no process execution itself.
    """
    reason_codes: list[str] = []
    worktree_record: WorktreeListRecord | None = None
    observed_sha = ""
    resolved_branch = branch

    reason_codes.extend(_observation_failure(worktree_list_observation, "worktree-list"))
    matched_record = None
    if worktree_list_observation.succeeded:
        try:
            records = _parse_porcelain(worktree_list_observation.stdout)
        except GitWorktreeAdapterError as exc:
            reason_codes.append(_reason(f"worktree-list:malformed:{exc}"))
            records = ()
        matches = tuple(record for record in records if record.path == workspace_path)
        if len(matches) == 1:
            matched_record = matches[0]
        elif len(matches) == 0:
            reason_codes.append("worktree-list:record-missing")
        else:
            reason_codes.append("worktree-list:record-duplicated")

    if matched_record is not None:
        worktree_record = WorktreeListRecord(
            path=matched_record.path,
            head=matched_record.head,
            branch=matched_record.branch,
            detached=matched_record.detached,
            bare=matched_record.bare,
            locked=matched_record.locked,
            lock_reason=matched_record.lock_reason,
            prunable=matched_record.prunable,
            prunable_reason=matched_record.prunable_reason,
        )
        observed_sha = matched_record.head
        resolved_branch = _branch_name(matched_record.branch) or branch
        if matched_record.prunable:
            reason_codes.append("worktree-list:prunable")
        if lock_identity and (
            not matched_record.locked or matched_record.lock_reason != lock_identity
        ):
            reason_codes.append("worktree-list:lock-identity-mismatch")

    categorized: dict[str, tuple[ChangedPathObservation, ...]] = {
        category: () for category in _PATH_CATEGORIES
    }
    reason_codes.extend(_observation_failure(status_observation, "status"))
    if status_observation.succeeded:
        try:
            categorized = parse_status_porcelain_v2(status_observation.stdout)
        except WorkspaceStateEvidenceError as exc:
            reason_codes.append(_reason(f"status:malformed:{exc}"))

    complete = (
        worktree_list_observation.succeeded
        and status_observation.succeeded
        and matched_record is not None
        and not matched_record.prunable
        and (not lock_identity or (matched_record.locked and matched_record.lock_reason == lock_identity))
        and not any(code.startswith("status:malformed") for code in reason_codes)
    )

    return WorkspaceStateObservation(
        observation_kind=observation_kind,
        repository_owner=repository_identity.owner,
        repository_name=repository_identity.repository,
        workspace_path=workspace_path,
        branch=resolved_branch,
        expected_sha=expected_sha,
        observed_sha=observed_sha,
        lock_identity=lock_identity,
        worktree_record=worktree_record,
        staged=categorized["staged"],
        unstaged=categorized["unstaged"],
        untracked=categorized["untracked"],
        ignored=categorized["ignored"],
        renamed=categorized["renamed"],
        copied=categorized["copied"],
        deleted=categorized["deleted"],
        conflict=categorized["conflict"],
        submodule=categorized["submodule"],
        observed_at=observed_at or f"monotonic:{time.monotonic_ns()}",
        complete=complete,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )


def inspect_complete_workspace_state(
    *,
    runner: GitRunner,
    git_binary: str = "git",
    repository_root: str,
    workspace_path: str,
    repository_identity: RepositoryIdentity,
    branch: str,
    expected_sha: str,
    lock_identity: str = "",
    observation_kind: str,
    environment: Mapping[str, str],
    timeout_seconds: float = MAX_GIT_TIMEOUT_SECONDS,
    max_output_bytes: int = MAX_GIT_OUTPUT_BYTES,
    observed_at: str = "",
) -> WorkspaceStateObservation:
    """Capture one complete workspace-state observation through the existing runner.

    Reuses the caller's ``GitRunner`` (typically the same runner bound to a
    ``GitWorktreeAdapter``) for both machine-readable Git calls. Does not
    create a new runner, worktree manager, or subprocess framework.
    """
    if observation_kind not in _OBSERVATION_KINDS:
        raise WorkspaceStateEvidenceError("unsupported observation_kind")

    worktree_list_observation = runner.run(
        (git_binary, "-C", repository_root, "worktree", "list", "--porcelain", "-z"),
        cwd=repository_root,
        env=environment,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
    )
    status_observation = runner.run(
        (
            git_binary,
            "-C",
            workspace_path,
            "status",
            "--porcelain=v2",
            "-z",
            "--untracked-files=all",
            "--ignored=matching",
        ),
        cwd=workspace_path,
        env=environment,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
    )
    return build_workspace_state_observation(
        observation_kind=observation_kind,
        repository_identity=repository_identity,
        workspace_path=workspace_path,
        branch=branch,
        expected_sha=expected_sha,
        lock_identity=lock_identity,
        worktree_list_observation=worktree_list_observation,
        status_observation=status_observation,
        observed_at=observed_at,
    )
