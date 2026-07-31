"""Bounded, identity-bound Git worktree implementation of WorkspaceAdapter."""

from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable, Literal

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
    side_effect_state: str = ""
    reason: str = ""
    repository_implementation_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    github_writes_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)


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

    def _bind_preparation(
        self, request: WorkspacePreparationRequest
    ) -> tuple[str, str, str]:
        if not isinstance(request, WorkspacePreparationRequest):
            raise TypeError("request must be WorkspacePreparationRequest")
        expected_repo = f"{self._identity.owner}/{self._identity.repository}".lower()
        if _text(request.repository, "repository").lower() != expected_repo:
            raise GitWorktreeAdapterError("repository identity mismatch")
        ref = _text(request.requested_ref, "requested_ref")
        if ref.startswith("refs/"):
            raise GitWorktreeAdapterError("requested_ref must use the canonical short name")
        if not _SHA40.fullmatch(request.expected_revision):
            raise GitWorktreeAdapterError("expected_revision must be a full lowercase SHA")
        if request.mode not in ("branch", "tag", "detached-sha"):
            raise GitWorktreeAdapterError("invalid preparation mode")
        _text(request.workspace_request_id, "workspace_request_id")
        dummy = WorkspaceRequest(
            workspace_request_id=request.workspace_request_id,
            repository=request.repository,
            branch=request.requested_ref,
            expected_revision=request.expected_revision,
        )
        identity = pilot_workspace_identity(dummy)
        suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        path = os.path.normpath(os.path.join(self._parent, f"agent-os-prep-{suffix}"))
        if not os.path.isabs(path) or path != os.path.abspath(path):
            raise GitWorktreeAdapterError("path is not absolute and normalized")
        parent_abs = os.path.abspath(self._parent)
        if not path.startswith(parent_abs + os.sep):
            raise GitWorktreeAdapterError("path escape detected")
        if os.path.islink(path) or os.path.islink(os.path.dirname(path)):
            raise GitWorktreeAdapterError("symlink detected in worktree path")
        return identity, path, ref

    def prepare(
        self, request: WorkspacePreparationRequest
    ) -> WorkspacePreparationResult:
        if self._create_attempted:
            raise RuntimeError("worktree creation may be attempted at most once")
        self._create_attempted = True
        auth = {
            "repository_implementation_authorized": False,
            "execution_authorized": False,
            "github_writes_authorized": False,
            "merge_authorized": False,
        }
        try:
            identity, path, requested_ref = self._bind_preparation(request)
        except (GitWorktreeAdapterError, TypeError, ValueError) as exc:
            return WorkspacePreparationResult(
                outcome="blocked",
                workspace_identity="",
                repository=request.repository,
                requested_ref=request.requested_ref,
                resolved_ref="",
                exact_sha="",
                mode=request.mode,
                path="",
                clean=False,
                reused=False,
                locked=False,
                reason=_reason(exc),
            )

        if request.mode == "branch":
            resolve_ref = f"refs/heads/{requested_ref}"
            checkout_ref = requested_ref
        elif request.mode == "tag":
            resolve_ref = f"refs/tags/{requested_ref}"
            checkout_ref = requested_ref
        else:
            if not _SHA40.fullmatch(requested_ref):
                return WorkspacePreparationResult(
                    outcome="blocked",
                    workspace_identity=identity,
                    repository=request.repository,
                    requested_ref=requested_ref,
                    resolved_ref="",
                    exact_sha="",
                    mode=request.mode,
                    path=path,
                    clean=False,
                    reused=False,
                    locked=False,
                    reason="detached-sha mode requires a full lowercase 40-character SHA",
                )
            resolve_ref = requested_ref
            checkout_ref = requested_ref

        resolved = self._run("-C", self._root, "rev-parse", "--verify", f"{resolve_ref}^{{commit}}")
        actual_sha = resolved.stdout.strip() if resolved.succeeded else ""
        if not resolved.succeeded or not _SHA40.fullmatch(actual_sha):
            return WorkspacePreparationResult(
                outcome="unavailable",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref="",
                exact_sha="",
                mode=request.mode,
                path=path,
                clean=False,
                reused=False,
                locked=False,
                reason="could not resolve ref to an exact commit",
            )
        if actual_sha != request.expected_revision:
            return WorkspacePreparationResult(
                outcome="manual-review",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref=resolve_ref,
                exact_sha=actual_sha,
                mode=request.mode,
                path=path,
                clean=False,
                reused=False,
                locked=False,
                reason="revision mismatch or tag movement detected",
            )

        try:
            records = self._records()
        except GitWorktreeAdapterError as exc:
            return WorkspacePreparationResult(
                outcome="unavailable",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref=resolve_ref,
                exact_sha=actual_sha,
                mode=request.mode,
                path=path,
                clean=False,
                reused=False,
                locked=False,
                reason=_reason(exc),
            )

        lock_reason = _reason(f"agent-os:{identity}")
        existing = next((r for r in records if r.path == path), None)
        if existing:
            mode_match = (request.mode == "branch" and not existing.detached) or (
                request.mode in ("tag", "detached-sha") and existing.detached
            )
            head_match = existing.head == actual_sha
            ref_match = request.mode != "branch" or existing.branch == resolve_ref
            lock_match = existing.locked and existing.lock_reason == lock_reason
            if mode_match and head_match and ref_match and lock_match and not existing.prunable:
                status = self._run("-C", path, "status", "--porcelain=v1", "-z", "--untracked-files=all")
                clean = status.succeeded and status.stdout == ""
                if clean:
                    self._binding = _Binding(
                        request=WorkspaceRequest(
                            workspace_request_id=request.workspace_request_id,
                            repository=request.repository,
                            branch=requested_ref,
                            expected_revision=actual_sha,
                        ),
                        identity=identity,
                        path=path,
                        branch_ref=resolve_ref if request.mode == "branch" else "",
                        lock_reason=lock_reason,
                    )
                    return WorkspacePreparationResult(
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
                    )
            return WorkspacePreparationResult(
                outcome="blocked",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref=resolve_ref,
                exact_sha=actual_sha,
                mode=request.mode,
                path=path,
                clean=False,
                reused=False,
                locked=existing.locked,
                reason="path collision, dirty state, or metadata conflict",
            )

        if request.mode == "branch" and any(r.branch == resolve_ref for r in records):
            return WorkspacePreparationResult(
                outcome="blocked",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref=resolve_ref,
                exact_sha=actual_sha,
                mode=request.mode,
                path=path,
                clean=False,
                reused=False,
                locked=False,
                reason="branch is already claimed by another worktree",
            )

        add_args = ["-C", self._root, "worktree", "add", "--lock", "--reason", lock_reason]
        if request.mode != "branch":
            add_args.append("--detach")
        add_args.extend([path, checkout_ref])
        added = self._run(*add_args)
        if not added.succeeded:
            return WorkspacePreparationResult(
                outcome="unavailable",
                workspace_identity=identity,
                repository=request.repository,
                requested_ref=requested_ref,
                resolved_ref=resolve_ref,
                exact_sha=actual_sha,
                mode=request.mode,
                path=path,
                clean=False,
                reused=False,
                locked=False,
                reason=_reason(added.reason or "worktree addition failed"),
            )

        self._binding = _Binding(
            request=WorkspaceRequest(
                workspace_request_id=request.workspace_request_id,
                repository=request.repository,
                branch=requested_ref,
                expected_revision=actual_sha,
            ),
            identity=identity,
            path=path,
            branch_ref=resolve_ref if request.mode == "branch" else "",
            lock_reason=lock_reason,
        )
        return WorkspacePreparationResult(
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
            evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
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
            expected_head_ref=binding.request.branch,
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
            (record.detached, "worktree is detached"),
            (record.bare, "worktree is bare"),
            (record.branch != binding.branch_ref, "worktree branch drifted"),
            (
                record.head != binding.request.expected_revision,
                "worktree revision drifted",
            ),
            (record.prunable, "worktree metadata is prunable"),
            (not locked_expected, "worktree lock ownership drifted"),
            (reused, "worktree branch is reused"),
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
            or record.branch != binding.branch_ref
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
