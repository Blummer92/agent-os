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
- The *payload argv* is bounded structured data admitted by a finite command
  grammar. Local execution never invokes a shell; each admitted argument is
  quoted for SSH's remote command interpretation.
- The *working directory* is a deterministic contract, not a measurement
  (#3333 Option B): when bound, it must be exactly the validated repository
  root (``/workspaces/agent-os``); the transport pins the remote command under
  it and rejects any other value before any Codespace contact. ``None``
  preserves the historical recorded-only behavior.
- Shells, arbitrary interpreters, executable paths, GitHub clients and unknown
  command families are rejected before discovery or transport. Admitted tests
  remain trusted repository code, not a hostile-code sandbox. Publication stays
  owned by the GitHub Service Agent through its existing governed paths.
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
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Literal

from .codespace_command_policy import admitted_repository_argv, valid_argv_data

REPOSITORY = "Blummer92/agent-os"
APPROVED_OWNER = "Blummer92"
REQUIRED_CODESPACE_STATE = "Available"
#: Deterministic repository working directory for the Codespaces execution
#: path (#3333, Option B, owner-approved). The incidental non-interactive SSH
#: session directory is not measured; instead the transport pins execution
#: under this validated constant. It is the only admissible workdir value:
#: anything else is rejected before any Codespace is contacted.
VALIDATED_CODESPACE_REPOSITORY_ROOT = "/workspaces/agent-os"
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
    execution_profile_or_none: str | None = None
    environment_health_evidence_or_none: str | None = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    request_id: str = ""

    def __post_init__(self) -> None:
        if self.repository != REPOSITORY:
            raise ValueError(f"repository must be {REPOSITORY}")
        _bounded_text(self.issue_identity)
        _bounded_text(self.admission_id)
        if not valid_argv_data(self.argv):
            raise ValueError("argv must contain bounded non-empty strings without controls")
        name = self.codespace_name_or_none
        if name is not None and (
            type(name) is not str or CODESPACE_NAME_RE.fullmatch(name) is None
        ):
            raise ValueError("codespace_name_or_none must match the identity pattern")
        sha = self.base_sha_or_none
        if sha is not None and (type(sha) is not str or SHA40_RE.fullmatch(sha) is None):
            raise ValueError("base_sha_or_none must be a 40-hex SHA or none")
        _text_or_none("workdir_or_none", self.workdir_or_none, limit=512)
        _text_or_none("execution_profile_or_none", self.execution_profile_or_none)
        _text_or_none("environment_health_evidence_or_none", self.environment_health_evidence_or_none)
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
            "execution_profile_or_none": self.execution_profile_or_none,
            "environment_health_evidence_or_none": self.environment_health_evidence_or_none,
            "timeout_seconds": self.timeout_seconds,
            "request_id": self.request_id,
        }


