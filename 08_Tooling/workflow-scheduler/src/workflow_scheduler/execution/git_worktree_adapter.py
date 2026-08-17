"""Bounded, identity-bound Git worktree implementation of WorkspaceAdapter."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Mapping, Protocol, runtime_checkable

if TYPE_CHECKING:
    from workflow_scheduler.execution.workspace_state_evidence import (
        WorkspaceStateObservation,
    )

from scripts.agent_os_execution_capabilities.models import (
    CAPABILITY_EVIDENCE_SCHEMA_NAME,
    CAPABILITY_EVIDENCE_SCHEMA_VERSION,
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateEvidence,
    WorktreeState,
)
from scripts.agent_os_execution_capabilities.repository_state import (
    validate_repository_state_evidence,
)
from workflow_scheduler.execution.posix_process_adapter import run_bounded_posix_process
from workflow_scheduler.execution.single_issue_pilot import (
    WorkspaceCleanup,
    WorkspaceHandle,
    WorkspaceInspection,
    WorkspaceRequest,
    pilot_workspace_identity,
)

MAX_GIT_OUTPUT_BYTES = 65_536
MAX_GIT_TIMEOUT_SECONDS = 30.0
MAX_REASON_BYTES = 512
MAX_TEXT_BYTES = 4096
MAX_RECORDS = 128
MAX_ENV_ITEMS = 64
MAX_ENV_BYTES = 65_536
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_PREPARATION_MODES = frozenset({"branch", "tag", "detached-sha"})
_PREPARATION_OUTCOMES = frozenset(
    {"prepared", "already-prepared", "manual-review", "blocked", "unavailable"}
)
_PREPARATION_SIDE_EFFECTS = frozenset(
    {
        "no-creation-attempted",
        "creation-attempted-no-workspace",
        "partial-creation-observed",
        "verified-prepared",
        "verified-reused",
    }
)
_FIELDS = frozenset(
    {"worktree", "HEAD", "branch", "detached", "bare", "locked", "prunable"}
)


class GitWorktreeAdapterError(ValueError):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspacePreparationRequest:
    """Bounded request for an immutable workspace preparation."""

    workspace_request_id: str
    repository: str
    requested_ref: str
    expected_revision: str
    mode: Literal["branch", "tag", "detached-sha"]


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspacePreparationResult:
    """Deterministic evidence of a bounded workspace preparation."""

    outcome: Literal[
        "prepared", "already-prepared", "manual-review", "blocked", "unavailable"
    ]
    workspace_identity: str
    repository: str
    requested_ref: str
    resolved_ref: str
    exact_sha: str
    mode: Literal["branch", "tag", "detached-sha"]
    path: str
    clean: bool
    reused: bool
    locked: bool
    side_effect_state: Literal[
        "no-creation-attempted",
        "creation-attempted-no-workspace",
        "partial-creation-observed",
        "verified-prepared",
        "verified-reused",
    ]
    reason: str = ""
    repository_implementation_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    github_writes_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.outcome not in _PREPARATION_OUTCOMES:
            raise GitWorktreeAdapterError("invalid preparation outcome")
        if self.side_effect_state not in _PREPARATION_SIDE_EFFECTS:
            raise GitWorktreeAdapterError("invalid preparation side-effect state")
        if self.mode not in _PREPARATION_MODES:
            raise GitWorktreeAdapterError("invalid preparation result mode")
        for name in (
            "workspace_identity",
            "repository",
            "requested_ref",
            "resolved_ref",
            "path",
        ):
            value = getattr(self, name)
            if _safe_result_text(value) != value:
                raise GitWorktreeAdapterError(f"{name} is not bounded exact text")
        if self.exact_sha and not _SHA40.fullmatch(self.exact_sha):
            raise GitWorktreeAdapterError("exact_sha is malformed")
        if _reason(self.reason) != self.reason:
            raise GitWorktreeAdapterError("reason is not bounded")
        for name in ("clean", "reused", "locked"):
            if type(getattr(self, name)) is not bool:
                raise GitWorktreeAdapterError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True, kw_only=True)
class GitObservation:
    started: bool
    return_code: int | None
    timed_out: bool
    termination_confirmed: bool
    stdout: str = field(default="", repr=False)
    stderr: str = field(default="", repr=False)
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    reason: str = field(default="", repr=False)

    @property
    def succeeded(self) -> bool:
        return bool(
            self.started
            and self.termination_confirmed
            and not self.timed_out
            and self.return_code == 0
            and not self.stdout_truncated
            and not self.stderr_truncated
        )


@runtime_checkable
class GitRunner(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: str,
        env: Mapping[str, str],
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> GitObservation: ...


class PosixGitRunner:
    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: str,
        env: Mapping[str, str],
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> GitObservation:
        result = run_bounded_posix_process(
            argv,
            cwd=cwd,
            env=dict(env),
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        return GitObservation(
            started=result.started,
            return_code=result.return_code,
            timed_out=result.timeout_observed,
            termination_confirmed=result.termination_confirmed,
            stdout=result.stdout_text,
            stderr=result.stderr_text,
            stdout_truncated=result.stdout_truncated,
            stderr_truncated=result.stderr_truncated,
            reason=result.reason,
        )


@dataclass(frozen=True, slots=True)
class _Record:
    path: str
    head: str
    branch: str | None
    detached: bool
    bare: bool
    locked: bool
    lock_reason: str
    prunable: bool
    prunable_reason: str


@dataclass(slots=True)
class _Binding:
    request: WorkspaceRequest
    identity: str
    path: str
    branch_ref: str
    lock_reason: str
    cleanup_attempted: bool = False
    detached: bool = False


def _text(value: object, name: str, maximum: int = MAX_TEXT_BYTES) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise GitWorktreeAdapterError(f"{name} must be non-empty NUL-free text")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise GitWorktreeAdapterError(f"{name} must be valid UTF-8 text") from exc
    if len(encoded) > maximum:
        raise GitWorktreeAdapterError(f"{name} exceeds the bounded byte length")
    return value


def _reason(value: object) -> str:
    raw = str(value).encode("utf-8", errors="replace")[:MAX_REASON_BYTES]
    return raw.decode("utf-8", errors="ignore")


def _safe_result_text(value: object, *, maximum: int = MAX_TEXT_BYTES) -> str:
    """Return bounded exact text without coercing arbitrary objects."""
    if not isinstance(value, str) or "\x00" in value:
        return ""
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return ""
    if len(encoded) > maximum:
        return ""
    return value


def _preparation_result(
    *,
    outcome: str,
    workspace_identity: object = "",
    repository: object = "",
    requested_ref: object = "",
    resolved_ref: object = "",
    exact_sha: object = "",
    mode: object = "branch",
    path: object = "",
    clean: bool = False,
    reused: bool = False,
    locked: bool = False,
    side_effect_state: str = "no-creation-attempted",
    reason: object = "",
) -> WorkspacePreparationResult:
    """Construct one finite, bounded, sanitized preparation result."""
    if outcome not in _PREPARATION_OUTCOMES:
        raise GitWorktreeAdapterError("invalid preparation outcome")
    if side_effect_state not in _PREPARATION_SIDE_EFFECTS:
        raise GitWorktreeAdapterError("invalid preparation side-effect state")
    safe_mode = mode if isinstance(mode, str) and mode in _PREPARATION_MODES else "branch"
    safe_sha = exact_sha if isinstance(exact_sha, str) and _SHA40.fullmatch(exact_sha) else ""
    safe_reason = _reason(reason if isinstance(reason, str) else "bounded preparation failure")
    return WorkspacePreparationResult(
        outcome=outcome,
        workspace_identity=_safe_result_text(workspace_identity),
        repository=_safe_result_text(repository),
        requested_ref=_safe_result_text(requested_ref),
        resolved_ref=_safe_result_text(resolved_ref),
        exact_sha=safe_sha,
        mode=safe_mode,
        path=_safe_result_text(path),
        clean=bool(clean),
        reused=bool(reused),
        locked=bool(locked),
        side_effect_state=side_effect_state,
        reason=safe_reason,
    )


def _absolute(value: str | os.PathLike[str], name: str) -> str:
    raw = os.fspath(value)
    _text(raw, name)
    normalized = os.path.abspath(os.path.normpath(raw))
    if not os.path.isabs(raw) or raw != normalized or not os.path.isdir(raw):
        raise GitWorktreeAdapterError(
            f"{name} must be an existing normalized absolute directory"
        )
    return raw


def _branch_ref(branch: str) -> str:
    return branch if branch.startswith("refs/heads/") else f"refs/heads/{branch}"


def _branch_name(ref: str | None) -> str:
    return "" if ref is None else ref.removeprefix("refs/heads/")


def _parse_porcelain(text: str) -> tuple[_Record, ...]:
    if not isinstance(text, str):
        raise GitWorktreeAdapterError("worktree porcelain must be text")
    records: list[_Record] = []
    current: dict[str, str] = {}

    def finish() -> None:
        nonlocal current
        if not current:
            return
        if len(records) >= MAX_RECORDS:
            raise GitWorktreeAdapterError("worktree record count exceeded")
        if not {"worktree", "HEAD"}.issubset(current):
            raise GitWorktreeAdapterError("worktree record is missing required fields")
        if sum(key in current for key in ("branch", "detached", "bare")) != 1:
            raise GitWorktreeAdapterError("worktree checkout mode is ambiguous")
        path, head = current["worktree"], current["HEAD"]
        if not os.path.isabs(path) or os.path.abspath(os.path.normpath(path)) != path:
            raise GitWorktreeAdapterError(
                "worktree path is not normalized and absolute"
            )
        if not _SHA40.fullmatch(head):
            raise GitWorktreeAdapterError("worktree HEAD is malformed")
        if any(item.path == path for item in records):
            raise GitWorktreeAdapterError("worktree path record is duplicated")
        records.append(
            _Record(
                path=path,
                head=head,
                branch=current.get("branch"),
                detached="detached" in current,
                bare="bare" in current,
                locked="locked" in current,
                lock_reason=current.get("locked", ""),
                prunable="prunable" in current,
                prunable_reason=current.get("prunable", ""),
            )
        )
        current = {}

    for token in text.split("\x00"):
        if token == "":
            finish()
            continue
        key, separator, value = token.partition(" ")
        if key not in _FIELDS:
            raise GitWorktreeAdapterError(
                "worktree record contains an unsupported field"
            )
        if key in current:
            raise GitWorktreeAdapterError(
                "worktree record contains a duplicate field"
            )
        if key in {"detached", "bare"}:
            if separator:
                raise GitWorktreeAdapterError(
                    "worktree flag has an unexpected value"
                )
            current[key] = ""
        elif separator:
            current[key] = value
        elif key in {"locked", "prunable"}:
            current[key] = ""
        else:
            raise GitWorktreeAdapterError("worktree field is missing a value")
    finish()
    return tuple(records)


def _cleanup_result(
    filesystem_removed: bool,
    metadata_removed: bool,
    path_absent: bool,
    reason: str = "",
) -> WorkspaceCleanup:
    return WorkspaceCleanup(
        filesystem_removed=filesystem_removed,
        metadata_removed=metadata_removed,
        path_absent=path_absent,
        force_required=False,
        reason=reason,
    )


class GitWorktreeAdapter:
    def __init__(
        self,
        *,
        repository_root: str | os.PathLike[str],
        workspace_parent: str | os.PathLike[str],
        repository_identity: RepositoryIdentity,
        runner: GitRunner | None = None,
        git_binary: str = "git",
        timeout_seconds: float = MAX_GIT_TIMEOUT_SECONDS,
        max_output_bytes: int = MAX_GIT_OUTPUT_BYTES,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._root = _absolute(repository_root, "repository_root")
        self._parent = _absolute(workspace_parent, "workspace_parent")
        if not isinstance(repository_identity, RepositoryIdentity):
            raise GitWorktreeAdapterError(
                "repository_identity must be RepositoryIdentity"
            )
        selected_runner = runner or PosixGitRunner()
        if not isinstance(selected_runner, GitRunner):
            raise GitWorktreeAdapterError("runner does not satisfy GitRunner")
        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds, (int, float)
        ):
            raise GitWorktreeAdapterError("timeout_seconds must be numeric")
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or not 0 < timeout <= MAX_GIT_TIMEOUT_SECONDS:
            raise GitWorktreeAdapterError(
                "timeout_seconds exceeds the bounded policy"
            )
        if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int):
            raise GitWorktreeAdapterError("max_output_bytes must be an integer")
        if not 0 < max_output_bytes <= MAX_GIT_OUTPUT_BYTES:
            raise GitWorktreeAdapterError(
                "max_output_bytes exceeds the bounded policy"
            )
        controlled = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": self._root,
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
        if environment is not None:
            if len(environment) > MAX_ENV_ITEMS:
                raise GitWorktreeAdapterError("environment item count exceeded")
            for key, value in environment.items():
                if not isinstance(key, str) or not isinstance(value, str) or "=" in key:
                    raise GitWorktreeAdapterError("environment is malformed")
                if key in controlled:
                    raise GitWorktreeAdapterError(
                        "protected environment values cannot be overridden"
                    )
                _text(key, "environment key")
                if value:
                    _text(value, "environment value")
                controlled[key] = value
        size = sum(
            len(key.encode("utf-8")) + len(value.encode("utf-8"))
            for key, value in controlled.items()
        )
        if size > MAX_ENV_BYTES:
            raise GitWorktreeAdapterError("environment byte budget exceeded")
        self._identity = repository_identity
        self._runner = selected_runner
        self._git = _text(git_binary, "git_binary")
        self._timeout = timeout
        self._output = max_output_bytes
        self._env = controlled
        self._create_attempted = False
        self._binding: _Binding | None = None

    @property
    def workspace_path(self) -> str | None:
        return None if self._binding is None else self._binding.path

    def _run(self, *args: str, cwd: str | None = None) -> GitObservation:
        try:
            result = self._runner.run(
                (self._git, *args),
                cwd=cwd or self._root,
                env=self._env,
                timeout_seconds=self._timeout,
                max_output_bytes=self._output,
            )
        except (TypeError, ValueError, RuntimeError, OSError) as exc:
            return GitObservation(
                started=False,
                return_code=None,
                timed_out=False,
                termination_confirmed=False,
                reason=f"Git runner failed: {type(exc).__name__}",
            )
        if isinstance(result, GitObservation):
            return result
        return GitObservation(
            started=False,
            return_code=None,
            timed_out=False,
            termination_confirmed=False,
            reason="Git runner returned unsupported evidence",
        )

    def _records(self) -> tuple[_Record, ...]:
        result = self._run(
            "-C", self._root, "worktree", "list", "--porcelain", "-z"
        )
        if not result.succeeded:
            raise GitWorktreeAdapterError(
                _reason(result.reason or "Git inspection failed")
            )
        return _parse_porcelain(result.stdout)

    def _preparation_identity(self, request: WorkspacePreparationRequest) -> str:
        """Stable identity for the logical preparation request."""
        return "prep-workspace:" + hashlib.sha256(
            f"agent-os-prep-v1:{request.repository.lower()}:{request.workspace_request_id}".encode(
                "utf-8"
            )
        ).hexdigest()

    @staticmethod
    def _preparation_contract_fingerprint(
        *, mode: str, requested_ref: str, resolved_ref: str, exact_sha: str
    ) -> str:
        payload = json.dumps(
            {
                "exact_sha": exact_sha,
                "mode": mode,
                "requested_ref": requested_ref,
                "resolved_ref": resolved_ref,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _bind_preparation(
        self, request: WorkspacePreparationRequest
    ) -> tuple[str, str, str, str]:
        if not isinstance(request, WorkspacePreparationRequest):
            raise TypeError("request must be WorkspacePreparationRequest")
        expected_repo = f"{self._identity.owner}/{self._identity.repository}".lower()
        repository = _text(request.repository, "repository")
        if repository.lower() != expected_repo:
            raise GitWorktreeAdapterError("repository identity mismatch")
        workspace_request_id = _text(
            request.workspace_request_id, "workspace_request_id"
        )
        ref = _text(request.requested_ref, "requested_ref")
        if ref.startswith("refs/"):
            raise GitWorktreeAdapterError(
                "requested_ref must use the canonical short name"
            )
        if not isinstance(request.mode, str) or request.mode not in _PREPARATION_MODES:
            raise GitWorktreeAdapterError("invalid preparation mode")
        if not isinstance(request.expected_revision, str) or not _SHA40.fullmatch(
            request.expected_revision
        ):
            raise GitWorktreeAdapterError(
                "expected_revision must be a full lowercase SHA"
            )
        if request.mode == "detached-sha" and not _SHA40.fullmatch(ref):
            raise GitWorktreeAdapterError(
                "detached-sha mode requires a full lowercase 40-character SHA as requested_ref"
            )

        identity = self._preparation_identity(request)
        suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        path = os.path.normpath(os.path.join(self._parent, f"agent-os-prep-{suffix}"))
        _text(path, "worktree path")
        if not os.path.isabs(path) or path != os.path.abspath(path):
            raise GitWorktreeAdapterError("path is not absolute and normalized")
        parent_abs = os.path.abspath(self._parent)
        if os.path.commonpath((parent_abs, path)) != parent_abs or path == parent_abs:
            raise GitWorktreeAdapterError("path escape detected")
        if os.path.islink(path) or os.path.islink(os.path.dirname(path)):
            raise GitWorktreeAdapterError("symlink detected in worktree path")

        if request.mode == "branch":
            resolve_ref = f"refs/heads/{ref}"
        elif request.mode == "tag":
            resolve_ref = f"refs/tags/{ref}"
        else:
            resolve_ref = ref
        return identity, path, ref, resolve_ref

    @staticmethod
    def _preparation_binding(
        request: WorkspacePreparationRequest,
        *,
        identity: str,
        path: str,
        requested_ref: str,
        resolve_ref: str,
        exact_sha: str,
        lock_reason: str,
    ) -> _Binding:
        return _Binding(
            request=WorkspaceRequest(
                workspace_request_id=request.workspace_request_id,
                repository=request.repository,
                branch=requested_ref,
                expected_revision=exact_sha,
            ),
            identity=identity,
            path=path,
            branch_ref=resolve_ref if request.mode == "branch" else "",
            lock_reason=lock_reason,
            detached=request.mode != "branch",
        )

    def prepare(
        self, request: WorkspacePreparationRequest
    ) -> WorkspacePreparationResult:
        if self._create_attempted:
            raise RuntimeError("worktree creation may be attempted at most once")
        self._create_attempted = True

        side_effect_state = "no-creation-attempted"
        if not isinstance(request, WorkspacePreparationRequest):
            return _preparation_result(
                outcome="blocked",
                reason="request must be WorkspacePreparationRequest",
                side_effect_state=side_effect_state,
            )
        try:
            identity, path, requested_ref, resolve_ref = self._bind_preparation(request)
        except (GitWorktreeAdapterError, TypeError, ValueError) as exc:
            return _preparation_result(
                outcome="blocked",
                repository=request.repository,
                requested_ref=request.requested_ref,
                mode=request.mode,
                reason=_reason(exc),
                side_effect_state=side_effect_state,
            )

        if request.mode in ("branch", "tag"):
            valid_ref = self._run("check-ref-format", resolve_ref)
            if not valid_ref.succeeded:
                return _preparation_result(
                    outcome="blocked",
                    workspace_identity=identity,
                    repository=request.repository,
                    requested_ref=requested_ref,
                    resolved_ref=resolve_ref,
                    mode=request.mode,
                    path=path,
                    reason="requested ref is not an exact valid Git ref",
                    side_effect_state=side_effect_state,
                )
            exact_ref = self._run(
                "-C", self._root, "show-ref", "--verify", "--hash", resolve_ref
            )
            ref_object = exact_ref.stdout.strip() if exact_ref.succeeded else ""
            if not exact_ref.succeeded or not _SHA40.fullmatch(ref_object):
                return _preparation_result(
                    outcome="unavailable",
                    workspace_identity=identity,
                    repository=request.repository,
                    requested_ref=requested_ref,
                    resolved_ref=resolve_ref,
                    mode=request.mode,
                    path=path,
                    reason="requested exact ref is unresolved",
                    side_effect_state=side_effect_state,
                )

        resolved = self._run(
            "-C", self._root, "rev-parse", "--verify", f"{resolve_ref}^{{commit}}"
        )
        actual_sha = resolved.stdout.strip() if resolved.succeeded else ""
        if not resolved.succeeded or not _SHA40.fullmatch(actual_sha):
            return _preparation_result(
                outcome="unavailable",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref=resolve_ref,
                mode=request.mode,
                path=path,
                reason="could not resolve ref to an exact commit",
                side_effect_state=side_effect_state,
            )
        if actual_sha != request.expected_revision:
            return _preparation_result(
                outcome="manual-review",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref=resolve_ref,
                exact_sha=actual_sha,
                mode=request.mode,
                path=path,
                reason="revision mismatch or tag movement detected",
                side_effect_state=side_effect_state,
            )

        fingerprint = self._preparation_contract_fingerprint(
            mode=request.mode,
            requested_ref=requested_ref,
            resolved_ref=resolve_ref,
            exact_sha=actual_sha,
        )
        lock_prefix = f"agent-os:{identity}:"
        lock_reason = f"{lock_prefix}{fingerprint}"

        try:
            records = self._records()
        except GitWorktreeAdapterError as exc:
            return _preparation_result(
                outcome="unavailable",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref=resolve_ref,
                exact_sha=actual_sha,
                mode=request.mode,
                path=path,
                reason=_reason(exc),
                side_effect_state=side_effect_state,
            )

        path_matches = tuple(record for record in records if record.path == path)
        identity_matches = tuple(
            record for record in records if record.lock_reason.startswith(lock_prefix)
        )
        branch_matches = (
            tuple(record for record in records if record.branch == resolve_ref)
            if request.mode == "branch"
            else ()
        )
        if len(path_matches) > 1 or len(identity_matches) > 1:
            return _preparation_result(
                outcome="blocked",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref=resolve_ref,
                exact_sha=actual_sha,
                mode=request.mode,
                path=path,
                reason="duplicate path or logical identity metadata detected",
                side_effect_state=side_effect_state,
            )
        existing_by_path = path_matches[0] if path_matches else None
        existing_by_identity = identity_matches[0] if identity_matches else None

        if existing_by_identity and existing_by_identity.path != path:
            return _preparation_result(
                outcome="blocked",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref=resolve_ref,
                exact_sha=actual_sha,
                mode=request.mode,
                path=path,
                locked=existing_by_identity.locked,
                reason="logical identity is bound to a different worktree path",
                side_effect_state=side_effect_state,
            )
        if existing_by_path and existing_by_path.lock_reason.startswith(lock_prefix):
            if existing_by_path.lock_reason != lock_reason:
                return _preparation_result(
                    outcome="manual-review",
                    workspace_identity=identity,
                    repository=request.repository,
                    requested_ref=requested_ref,
                    resolved_ref=resolve_ref,
                    exact_sha=actual_sha,
                    mode=request.mode,
                    path=path,
                    locked=existing_by_path.locked,
                    reason="logical request conflicts with the prepared ref, mode, or SHA",
                    side_effect_state=side_effect_state,
                )
        elif existing_by_path:
            return _preparation_result(
                outcome="blocked",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref=resolve_ref,
                exact_sha=actual_sha,
                mode=request.mode,
                path=path,
                locked=existing_by_path.locked,
                reason="path conflict: existing worktree has different lock ownership",
                side_effect_state=side_effect_state,
            )

        if request.mode == "branch" and any(
            record.path != path for record in branch_matches
        ):
            return _preparation_result(
                outcome="blocked",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref=resolve_ref,
                exact_sha=actual_sha,
                mode=request.mode,
                path=path,
                reason="branch is already claimed by another worktree",
                side_effect_state=side_effect_state,
            )

        if existing_by_path:
            existing = existing_by_path
            reason = "path collision, dirty state, or metadata conflict"
            mode_match = (
                not existing.detached
                if request.mode == "branch"
                else existing.detached
            )
            ref_match = (
                existing.branch == resolve_ref
                if request.mode == "branch"
                else existing.lock_reason == lock_reason
            )
            if (
                mode_match
                and existing.head == actual_sha
                and ref_match
                and existing.locked
                and existing.lock_reason == lock_reason
                and not existing.prunable
            ):
                status = self._run(
                    "-C",
                    path,
                    "status",
                    "--porcelain=v1",
                    "-z",
                    "--untracked-files=all",
                )
                clean = status.succeeded and status.stdout == ""
                if not clean:
                    reason = "worktree is dirty or status inspection was unresolved"
                if clean:
                    self._binding = self._preparation_binding(
                        request,
                        identity=identity,
                        path=path,
                        requested_ref=requested_ref,
                        resolve_ref=resolve_ref,
                        exact_sha=actual_sha,
                        lock_reason=lock_reason,
                    )
                    try:
                        valid = self._canonical_valid(
                            self._binding,
                            _branch_name(existing.branch),
                            actual_sha,
                            True,
                        )
                    except (TypeError, ValueError, RuntimeError) as exc:
                        valid = False
                        reason = f"canonical validation failed: {type(exc).__name__}"
                    else:
                        reason = "" if valid else "canonical validation failed"
                    if valid:
                        return _preparation_result(
                            outcome="already-prepared",
                            workspace_identity=identity,
                            repository=request.repository,
                            requested_ref=requested_ref,
                            resolved_ref=resolve_ref,
                            exact_sha=actual_sha,
                            mode=request.mode,
                            path=path,
                            clean=True,
                            reused=True,
                            locked=True,
                            side_effect_state="verified-reused",
                        )
                    self._binding = None
            else:
                reason = "path collision, dirty state, or metadata conflict"
            return _preparation_result(
                outcome="blocked",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref=resolve_ref,
                exact_sha=actual_sha,
                mode=request.mode,
                path=path,
                locked=existing.locked and existing.lock_reason == lock_reason,
                reason=reason,
                side_effect_state=side_effect_state,
            )

        if os.path.lexists(path):
            return _preparation_result(
                outcome="blocked",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref=resolve_ref,
                exact_sha=actual_sha,
                mode=request.mode,
                path=path,
                reason="path exists on disk but is not a registered worktree",
                side_effect_state=side_effect_state,
            )

        side_effect_state = "creation-attempted-no-workspace"
        add_args = [
            "-C",
            self._root,
            "worktree",
            "add",
            "--lock",
            "--reason",
            lock_reason,
        ]
        if request.mode == "branch":
            # Git attaches an existing branch only when given its canonical short
            # branch name. Exact full-ref validation and post-create inspection
            # prevent a same-name tag from changing the selected branch.
            checkout_target = requested_ref
        else:
            add_args.append("--detach")
            checkout_target = actual_sha
        add_args.extend([path, checkout_target])

        added = self._run(*add_args)
        path_exists = os.path.lexists(path)
        post_records: tuple[_Record, ...] = ()
        metadata_reason = ""
        try:
            post_records = self._records()
        except GitWorktreeAdapterError as exc:
            metadata_reason = f"post-creation metadata inspection failed: {type(exc).__name__}"
        partial_matches = tuple(record for record in post_records if record.path == path)
        partial_record = partial_matches[0] if len(partial_matches) == 1 else None
        if path_exists or partial_matches:
            side_effect_state = "partial-creation-observed"
        partial_locked = bool(
            partial_record
            and partial_record.locked
            and partial_record.lock_reason == lock_reason
        )
        partial_safe = bool(
            partial_record
            and partial_locked
            and partial_record.head == actual_sha
            and partial_record.detached == (request.mode != "branch")
            and (
                request.mode != "branch" or partial_record.branch == resolve_ref
            )
        )
        if partial_safe:
            self._binding = self._preparation_binding(
                request,
                identity=identity,
                path=path,
                requested_ref=requested_ref,
                resolve_ref=resolve_ref,
                exact_sha=actual_sha,
                lock_reason=lock_reason,
            )

        if not added.succeeded:
            return _preparation_result(
                outcome="unavailable",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref=resolve_ref,
                exact_sha=actual_sha,
                mode=request.mode,
                path=path,
                locked=partial_locked,
                reason=metadata_reason
                or _reason(added.reason or "worktree addition failed"),
                side_effect_state=side_effect_state,
            )

        fail_reason = metadata_reason
        record = partial_record
        identity_after = tuple(
            candidate
            for candidate in post_records
            if candidate.lock_reason.startswith(lock_prefix)
        )
        branch_after = (
            tuple(candidate for candidate in post_records if candidate.branch == resolve_ref)
            if request.mode == "branch"
            else ()
        )
        if not fail_reason:
            if len(partial_matches) != 1:
                fail_reason = "worktree metadata missing or duplicated after creation"
            elif record is None:
                fail_reason = "worktree metadata missing after creation"
            elif record.head != actual_sha:
                fail_reason = "worktree HEAD did not match the exact requested SHA"
            elif record.detached != (request.mode != "branch"):
                fail_reason = "worktree checkout mode did not match the request"
            elif request.mode == "branch" and record.branch != resolve_ref:
                fail_reason = "worktree branch did not match the exact requested ref"
            elif not (record.locked and record.lock_reason == lock_reason):
                fail_reason = "worktree lock ownership did not match the request"
            elif record.prunable:
                fail_reason = "worktree metadata is prunable"
            elif len(identity_after) != 1 or identity_after[0].path != path:
                fail_reason = "logical identity metadata conflicted after creation"
            elif request.mode == "branch" and (
                len(branch_after) != 1 or branch_after[0].path != path
            ):
                fail_reason = "branch ownership conflicted after creation"

        if not fail_reason:
            status = self._run(
                "-C",
                path,
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            )
            if not (status.succeeded and status.stdout == ""):
                fail_reason = "worktree is dirty after creation"

        if not fail_reason:
            self._binding = self._preparation_binding(
                request,
                identity=identity,
                path=path,
                requested_ref=requested_ref,
                resolve_ref=resolve_ref,
                exact_sha=actual_sha,
                lock_reason=lock_reason,
            )
            try:
                valid = self._canonical_valid(
                    self._binding,
                    _branch_name(record.branch if record else None),
                    actual_sha,
                    True,
                )
            except (TypeError, ValueError, RuntimeError) as exc:
                valid = False
                fail_reason = f"canonical validation failed: {type(exc).__name__}"
            else:
                fail_reason = "" if valid else "canonical validation failed"
            if valid:
                return _preparation_result(
                    outcome="prepared",
                    workspace_identity=identity,
                    repository=request.repository,
                    requested_ref=requested_ref,
                    resolved_ref=resolve_ref,
                    exact_sha=actual_sha,
                    mode=request.mode,
                    path=path,
                    clean=True,
                    reused=False,
                    locked=True,
                    side_effect_state="verified-prepared",
                )
            self._binding = None

        if partial_safe and self._binding is None:
            self._binding = self._preparation_binding(
                request,
                identity=identity,
                path=path,
                requested_ref=requested_ref,
                resolve_ref=resolve_ref,
                exact_sha=actual_sha,
                lock_reason=lock_reason,
            )
        return _preparation_result(
            outcome="unavailable",
            workspace_identity=identity,
            repository=request.repository,
            requested_ref=requested_ref,
            resolved_ref=resolve_ref,
            exact_sha=actual_sha,
            mode=request.mode,
            path=path,
            locked=partial_locked,
            reason=fail_reason or "post-creation verification failed",
            side_effect_state=side_effect_state,
        )

    def _bind_request(self, request: WorkspaceRequest) -> tuple[str, str, str]:
        if not isinstance(request, WorkspaceRequest):
            raise TypeError("request must be WorkspaceRequest")
        expected_repo = f"{self._identity.owner}/{self._identity.repository}".lower()
        if _text(request.repository, "repository").lower() != expected_repo:
            raise GitWorktreeAdapterError("repository identity mismatch")
        branch = _text(request.branch, "branch")
        if branch.startswith("refs/"):
            raise GitWorktreeAdapterError("branch must use the canonical short name")
        if not _SHA40.fullmatch(request.expected_revision):
            raise GitWorktreeAdapterError(
                "expected_revision must be a full lowercase SHA"
            )
        _text(request.workspace_request_id, "workspace_request_id")
        identity = pilot_workspace_identity(request)
        suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        path = os.path.join(self._parent, f"agent-os-worktree-{suffix}")
        if len(path.encode("utf-8")) > MAX_TEXT_BYTES:
            raise GitWorktreeAdapterError("derived worktree path exceeded")
        return identity, path, branch

    def create(self, request: WorkspaceRequest) -> WorkspaceHandle:
        if self._create_attempted:
            raise RuntimeError("worktree creation may be attempted at most once")
        self._create_attempted = True
        identity, path, branch = self._bind_request(request)
        if not self._run("check-ref-format", "--branch", branch).succeeded:
            return WorkspaceHandle(
                created=False,
                workspace_identity=identity,
                reason="requested branch is invalid",
            )
        resolved = self._run(
            "-C",
            self._root,
            "rev-parse",
            "--verify",
            f"{branch}^{{commit}}",
        )
        sha = resolved.stdout.strip() if resolved.succeeded else ""
        if not _SHA40.fullmatch(sha):
            return WorkspaceHandle(
                created=False,
                workspace_identity=identity,
                reason="requested branch is unresolved",
            )
        if sha != request.expected_revision:
            return WorkspaceHandle(
                created=False,
                workspace_identity=identity,
                reason="requested branch revision drifted",
            )
        try:
            records = self._records()
        except GitWorktreeAdapterError as exc:
            return WorkspaceHandle(
                created=False,
                workspace_identity=identity,
                reason=_reason(exc),
            )
        branch_ref = _branch_ref(branch)
        if os.path.lexists(path) or any(
            record.path == path or record.branch == branch_ref for record in records
        ):
            return WorkspaceHandle(
                created=False,
                workspace_identity=identity,
                reason="worktree path or branch is already in use",
            )
        lock_reason = _reason(f"agent-os:{identity}")
        added = self._run(
            "-C",
            self._root,
            "worktree",
            "add",
            "--lock",
            "--reason",
            lock_reason,
            path,
            branch,
        )
        if not added.succeeded:
            partial = os.path.lexists(path)
            try:
                partial = partial or any(
                    record.path == path for record in self._records()
                )
            except GitWorktreeAdapterError:
                partial = True
            if not partial:
                return WorkspaceHandle(
                    created=False,
                    workspace_identity=identity,
                    reason=_reason(added.reason or "creation failed"),
                )
        self._binding = _Binding(
            request=request,
            identity=identity,
            path=path,
            branch_ref=branch_ref,
            lock_reason=lock_reason,
            detached=False,
        )
        return WorkspaceHandle(
            created=True,
            workspace_identity=identity,
            reason="" if added.succeeded else "partial creation state",
        )

    def _bound(self, handle: WorkspaceHandle) -> _Binding:
        if not isinstance(handle, WorkspaceHandle):
            raise TypeError("handle must be WorkspaceHandle")
        if self._binding is None or not handle.created:
            raise GitWorktreeAdapterError("no created workspace is bound")
        if handle.workspace_identity != self._binding.identity:
            raise GitWorktreeAdapterError("workspace identity mismatch")
        return self._binding

    def _canonical_valid(
        self, binding: _Binding, branch: str, head: str, clean: bool
    ) -> bool:
        evidence = RepositoryStateEvidence(
            schema_name=CAPABILITY_EVIDENCE_SCHEMA_NAME,
            evidence_schema_version=CAPABILITY_EVIDENCE_SCHEMA_VERSION,
            producer_adapter="agent-os-git-worktree-adapter",
            producer_adapter_version="1.0",
            correlation_id=binding.identity,
            repository_identity=self._identity,
            base_ref=binding.request.branch,
            base_sha=binding.request.expected_revision,
            head_ref=branch,
            head_sha=head,
            requested_ref=binding.request.branch,
            requested_sha=binding.request.expected_revision,
            observed_sha=head,
            tested_sha=head,
            pushed_sha=None,
            proposed_pr_sha=None,
            synthetic_merge_sha=None,
            external_build_sha=None,
            evidence_type=RepositoryEvidenceType.BASE_SHA
            if binding.detached
            else RepositoryEvidenceType.BRANCH_HEAD,
            contract_fingerprint=hashlib.sha256(
                binding.identity.encode("utf-8")
            ).hexdigest(),
            worktree_state=WorktreeState.CLEAN if clean else WorktreeState.DIRTY,
            worktree_reason_codes=(),
            observed_at="single-inspection",
            freshness_boundary="single-inspection",
        )
        result = validate_repository_state_evidence(
            evidence,
            expected_repository=self._identity,
            expected_base_ref=binding.request.branch,
            expected_base_sha=binding.request.expected_revision,
            expected_head_ref=None if binding.detached else binding.request.branch,
            expected_head_sha=binding.request.expected_revision,
            expected_requested_sha=binding.request.expected_revision,
        )
        return result.outcome == "valid"

    def inspect(self, handle: WorkspaceHandle) -> WorkspaceInspection:
        binding = self._bound(handle)
        try:
            records = self._records()
        except GitWorktreeAdapterError as exc:
            return WorkspaceInspection(
                resolved=False,
                repository=binding.request.repository,
                branch="",
                expected_revision=binding.request.expected_revision,
                actual_revision="",
                clean=False,
                detached=False,
                reused="duplicate" in str(exc),
                locked=False,
                locked_expected=False,
                missing=not os.path.exists(binding.path),
                prunable=False,
                reason=_reason(exc),
            )
        matches = tuple(record for record in records if record.path == binding.path)
        reused = any(
            record.path != binding.path and record.branch == binding.branch_ref
            for record in records
        )
        if len(matches) != 1:
            return WorkspaceInspection(
                resolved=False,
                repository=binding.request.repository,
                branch="",
                expected_revision=binding.request.expected_revision,
                actual_revision="",
                clean=False,
                detached=False,
                reused=reused or len(matches) > 1,
                locked=False,
                locked_expected=False,
                missing=len(matches) == 0 or not os.path.exists(binding.path),
                prunable=False,
                reason="worktree metadata is missing or duplicated",
            )
        record = matches[0]
        exists = os.path.isdir(binding.path)
        branch = _branch_name(record.branch)
        status = self._run(
            "-C",
            binding.path,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            cwd=binding.path if exists else self._root,
        )
        clean = status.succeeded and status.stdout == ""
        locked_expected = record.locked and record.lock_reason == binding.lock_reason
        checks = (
            (not status.succeeded, "Git status inspection failed"),
            (not exists, "worktree filesystem path is missing"),
            (record.detached != binding.detached, "worktree detachment mismatch"),
            (record.bare, "worktree is bare"),
            (not binding.detached and record.branch != binding.branch_ref, "worktree branch drifted"),
            (
                record.head != binding.request.expected_revision,
                "worktree revision drifted",
            ),
            (record.prunable, "worktree metadata is prunable"),
            (not locked_expected, "worktree lock ownership drifted"),
            (not binding.detached and reused, "worktree branch is reused"),
        )
        reasons = [reason for failed, reason in checks if failed]
        try:
            canonical_valid = self._canonical_valid(
                binding, branch, record.head, clean
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            canonical_valid = False
            reasons.append(f"canonical validation failed: {type(exc).__name__}")
        if not canonical_valid:
            reasons.append("canonical repository-state validation did not pass")
        return WorkspaceInspection(
            resolved=not reasons,
            repository=binding.request.repository,
            branch=branch,
            expected_revision=binding.request.expected_revision,
            actual_revision=record.head,
            clean=clean,
            detached=record.detached,
            reused=reused,
            locked=record.locked,
            locked_expected=locked_expected,
            missing=not exists,
            prunable=record.prunable,
            reason=_reason("; ".join(reasons)),
        )

    def inspect_complete_state(
        self, handle: WorkspaceHandle, *, observation_kind: str
    ) -> "WorkspaceStateObservation":
        """Capture one complete workspace-state observation for the bound workspace.

        Reuses this adapter's own ``GitRunner``, root, and bounded process
        policy; no second Git runner or worktree manager is created.
        """
        from workflow_scheduler.execution.workspace_state_evidence import (
            inspect_complete_workspace_state,
        )

        binding = self._bound(handle)
        return inspect_complete_workspace_state(
            runner=self._runner,
            git_binary=self._git,
            repository_root=self._root,
            workspace_path=binding.path,
            repository_identity=self._identity,
            branch=_branch_name(binding.branch_ref) or binding.request.branch,
            expected_sha=binding.request.expected_revision,
            lock_identity=binding.lock_reason,
            observation_kind=observation_kind,
            environment=self._env,
            timeout_seconds=self._timeout,
            max_output_bytes=self._output,
        )

    def cleanup(self, handle: WorkspaceHandle) -> WorkspaceCleanup:
        binding = self._bound(handle)
        if binding.cleanup_attempted:
            raise RuntimeError("workspace cleanup may be attempted at most once")
        binding.cleanup_attempted = True
        existed = os.path.isdir(binding.path)
        try:
            records = self._records()
        except GitWorktreeAdapterError as exc:
            return _cleanup_result(
                False, False, not os.path.exists(binding.path), _reason(exc)
            )
        matches = tuple(record for record in records if record.path == binding.path)
        if len(matches) != 1:
            return _cleanup_result(
                False,
                False,
                not os.path.exists(binding.path),
                "bound metadata is missing or duplicated",
            )
        record = matches[0]
        if (
            record.head != binding.request.expected_revision
            or record.detached != binding.detached
            or (not binding.detached and record.branch != binding.branch_ref)
            or not record.locked
            or record.lock_reason != binding.lock_reason
        ):
            return _cleanup_result(
                False,
                False,
                not os.path.exists(binding.path),
                "identity or lock ownership diverged",
            )
        if existed:
            status = self._run(
                "-C",
                binding.path,
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                cwd=binding.path,
            )
            if not status.succeeded or status.stdout:
                return _cleanup_result(
                    False,
                    False,
                    False,
                    "refusing non-force cleanup of a dirty or unresolved worktree",
                )
        if not self._run(
            "-C", self._root, "worktree", "unlock", binding.path
        ).succeeded:
            return _cleanup_result(
                False,
                False,
                not os.path.exists(binding.path),
                "worktree unlock failed",
            )
        try:
            unlocked = tuple(
                record for record in self._records() if record.path == binding.path
            )
        except GitWorktreeAdapterError as exc:
            return _cleanup_result(
                False, False, not os.path.exists(binding.path), _reason(exc)
            )
        if (
            len(unlocked) != 1
            or unlocked[0].locked
            or unlocked[0].head != record.head
            or unlocked[0].branch != record.branch
        ):
            return _cleanup_result(
                False,
                False,
                not os.path.exists(binding.path),
                "identity changed after unlock",
            )
        removed = self._run(
            "-C", self._root, "worktree", "remove", binding.path
        )
        if not removed.succeeded:
            restored = self._run(
                "-C",
                self._root,
                "worktree",
                "lock",
                "--reason",
                binding.lock_reason,
                binding.path,
            )
            reason = (
                "worktree removal failed; lock ownership restored"
                if restored.succeeded
                else "worktree removal failed; lock ownership is unresolved"
            )
            return _cleanup_result(
                False, False, not os.path.exists(binding.path), reason
            )
        try:
            metadata_removed = not any(
                record.path == binding.path for record in self._records()
            )
        except GitWorktreeAdapterError as exc:
            return _cleanup_result(
                False, False, not os.path.exists(binding.path), _reason(exc)
            )
        path_absent = not os.path.exists(binding.path)
        filesystem_removed = existed and path_absent
        return _cleanup_result(
            filesystem_removed,
            metadata_removed,
            path_absent,
            ""
            if filesystem_removed and metadata_removed
            else "cleanup state remains divergent",
        )
