"""Governed ChatGPT Orchestrator -> Codespace command transport (#3333).

This module is the thin last-mile seam between an already-authorized ChatGPT
Orchestrator implementation mission and the current qualified Codespace. It
owns no routing, authorization, Scheduler, lease, or execution authority of its
own: it consumes the canonical #918 executor-routing decision (via the
caller's ``choose_governed_runner`` result), the Safe Implementation Lane
admission held by the caller, and the existing ``gh codespace ssh`` transport
pattern proven by the workflow-side Codespaces modules.

Trust domains, stated plainly:

- The *caller* is the already lane-authorized ChatGPT Orchestrator. The
  orchestrator composes the bounded command argv; the transport never invents
  commands.
- The *payload argv* is structured data (a tuple of strings), never a shell
  string. No shell is invoked at any point.
- GitHub-mutating commands are unreachable through this lane: ``git push`` and
  ``gh`` payload invocations are rejected with explicit reason-coded evidence
  before any transport occurs. Publication stays owned by the GitHub Service
  Agent through its existing governed paths.
- Codespaces remains a repository execution venue, not an Agent OS agent. This
  module performs no agent registration and creates no second #918 vocabulary.

All external effects are injected (``list_candidates`` / ``run``), so the
module is fully testable with fakes and performs no network or subprocess I/O
unless the caller supplies the default implementations.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Literal

REPOSITORY = "Blummer92/agent-os"
APPROVED_OWNER = "Blummer92"
REQUIRED_CODESPACE_STATE = "Available"
CODESPACE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,99}$", re.ASCII)
SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)

DEFAULT_TIMEOUT_SECONDS = 600
MAX_TIMEOUT_SECONDS = 3600
MAX_EVIDENCE_CHARS = 4096

SIDE_EFFECT_CLASSIFICATION = "repository-execution-only"


class TransportReason(str, Enum):
    """Reason-coded outcomes. Every terminal result carries at least one."""

    OK = "ok"
    NO_QUALIFIED_CODESPACE = "no-qualified-codespace"
    MULTIPLE_QUALIFIED_CODESPACES = "multiple-qualified-codespaces"
    CODESPACE_IDENTITY_MISMATCH = "codespace-identity-mismatch"
    INVALID_REQUEST = "invalid-request"
    FORBIDDEN_COMMAND = "forbidden-command"
    TRANSPORT_ERROR = "transport-error"
    TRANSPORT_TIMEOUT = "transport-timeout"


class TransportStatus(str, Enum):
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


def _bounded_text(value: str, *, limit: int = 256) -> str:
    if type(value) is not str or not value or len(value) > limit:
        raise ValueError("must be bounded non-empty text")
    if any(ch.isspace() for ch in value):
        raise ValueError("must not contain whitespace")
    return value


def _text_or_none(name: str, value: object, *, limit: int = 256) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or len(value) > limit:
        raise ValueError(f"{name} must be bounded text or none")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class CodespaceCandidate:
    """One observed Codespace, as returned by the injected lister."""

    name: str
    state: str
    repository_full_name: str
    owner_login: str

    def __post_init__(self) -> None:
        if type(self.name) is not str or CODESPACE_NAME_RE.fullmatch(self.name) is None:
            raise ValueError("name must match the Codespace identity pattern")
        for attr in ("state", "repository_full_name", "owner_login"):
            _bounded_text(getattr(self, attr))

    def is_qualified(self) -> bool:
        return (
            self.state == REQUIRED_CODESPACE_STATE
            and self.repository_full_name == REPOSITORY
            and self.owner_login == APPROVED_OWNER
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TransportRequest:
    """Bounded command request from the lane-authorized orchestrator."""

    repository: str
    issue_identity: str
    admission_id: str
    argv: tuple[str, ...]
    codespace_name_or_none: str | None = None
    base_sha_or_none: str | None = None
    workdir_or_none: str | None = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    request_id: str = ""

    def __post_init__(self) -> None:
        if self.repository != REPOSITORY:
            raise ValueError(f"repository must be {REPOSITORY}")
        _bounded_text(self.issue_identity)
        _bounded_text(self.admission_id)
        if type(self.argv) is not tuple or not self.argv:
            raise ValueError("argv must be a non-empty tuple of strings")
        for part in self.argv:
            if type(part) is not str or not part or "\x00" in part:
                raise ValueError("argv parts must be non-empty strings without NUL")
        name = self.codespace_name_or_none
        if name is not None and (
            type(name) is not str or CODESPACE_NAME_RE.fullmatch(name) is None
        ):
            raise ValueError("codespace_name_or_none must match the identity pattern")
        sha = self.base_sha_or_none
        if sha is not None and (type(sha) is not str or SHA40_RE.fullmatch(sha) is None):
            raise ValueError("base_sha_or_none must be a 40-hex SHA or none")
        _text_or_none("workdir_or_none", self.workdir_or_none, limit=512)
        if (
            type(self.timeout_seconds) is not int
            or self.timeout_seconds < 1
            or self.timeout_seconds > MAX_TIMEOUT_SECONDS
        ):
            raise ValueError("timeout_seconds must be within the bounded range")
        computed = transport_request_id(self)
        if self.request_id and self.request_id != computed:
            raise ValueError("request_id does not match request content")
        object.__setattr__(self, "request_id", computed)

    def to_dict(self) -> dict[str, object]:
        return {
            "repository": self.repository,
            "issue_identity": self.issue_identity,
            "admission_id": self.admission_id,
            "argv": list(self.argv),
            "codespace_name_or_none": self.codespace_name_or_none,
            "base_sha_or_none": self.base_sha_or_none,
            "workdir_or_none": self.workdir_or_none,
            "timeout_seconds": self.timeout_seconds,
            "request_id": self.request_id,
        }


def transport_request_id(request: TransportRequest) -> str:
    material = json.dumps(
        [
            request.repository,
            request.issue_identity,
            request.admission_id,
            list(request.argv),
            request.codespace_name_or_none,
            request.base_sha_or_none,
            request.workdir_or_none,
            request.timeout_seconds,
        ],
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(material).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class TransportResult:
    """Deterministic structured evidence for one transport invocation."""

    request_id: str
    status: TransportStatus
    reason_codes: tuple[TransportReason, ...]
    codespace_name_or_none: str | None
    argv: tuple[str, ...]
    workdir_or_none: str | None
    exit_status_or_none: int | None
    stdout_tail: str
    stderr_tail: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: int
    issue_identity: str
    base_sha_or_none: str | None
    side_effect_classification: str = SIDE_EFFECT_CLASSIFICATION
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    publication_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.request_id) is not str or not self.request_id:
            raise ValueError("request_id must be non-empty")
        if type(self.status) is not TransportStatus:
            raise TypeError("status must be an exact TransportStatus")
        if (
            type(self.reason_codes) is not tuple
            or not self.reason_codes
            or any(type(item) is not TransportReason for item in self.reason_codes)
        ):
            raise ValueError("reason_codes must be a non-empty tuple of TransportReason")
        name = self.codespace_name_or_none
        if name is not None and (
            type(name) is not str or CODESPACE_NAME_RE.fullmatch(name) is None
        ):
            raise ValueError("codespace_name_or_none must match the identity pattern")
        if type(self.argv) is not tuple or any(type(part) is not str for part in self.argv):
            raise ValueError("argv must be a tuple of strings")
        _text_or_none("workdir_or_none", self.workdir_or_none, limit=512)
        exit_status = self.exit_status_or_none
        if exit_status is not None and type(exit_status) is not int:
            raise ValueError("exit_status_or_none must be an int or none")
        for attr in ("stdout_tail", "stderr_tail"):
            value = getattr(self, attr)
            if type(value) is not str or len(value) > MAX_EVIDENCE_CHARS:
                raise ValueError(f"{attr} must be bounded text")
        for attr in ("stdout_truncated", "stderr_truncated"):
            if type(getattr(self, attr)) is not bool:
                raise ValueError(f"{attr} must be a bool")
        if type(self.duration_ms) is not int or self.duration_ms < 0:
            raise ValueError("duration_ms must be a non-negative int")
        _bounded_text(self.issue_identity)
        sha = self.base_sha_or_none
        if sha is not None and (type(sha) is not str or SHA40_RE.fullmatch(sha) is None):
            raise ValueError("base_sha_or_none must be a 40-hex SHA or none")
        if self.side_effect_classification != SIDE_EFFECT_CLASSIFICATION:
            raise ValueError("side_effect_classification is fixed")

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "status": self.status.value,
            "reason_codes": [item.value for item in self.reason_codes],
            "codespace_name_or_none": self.codespace_name_or_none,
            "argv": list(self.argv),
            "workdir_or_none": self.workdir_or_none,
            "exit_status_or_none": self.exit_status_or_none,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "duration_ms": self.duration_ms,
            "issue_identity": self.issue_identity,
            "base_sha_or_none": self.base_sha_or_none,
            "side_effect_classification": self.side_effect_classification,
            "github_writes_authorized": False,
            "execution_authorized": False,
            "publication_authorized": False,
            "merge_authorized": False,
        }


def _tail(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_EVIDENCE_CHARS:
        return text, False
    return text[-MAX_EVIDENCE_CHARS:], True


def resolve_current_codespace(
    candidates: tuple[CodespaceCandidate, ...],
) -> tuple[CodespaceCandidate | None, TransportReason]:
    """Apply the exactly-one-qualified-Codespace rule. Pure; no I/O."""
    if type(candidates) is not tuple or any(
        type(item) is not CodespaceCandidate for item in candidates
    ):
        raise TypeError("candidates must be a tuple of CodespaceCandidate")
    qualified = [item for item in candidates if item.is_qualified()]
    if not qualified:
        return None, TransportReason.NO_QUALIFIED_CODESPACE
    if len(qualified) > 1:
        return None, TransportReason.MULTIPLE_QUALIFIED_CODESPACES
    return qualified[0], TransportReason.OK


_FORBIDDEN_GH_SUBCOMMANDS = frozenset({
    "api",
    "auth",
    "cache",
    "codespace",
    "copilot",
    "extension",
    "gist",
    "issue",
    "pr",
    "project",
    "release",
    "repo",
    "run",
    "secret",
    "ssh-key",
    "variable",
    "workflow",
})


def validate_argv(argv: tuple[str, ...]) -> TransportReason | None:
    """Reject payload argv that could mutate GitHub or the Codespace fleet.

    Returns None when the argv is acceptable, else the rejecting reason.
    The transport never invokes a shell, so this is a tripwire over the
    structured argv — not a shell-escaping filter.
    """
    if type(argv) is not tuple or not argv:
        return TransportReason.INVALID_REQUEST
    if any(type(part) is not str or not part or "\x00" in part for part in argv):
        return TransportReason.INVALID_REQUEST
    head = argv[0]
    rest = argv[1:]
    if head == "git" and "push" in rest:
        return TransportReason.FORBIDDEN_COMMAND
    if head == "gh":
        # No gh payload invocations inside the Codespace: the lane performs
        # repository execution only. Even read-only gh subcommands are rejected
        # here because the gh surface is one flag away from mutation and the
        # orchestrator has no read need it cannot satisfy another way.
        return TransportReason.FORBIDDEN_COMMAND
    if head == "hub":
        return TransportReason.FORBIDDEN_COMMAND
    return None


def _failure(
    request: TransportRequest,
    status: TransportStatus,
    reason: TransportReason,
    codespace_name_or_none: str | None,
    duration_ms: int = 0,
) -> TransportResult:
    return TransportResult(
        request_id=request.request_id,
        status=status,
        reason_codes=(reason,),
        codespace_name_or_none=codespace_name_or_none,
        argv=request.argv,
        workdir_or_none=request.workdir_or_none,
        exit_status_or_none=None,
        stdout_tail="",
        stderr_tail="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=duration_ms,
        issue_identity=request.issue_identity,
        base_sha_or_none=request.base_sha_or_none,
    )


def default_list_candidates() -> tuple[CodespaceCandidate, ...]:
    """List Codespaces for the repository via the gh CLI. Network I/O."""
    completed = subprocess.run(
        ("gh", "api", f"repos/{REPOSITORY}/codespaces", "--paginate"),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"gh api codespaces failed: {completed.stderr[-500:]}")
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("gh api codespaces returned invalid JSON") from exc
    items = payload.get("codespaces", [])
    candidates: list[CodespaceCandidate] = []
    for item in items:
        try:
            candidates.append(
                CodespaceCandidate(
                    name=str(item["name"]),
                    state=str(item["state"]),
                    repository_full_name=str(
                        (item.get("repository") or {}).get("full_name", "")
                    ),
                    owner_login=str((item.get("owner") or {}).get("login", "")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(candidates)


def default_run(argv: tuple[str, ...], *, timeout_seconds: int) -> tuple[int, str, str]:
    """Run a local argv with a timeout. Subprocess I/O."""
    completed = subprocess.run(
        tuple(argv),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return completed.returncode, completed.stdout, completed.stderr


def run_codespace_transport(
    request: TransportRequest,
    *,
    list_candidates: Callable[[], tuple[CodespaceCandidate, ...]] = default_list_candidates,
    run: Callable[..., tuple[int, str, str]] = default_run,
) -> TransportResult:
    """Execute one bounded request on the current qualified Codespace.

    The payload argv is executed via ``gh codespace ssh`` with no shell. All
    external effects flow through the injected ``list_candidates`` and ``run``
    callables, which the test suite replaces with fakes.
    """
    if type(request) is not TransportRequest:
        raise TypeError("request must be an exact TransportRequest")

    forbidden = validate_argv(request.argv)
    if forbidden is not None:
        return _failure(request, TransportStatus.REJECTED, forbidden, None)

    try:
        candidates = list_candidates()
    except Exception:
        return _failure(
            request, TransportStatus.FAILED, TransportReason.TRANSPORT_ERROR, None
        )
    codespace, reason = resolve_current_codespace(candidates)
    if codespace is None:
        return _failure(request, TransportStatus.FAILED, reason, None)
    if (
        request.codespace_name_or_none is not None
        and request.codespace_name_or_none != codespace.name
    ):
        return _failure(
            request,
            TransportStatus.FAILED,
            TransportReason.CODESPACE_IDENTITY_MISMATCH,
            codespace.name,
        )

    ssh_argv = (
        "gh",
        "codespace",
        "ssh",
        "-c",
        codespace.name,
        "--",
        *request.argv,
    )
    started = time.monotonic()
    try:
        exit_status, stdout, stderr = run(ssh_argv, timeout_seconds=request.timeout_seconds)
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - started) * 1000)
        return _failure(
            request,
            TransportStatus.FAILED,
            TransportReason.TRANSPORT_TIMEOUT,
            codespace.name,
            duration_ms,
        )
    except Exception:
        duration_ms = int((time.monotonic() - started) * 1000)
        return _failure(
            request,
            TransportStatus.FAILED,
            TransportReason.TRANSPORT_ERROR,
            codespace.name,
            duration_ms,
        )
    duration_ms = int((time.monotonic() - started) * 1000)
    stdout_tail, stdout_truncated = _tail(stdout or "")
    stderr_tail, stderr_truncated = _tail(stderr or "")
    return TransportResult(
        request_id=request.request_id,
        status=TransportStatus.COMPLETED,
        reason_codes=(TransportReason.OK,),
        codespace_name_or_none=codespace.name,
        argv=request.argv,
        workdir_or_none=request.workdir_or_none,
        exit_status_or_none=exit_status,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        duration_ms=duration_ms,
        issue_identity=request.issue_identity,
        base_sha_or_none=request.base_sha_or_none,
    )