def transport_request_id(request: TransportRequest) -> str:
    fields = [
        request.repository,
        request.issue_identity,
        request.admission_id,
        list(request.argv),
        request.codespace_name_or_none,
        request.base_sha_or_none,
        request.workdir_or_none,
        request.timeout_seconds,
    ]
    # Preserve existing no-profile identities; bind newly supplied canonical
    # runner evidence without rewriting earlier admitted request identities.
    if (request.execution_profile_or_none is not None
            or request.environment_health_evidence_or_none is not None):
        fields.extend([
            "runner-evidence", request.execution_profile_or_none,
            request.environment_health_evidence_or_none,
        ])
    material = json.dumps(
        fields,
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
    repository: str = REPOSITORY
    execution_surface: str = "codespaces"
    execution_profile_or_none: str | None = None
    environment_health_evidence_or_none: str | None = None
    started_at_or_none: str | None = None
    ended_at_or_none: str | None = None
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
        if self.repository != REPOSITORY or self.execution_surface != "codespaces":
            raise ValueError("repository and execution_surface are fixed")
        _text_or_none("execution_profile_or_none", self.execution_profile_or_none)
        _text_or_none("environment_health_evidence_or_none", self.environment_health_evidence_or_none)
        if (self.started_at_or_none is None) != (self.ended_at_or_none is None):
            raise ValueError("start/end evidence must be paired")
        for value in (self.started_at_or_none, self.ended_at_or_none):
            if value is not None:
                _text_or_none("execution timestamp", value, limit=40)
                stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                offset = stamp.utcoffset()
                if stamp.tzinfo is None or offset is None or offset.total_seconds() != 0:
                    raise ValueError("execution timestamps must be UTC")

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "status": self.status.value,
            "reason_codes": [item.value for item in self.reason_codes],
            "codespace_name_or_none": self.codespace_name_or_none,
            "argv": list(self.argv),
            "workdir_or_none": self.workdir_or_none,
            "repository": self.repository,
            "execution_surface": self.execution_surface,
            "execution_profile_or_none": self.execution_profile_or_none,
            "environment_health_evidence_or_none": self.environment_health_evidence_or_none,
            "exit_status_or_none": self.exit_status_or_none,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "duration_ms": self.duration_ms,
            "started_at_or_none": self.started_at_or_none,
            "ended_at_or_none": self.ended_at_or_none,
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


def validate_argv(argv: tuple[str, ...]) -> TransportReason | None:
    """Admit only finite repository command families before any external call."""
    if not valid_argv_data(argv):
        return TransportReason.INVALID_REQUEST
    if not admitted_repository_argv(argv):
        return TransportReason.FORBIDDEN_COMMAND
    return None


def _validate_workdir(workdir: object) -> TransportReason | None:
    """Enforce the deterministic working-directory contract (#3333 Option B).

    ``None`` preserves the historical recorded-only behavior for callers that
    bind no working directory. Any other value must be exactly the validated
    repository root; everything else is rejected before any Codespace contact.
    """
    if workdir is None:
        return None
    if type(workdir) is not str or workdir != VALIDATED_CODESPACE_REPOSITORY_ROOT:
        return TransportReason.INVALID_REQUEST
    return None


def _sh_single_quote(value: str) -> str:
    """POSIX-shell single-quote a fixed transport constant.

    Defense in depth for the deterministic working-directory contract: even
    though ``_validate_workdir`` admits only the exact validated constant, the
    value is always quoted at the splice point, so a future refactor that
    separates validation from use cannot open a shell-injection channel.
    """
    return "'" + value.replace("'", "'\\''") + "'"


#: Remote-side repository-identity gate, as fixed ssh argv words. The driver
#: cannot see the remote filesystem, so identity is asserted where the fixed
#: command runs: ``git rev-parse --show-toplevel`` (already-admitted grammar;
#: no allowlist widening) must report exactly the validated root. Any
#: mismatch -- wrong repository, subdirectory of another repository, or not a
#: git work tree at all -- fails the ``&&`` chain with a non-zero exit before
#: the fixed argv executes. Both sides of the comparison are validated
#: constants, never caller shell text.
def _identity_gate_words(quoted_root: str) -> tuple[str, ...]:
    return (
        "[",
        '"$(git rev-parse --show-toplevel)"',
        "=",
        quoted_root,
        "]",
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime) -> str:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError("execution clock must return UTC evidence")
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _failure(
    request: TransportRequest,
    status: TransportStatus,
    reason: TransportReason,
    codespace_name_or_none: str | None,
    duration_ms: int = 0,
    started_at_or_none: str | None = None,
    ended_at_or_none: str | None = None,
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
        execution_profile_or_none=request.execution_profile_or_none,
        environment_health_evidence_or_none=request.environment_health_evidence_or_none,
        started_at_or_none=started_at_or_none,
        ended_at_or_none=ended_at_or_none,
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
    utc_now: Callable[[], datetime] = _utc_now,
) -> TransportResult:
    """Execute one bounded request on the current qualified Codespace.

    Admitted argv is quoted for SSH; no caller shell string is accepted. All
    external effects flow through the injected ``list_candidates`` and ``run``
    callables, which the test suite replaces with fakes.
    """
    if type(request) is not TransportRequest:
        raise TypeError("request must be an exact TransportRequest")

    forbidden = validate_argv(request.argv)
    if forbidden is not None:
        return _failure(request, TransportStatus.REJECTED, forbidden, None)
    if _validate_workdir(request.workdir_or_none) is not None:
        return _failure(
            request, TransportStatus.REJECTED, TransportReason.INVALID_REQUEST, None
        )

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

    ssh_prefix = ("gh", "codespace", "ssh", "-c", codespace.name, "--")
    if request.workdir_or_none is not None:
        # Deterministic working-directory contract (#3333 Option B): the only
        # admissible workdir is the validated repository root. The remote
        # command is pinned under `cd '<root>' &&`, and repository identity
        # (not merely the directory path) is asserted on the remote side
        # before the fixed command runs: the identity gate requires
        # `git rev-parse --show-toplevel` to report exactly the validated
        # root. A missing directory, a non-git directory, or a different
        # repository fails the `&&` chain with a non-zero exit before the
        # fixed argv executes. Every word here is a validated constant or
        # fixed gate text, never caller shell text; the admitted argv is
        # unchanged and the command grammar is not widened.
        quoted_root = _sh_single_quote(request.workdir_or_none)
        ssh_argv = (
            *ssh_prefix,
            "cd",
            quoted_root,
            "&&",
            *_identity_gate_words(quoted_root),
            "&&",
            *(shlex.quote(part) for part in request.argv),
        )
    else:
        ssh_argv = (
            *ssh_prefix,
            *(shlex.quote(part) for part in request.argv),
        )
    started_at_or_none = _utc_text(utc_now())
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
            started_at_or_none,
            _utc_text(utc_now()),
        )
    except Exception:
        duration_ms = int((time.monotonic() - started) * 1000)
        return _failure(
            request,
            TransportStatus.FAILED,
            TransportReason.TRANSPORT_ERROR,
            codespace.name,
            duration_ms,
            started_at_or_none,
            _utc_text(utc_now()),
        )
    duration_ms = int((time.monotonic() - started) * 1000)
    ended_at_or_none = _utc_text(utc_now())
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
        execution_profile_or_none=request.execution_profile_or_none,
        environment_health_evidence_or_none=request.environment_health_evidence_or_none,
        started_at_or_none=started_at_or_none,
        ended_at_or_none=ended_at_or_none,
    )
