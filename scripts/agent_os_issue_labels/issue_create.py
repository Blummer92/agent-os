from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum, IntEnum
from typing import BinaryIO, Protocol
from urllib.parse import urlparse

from scripts.agent_os_issue_acceptance.models import Status

from .validation import IssueDraftValidationResult

_MAX_DIAGNOSTIC = 4096
_MAX_CAPTURE_BYTES = 65_536
_MAX_TITLE = 256
_MAX_BODY_BYTES = 262_144
_MAX_LABELS = 20
_MAX_LABEL = 100
_DEFAULT_TIMEOUT = 30.0
_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_URL_RE = re.compile(r"https://[^\s<>()]+")
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SECRET_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{8,}\b", re.IGNORECASE),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}\b", re.IGNORECASE),
    re.compile(r"(?im)\bauthorization\s*:\s*[^\r\n]+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)\b(password|passwd|token|access[_-]?token|secret|client[_-]?secret|api[_-]?key)"
        r"\s*[\"']?\s*[:=]\s*[\"']?[^\s,;&\"']+"
    ),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"https?://[^\s/@:]+:[^\s/@]+@"),
)
_REQUIRED_CREATE_FLAGS = ("--repo", "--title", "--body-file", "--label")


class IssueCreateReasonCode(str, Enum):
    CREATE_CONFIRMED = "create-confirmed"
    VALIDATION_INELIGIBLE = "validation-ineligible"
    ELIGIBLE_WARNING_NOT_ACCEPTED = "eligible-warning-not-accepted"
    CONFIRMATION_MISSING = "confirmation-missing"
    CONFIRMATION_CANCELLED = "confirmation-cancelled"
    CONFIRMATION_STALE_OR_MISMATCHED = "confirmation-stale-or-mismatched"
    GH_UNAVAILABLE = "gh-unavailable"
    GH_CAPABILITY_UNSUPPORTED = "gh-capability-unsupported"
    AUTHENTICATION_UNAVAILABLE = "authentication-unavailable"
    ACCOUNT_AMBIGUOUS_OR_MISMATCHED = "account-ambiguous-or-mismatched"
    TARGET_INVALID_OR_AMBIGUOUS = "target-invalid-or-ambiguous"
    TARGET_MISMATCHED = "target-mismatched"
    WRITE_AUTHORIZATION_ABSENT = "write-authorization-absent"
    OPTIONAL_METADATA_UNSUPPORTED = "optional-metadata-unsupported"
    COMMAND_FAILED = "command-failed"
    COMMAND_TIMEOUT = "command-timeout"
    COMMAND_INTERRUPTED = "command-interrupted"
    MALFORMED_SUCCESS_OUTPUT = "malformed-success-output"
    WRONG_TARGET_SUCCESS_OUTPUT = "wrong-target-success-output"
    MUTATION_UNCERTAIN = "mutation-uncertain"
    REPEAT_INVOCATION_DETECTED = "repeat-invocation-detected"


class IssueCreateExitCode(IntEnum):
    CONFIRMED = 0
    CONFIRMATION = 70
    GH_UNAVAILABLE = 71
    CAPABILITY = 72
    AUTHENTICATION = 73
    TARGET = 74
    AUTHORIZATION = 75
    COMMAND_FAILURE = 76
    TIMEOUT_OR_INTERRUPTION = 77
    MALFORMED_SUCCESS = 78
    UNCERTAIN = 79
    REPEATED = 80


class MutationState(str, Enum):
    NOT_ATTEMPTED = "not-attempted"
    UNCERTAIN = "uncertain"
    CONFIRMED = "confirmed"


@dataclass(frozen=True)
class GitHubRepositoryTarget:
    host: str
    owner: str
    repository: str

    @classmethod
    def parse(cls, value: str) -> "GitHubRepositoryTarget":
        if not isinstance(value, str) or value != value.strip():
            raise ValueError("target must be a trimmed string")
        parts = value.split("/")
        if len(parts) == 2:
            host, owner, repository = "github.com", parts[0], parts[1]
        elif len(parts) == 3:
            host, owner, repository = parts
        else:
            raise ValueError("target must be OWNER/REPOSITORY or HOST/OWNER/REPOSITORY")
        if not _valid_host(host):
            raise ValueError("target host is invalid or ambiguous")
        if any(
            not item
            or item in {".", ".."}
            or not _SLUG_RE.fullmatch(item)
            for item in (owner, repository)
        ):
            raise ValueError("target owner or repository is invalid")
        return cls(host.casefold(), owner, repository)

    @property
    def canonical(self) -> str:
        return f"{self.host}/{self.owner}/{self.repository}"

    @property
    def name_with_owner(self) -> str:
        return f"{self.owner}/{self.repository}"


@dataclass(frozen=True)
class IssueCreateRequest:
    validation: IssueDraftValidationResult
    target: GitHubRepositoryTarget
    invocation_id: str
    prior_fingerprints: tuple[str, ...] = ()
    optional_metadata: tuple[str, ...] = ()


@dataclass(frozen=True)
class GhCapabilities:
    version: str
    active_account: str
    repository_url: str
    executable_path: str
    fingerprint: str


@dataclass(frozen=True)
class IssueCreateCommandPlan:
    target: GitHubRepositoryTarget
    argv: tuple[str, ...]
    body: str
    body_digest: str
    body_bytes: int
    warning_reason_codes: tuple[str, ...]
    capability: GhCapabilities
    operation_identity: str
    operation_fingerprint: str


@dataclass(frozen=True)
class IssueCreateConfirmation:
    invocation_id: str
    operation_fingerprint: str
    target: str
    confirmed: bool
    accepted_warning_reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class IssueCreateProcessResult:
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    interrupted: bool = False


@dataclass(frozen=True)
class IssueCreateAdapterResult:
    status: str
    reason_code: IssueCreateReasonCode
    reason_codes: tuple[IssueCreateReasonCode, ...]
    exit_code: int
    target: str | None
    operation_identity: str | None
    operation_fingerprint: str | None
    planning_completed: bool
    confirmation_requested: bool
    confirmation_matched: bool
    write_authorized: bool
    execution_attempted: bool
    raw_process_exit_code: int | None
    sanitized_stdout: str
    sanitized_stderr: str
    created_issue_url: str | None
    created_issue_number: int | None
    mutation_state: MutationState
    mutation_performed: bool
    retry_allowed: bool
    recovery_evidence: tuple[str, ...]
    validation_status: str
    validation_reason_codes: tuple[str, ...]
    account_identity: str | None = None
    capability_fingerprint: str | None = None
    command_plan_digest: str | None = None


class GhRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        input_text: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> IssueCreateProcessResult: ...


class ConfirmationProvider(Protocol):
    def confirm(self, plan: IssueCreateCommandPlan) -> IssueCreateConfirmation | None: ...


class _BoundedCapture:
    def __init__(self, limit: int = _MAX_CAPTURE_BYTES) -> None:
        self.limit = limit
        self.data = bytearray()
        self.digest = hashlib.sha256()
        self.total = 0

    def drain(self, stream: BinaryIO) -> None:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                break
            self.digest.update(chunk)
            self.total += len(chunk)
            remaining = self.limit - len(self.data)
            if remaining > 0:
                self.data.extend(chunk[:remaining])

    def text(self) -> str:
        value = bytes(self.data).decode("utf-8", errors="replace")
        if self.total > len(self.data):
            value += f"\n[CAPTURE TRUNCATED sha256={self.digest.hexdigest()[:16]}]"
        return value


class SubprocessGhRunner:
    def __init__(self, *, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        found = shutil.which("gh")
        self.executable_path = os.path.realpath(found) if found else None

    def resolve_executable(self) -> str | None:
        return self.executable_path

    def run(
        self,
        argv: Sequence[str],
        *,
        input_text: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> IssueCreateProcessResult:
        env = _bounded_environment()
        process: subprocess.Popen[bytes] | None = None
        stdout_capture = _BoundedCapture()
        stderr_capture = _BoundedCapture()
        try:
            process = subprocess.Popen(
                tuple(argv),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                env=env,
            )
            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None
            stdout_thread = threading.Thread(
                target=stdout_capture.drain, args=(process.stdout,), daemon=True
            )
            stderr_thread = threading.Thread(
                target=stderr_capture.drain, args=(process.stderr,), daemon=True
            )
            stdout_thread.start()
            stderr_thread.start()

            def write_stdin() -> None:
                try:
                    if input_text is not None:
                        process.stdin.write(input_text.encode("utf-8"))
                except BrokenPipeError:
                    pass
                finally:
                    process.stdin.close()

            stdin_thread = threading.Thread(target=write_stdin, daemon=True)
            stdin_thread.start()
            try:
                returncode = process.wait(timeout=min(timeout, self.timeout))
                timed_out = False
                interrupted = False
            except subprocess.TimeoutExpired:
                process.kill()
                returncode = process.wait()
                timed_out = True
                interrupted = False
            except KeyboardInterrupt:
                process.kill()
                returncode = process.wait()
                timed_out = False
                interrupted = True
            stdin_thread.join()
            stdout_thread.join()
            stderr_thread.join()
            return IssueCreateProcessResult(
                returncode=returncode,
                stdout=stdout_capture.text(),
                stderr=stderr_capture.text(),
                timed_out=timed_out,
                interrupted=interrupted,
            )
        except OSError as exc:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            return IssueCreateProcessResult(returncode=None, stderr=str(exc))


def sanitize_diagnostic_text(
    value: str,
    *,
    limit: int = _MAX_DIAGNOSTIC,
    sensitive_values: Sequence[str] = (),
) -> str:
    text = _ANSI_RE.sub("", _coerce_text(value))
    for sensitive in sorted(
        {item for item in sensitive_values if isinstance(item, str) and item},
        key=len,
        reverse=True,
    ):
        text = text.replace(sensitive, "[REDACTED]")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    text = "".join(
        char if char in "\n\t" or ord(char) >= 32 and ord(char) != 127 else "�"
        for char in text
    )
    if len(text) <= limit:
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{text[:limit]}\n[TRUNCATED sha256={digest}]"


def build_issue_create_argv(
    target: GitHubRepositoryTarget,
    title: str,
    labels: Sequence[str],
    *,
    executable: str = "gh",
) -> tuple[str, ...]:
    _validate_text(title, "title", max_length=_MAX_TITLE, multiline=False)
    ordered_labels = tuple(sorted(dict.fromkeys(labels)))
    if len(ordered_labels) > _MAX_LABELS:
        raise ValueError("too many labels")
    for label in ordered_labels:
        _validate_text(label, "label", max_length=_MAX_LABEL, multiline=False)
    return (
        executable,
        "issue",
        "create",
        f"--repo={target.canonical}",
        f"--title={title}",
        "--body-file=-",
        *(f"--label={label}" for label in ordered_labels),
    )


def build_operation_fingerprint(
    request: IssueCreateRequest,
    *,
    operation_identity: str,
    argv: Sequence[str],
    capability: GhCapabilities,
) -> str:
    payload = {
        "domain": "agent-os.issue-create-confirmation.v1",
        "invocation_id": request.invocation_id,
        "operation_identity": operation_identity,
        "active_account": capability.active_account,
        "capability_fingerprint": capability.fingerprint,
        "semantic_argv": list(_semantic_argv(argv)),
    }
    return _sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )


def plan_issue_creation(
    request: IssueCreateRequest,
    runner: GhRunner,
) -> tuple[IssueCreateCommandPlan | None, IssueCreateAdapterResult | None]:
    validation = request.validation
    if (
        not validation.submission_eligible
        or validation.status not in {Status.PASS, Status.WARN}
        or validation.write_authorized
        or validation.mutation_performed
    ):
        return None, _result(
            request,
            IssueCreateReasonCode.VALIDATION_INELIGIBLE,
            IssueCreateExitCode.AUTHORIZATION,
        )
    if request.optional_metadata:
        return None, _result(
            request,
            IssueCreateReasonCode.OPTIONAL_METADATA_UNSUPPORTED,
            IssueCreateExitCode.AUTHORIZATION,
        )
    if not request.invocation_id.strip():
        return None, _result(
            request,
            IssueCreateReasonCode.WRITE_AUTHORIZATION_ABSENT,
            IssueCreateExitCode.AUTHORIZATION,
        )

    body = validation.draft.body
    try:
        _validate_text(body, "body", max_bytes=_MAX_BODY_BYTES, multiline=True)
        _validate_text(
            validation.draft.title,
            "title",
            max_length=_MAX_TITLE,
            multiline=False,
        )
        for label in validation.draft.proposed_labels:
            _validate_text(label, "label", max_length=_MAX_LABEL, multiline=False)
    except ValueError:
        return None, _result(
            request,
            IssueCreateReasonCode.VALIDATION_INELIGIBLE,
            IssueCreateExitCode.AUTHORIZATION,
        )

    capability, failure = _probe_capabilities(request, runner)
    if failure is not None:
        return None, failure
    assert capability is not None
    try:
        argv = build_issue_create_argv(
            request.target,
            validation.draft.title,
            validation.draft.proposed_labels,
            executable=capability.executable_path,
        )
    except ValueError:
        return None, _result(
            request,
            IssueCreateReasonCode.VALIDATION_INELIGIBLE,
            IssueCreateExitCode.AUTHORIZATION,
            capability=capability,
        )

    body_bytes = len(body.encode("utf-8"))
    body_digest = _sha256(body)
    operation_identity = _build_operation_identity(
        request,
        argv=argv,
        body_digest=body_digest,
        body_bytes=body_bytes,
    )
    if operation_identity in request.prior_fingerprints:
        return None, _result(
            request,
            IssueCreateReasonCode.REPEAT_INVOCATION_DETECTED,
            IssueCreateExitCode.REPEATED,
            identity=operation_identity,
            capability=capability,
        )
    fingerprint = build_operation_fingerprint(
        request,
        operation_identity=operation_identity,
        argv=argv,
        capability=capability,
    )
    warnings = (
        tuple(
            code.value
            for code in validation.reason_codes
            if code.value != "eligible-warning"
        )
        if validation.status == Status.WARN
        else ()
    )
    return (
        IssueCreateCommandPlan(
            target=request.target,
            argv=argv,
            body=body,
            body_digest=body_digest,
            body_bytes=body_bytes,
            warning_reason_codes=warnings,
            capability=capability,
            operation_identity=operation_identity,
            operation_fingerprint=fingerprint,
        ),
        None,
    )


def execute_issue_creation(
    request: IssueCreateRequest,
    runner: GhRunner,
    confirmation_provider: ConfirmationProvider,
) -> IssueCreateAdapterResult:
    plan, failure = plan_issue_creation(request, runner)
    if failure is not None:
        return failure
    assert plan is not None
    confirmation = confirmation_provider.confirm(plan)
    common_confirmation = dict(
        identity=plan.operation_identity,
        fingerprint=plan.operation_fingerprint,
        capability=plan.capability,
        planning=True,
        confirmation_requested=True,
    )
    if confirmation is None:
        return _result(
            request,
            IssueCreateReasonCode.CONFIRMATION_MISSING,
            IssueCreateExitCode.CONFIRMATION,
            **common_confirmation,
        )
    if not confirmation.confirmed:
        return _result(
            request,
            IssueCreateReasonCode.CONFIRMATION_CANCELLED,
            IssueCreateExitCode.CONFIRMATION,
            **common_confirmation,
        )
    expected_warnings = tuple(sorted(plan.warning_reason_codes))
    supplied_warnings = tuple(sorted(confirmation.accepted_warning_reason_codes))
    if expected_warnings != supplied_warnings:
        return _result(
            request,
            IssueCreateReasonCode.ELIGIBLE_WARNING_NOT_ACCEPTED,
            IssueCreateExitCode.CONFIRMATION,
            **common_confirmation,
        )
    if (
        confirmation.invocation_id != request.invocation_id
        or confirmation.operation_fingerprint != plan.operation_fingerprint
        or confirmation.target != request.target.canonical
    ):
        return _result(
            request,
            IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED,
            IssueCreateExitCode.CONFIRMATION,
            **common_confirmation,
        )

    process = runner.run(plan.argv, input_text=plan.body, timeout=_DEFAULT_TIMEOUT)
    sensitive_values = (
        plan.body,
        request.validation.draft.title,
        *request.validation.draft.proposed_labels,
    )
    stdout = sanitize_diagnostic_text(
        process.stdout, sensitive_values=sensitive_values
    )
    stderr = sanitize_diagnostic_text(
        process.stderr, sensitive_values=sensitive_values
    )
    common = dict(
        **common_confirmation,
        confirmation_matched=True,
        write_authorized=True,
        execution_attempted=True,
        raw_exit=process.returncode,
        stdout=stdout,
        stderr=stderr,
        command_plan_digest=_sha256(
            json.dumps(list(_semantic_argv(plan.argv)), separators=(",", ":"))
        ),
    )
    if process.timed_out:
        return _result(
            request,
            IssueCreateReasonCode.COMMAND_TIMEOUT,
            IssueCreateExitCode.TIMEOUT_OR_INTERRUPTION,
            mutation=MutationState.UNCERTAIN,
            **common,
        )
    if process.interrupted:
        return _result(
            request,
            IssueCreateReasonCode.COMMAND_INTERRUPTED,
            IssueCreateExitCode.TIMEOUT_OR_INTERRUPTION,
            mutation=MutationState.UNCERTAIN,
            **common,
        )
    if process.returncode != 0:
        return _result(
            request,
            IssueCreateReasonCode.COMMAND_FAILED,
            IssueCreateExitCode.COMMAND_FAILURE,
            mutation=MutationState.UNCERTAIN,
            **common,
        )

    parsed = _parse_created_issue(stdout, request.target)
    if parsed == "wrong-target":
        return _result(
            request,
            IssueCreateReasonCode.WRONG_TARGET_SUCCESS_OUTPUT,
            IssueCreateExitCode.UNCERTAIN,
            mutation=MutationState.UNCERTAIN,
            **common,
        )
    if parsed is None:
        return _result(
            request,
            IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT,
            IssueCreateExitCode.MALFORMED_SUCCESS,
            mutation=MutationState.UNCERTAIN,
            **common,
        )
    url, number = parsed
    return _result(
        request,
        IssueCreateReasonCode.CREATE_CONFIRMED,
        IssueCreateExitCode.CONFIRMED,
        mutation=MutationState.CONFIRMED,
        created_url=url,
        created_number=number,
        **common,
    )


def issue_create_result_to_dict(
    result: IssueCreateAdapterResult,
) -> dict[str, object]:
    payload = asdict(result)
    payload["reason_code"] = result.reason_code.value
    payload["reason_codes"] = [code.value for code in result.reason_codes]
    payload["mutation_state"] = result.mutation_state.value
    return payload


def render_issue_create_result(result: IssueCreateAdapterResult) -> str:
    lines = [
        "Agent OS GitHub Issue Create Adapter",
        f"Status: {result.status}",
        f"Reason: {result.reason_code.value}",
        f"Reason codes: {', '.join(code.value for code in result.reason_codes)}",
        f"Exit code: {result.exit_code}",
        f"Target: {result.target or 'none'}",
        f"Planning completed: {_yes_no(result.planning_completed)}",
        f"Confirmation matched: {_yes_no(result.confirmation_matched)}",
        f"Write authorized: {_yes_no(result.write_authorized)}",
        f"Execution attempted: {_yes_no(result.execution_attempted)}",
        f"Mutation state: {result.mutation_state.value}",
        f"Mutation performed: {_yes_no(result.mutation_performed)}",
        f"Retry allowed: {_yes_no(result.retry_allowed)}",
        f"Operation identity: {result.operation_identity or 'none'}",
        f"Operation fingerprint: {result.operation_fingerprint or 'none'}",
        f"Created issue: {result.created_issue_url or 'none'}",
        "Recovery evidence:",
        *(f"- {item}" for item in result.recovery_evidence or ("none",)),
        "Sanitized stdout:",
        result.sanitized_stdout or "none",
        "Sanitized stderr:",
        result.sanitized_stderr or "none",
    ]
    return "\n".join(lines) + "\n"


def _probe_capabilities(
    request: IssueCreateRequest,
    runner: GhRunner,
) -> tuple[GhCapabilities | None, IssueCreateAdapterResult | None]:
    executable = _resolve_executable(runner)
    if executable is None:
        return None, _result(
            request,
            IssueCreateReasonCode.GH_UNAVAILABLE,
            IssueCreateExitCode.GH_UNAVAILABLE,
        )
    version = runner.run((executable, "--version"))
    version_text = sanitize_diagnostic_text(version.stdout)
    if version.returncode != 0 or not version_text.strip():
        return None, _result(
            request,
            IssueCreateReasonCode.GH_UNAVAILABLE,
            IssueCreateExitCode.GH_UNAVAILABLE,
            stderr=sanitize_diagnostic_text(version.stderr),
        )
    help_result = runner.run((executable, "issue", "create", "--help"))
    if help_result.returncode != 0 or any(
        not _help_has_flag(help_result.stdout, flag)
        for flag in _REQUIRED_CREATE_FLAGS
    ):
        return None, _result(
            request,
            IssueCreateReasonCode.GH_CAPABILITY_UNSUPPORTED,
            IssueCreateExitCode.CAPABILITY,
            stderr=sanitize_diagnostic_text(help_result.stderr),
        )
    auth = runner.run(
        (executable, "auth", "status", "--active", "--hostname", request.target.host)
    )
    if auth.returncode != 0:
        return None, _result(
            request,
            IssueCreateReasonCode.AUTHENTICATION_UNAVAILABLE,
            IssueCreateExitCode.AUTHENTICATION,
            stderr=sanitize_diagnostic_text(auth.stderr),
        )
    auth_text = sanitize_diagnostic_text(f"{auth.stdout}\n{auth.stderr}")
    accounts = tuple(
        sorted(
            set(
                re.findall(
                    r"(?im)^.*?logged in to .*? account ([A-Za-z0-9_.-]+)\b",
                    auth_text,
                )
            )
        )
    )
    if len(accounts) != 1:
        return None, _result(
            request,
            IssueCreateReasonCode.ACCOUNT_AMBIGUOUS_OR_MISMATCHED,
            IssueCreateExitCode.AUTHENTICATION,
            stderr=sanitize_diagnostic_text(auth.stderr),
        )
    repo = runner.run(
        (
            executable,
            "repo",
            "view",
            request.target.canonical,
            "--json",
            "nameWithOwner,url,hasIssuesEnabled,isArchived",
        )
    )
    if repo.returncode != 0:
        return None, _result(
            request,
            IssueCreateReasonCode.TARGET_INVALID_OR_AMBIGUOUS,
            IssueCreateExitCode.TARGET,
            stderr=sanitize_diagnostic_text(repo.stderr),
        )
    try:
        metadata = json.loads(repo.stdout)
    except json.JSONDecodeError:
        return None, _result(
            request,
            IssueCreateReasonCode.TARGET_INVALID_OR_AMBIGUOUS,
            IssueCreateExitCode.TARGET,
        )
    if (
        str(metadata.get("nameWithOwner") or "").casefold()
        != request.target.name_with_owner.casefold()
        or metadata.get("isArchived") is not False
        or metadata.get("hasIssuesEnabled") is not True
    ):
        return None, _result(
            request,
            IssueCreateReasonCode.TARGET_MISMATCHED,
            IssueCreateExitCode.TARGET,
        )
    parsed = urlparse(str(metadata.get("url") or ""))
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").casefold() != request.target.host.casefold()
        or parsed.path.strip("/").casefold()
        != request.target.name_with_owner.casefold()
        or parsed.query
        or parsed.fragment
    ):
        return None, _result(
            request,
            IssueCreateReasonCode.TARGET_MISMATCHED,
            IssueCreateExitCode.TARGET,
        )
    capability_payload = {
        "version": version_text.splitlines()[0][:160],
        "account": accounts[0],
        "repository_url": metadata["url"],
        "executable_path": executable,
        "required_flags": _REQUIRED_CREATE_FLAGS,
    }
    fingerprint = _sha256(
        json.dumps(capability_payload, sort_keys=True, separators=(",", ":"))
    )
    return (
        GhCapabilities(
            capability_payload["version"],
            accounts[0],
            metadata["url"],
            executable,
            fingerprint,
        ),
        None,
    )


def _parse_created_issue(
    stdout: str,
    target: GitHubRepositoryTarget,
) -> tuple[str, int] | str | None:
    candidates = [
        value.rstrip(".,;)")
        for value in _URL_RE.findall(stdout)
        if "/issues/" in value.casefold()
    ]
    if len(candidates) != 1:
        return None
    url = candidates[0]
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme != "https"
        or parsed.query
        or parsed.fragment
        or len(parts) != 4
        or parts[2].casefold() != "issues"
    ):
        return None
    if (
        (parsed.hostname or "").casefold() != target.host.casefold()
        or [part.casefold() for part in parts[:2]]
        != [target.owner.casefold(), target.repository.casefold()]
    ):
        return "wrong-target"
    if not parts[3].isdigit() or int(parts[3]) <= 0:
        return None
    return url, int(parts[3])


def _result(
    request: IssueCreateRequest,
    reason: IssueCreateReasonCode,
    exit_code: IssueCreateExitCode,
    *,
    identity: str | None = None,
    fingerprint: str | None = None,
    capability: GhCapabilities | None = None,
    planning: bool = False,
    confirmation_requested: bool = False,
    confirmation_matched: bool = False,
    write_authorized: bool = False,
    execution_attempted: bool = False,
    raw_exit: int | None = None,
    stdout: str = "",
    stderr: str = "",
    mutation: MutationState = MutationState.NOT_ATTEMPTED,
    created_url: str | None = None,
    created_number: int | None = None,
    command_plan_digest: str | None = None,
) -> IssueCreateAdapterResult:
    uncertain = mutation == MutationState.UNCERTAIN
    reason_codes = (
        (reason, IssueCreateReasonCode.MUTATION_UNCERTAIN)
        if uncertain and reason != IssueCreateReasonCode.MUTATION_UNCERTAIN
        else (reason,)
    )
    retry_allowed = (
        mutation == MutationState.NOT_ATTEMPTED
        and not execution_attempted
        and reason != IssueCreateReasonCode.REPEAT_INVOCATION_DETECTED
    )
    return IssueCreateAdapterResult(
        status="pass" if reason == IssueCreateReasonCode.CREATE_CONFIRMED else "blocked",
        reason_code=reason,
        reason_codes=reason_codes,
        exit_code=int(exit_code),
        target=request.target.canonical,
        operation_identity=identity,
        operation_fingerprint=fingerprint,
        planning_completed=planning,
        confirmation_requested=confirmation_requested,
        confirmation_matched=confirmation_matched,
        write_authorized=write_authorized,
        execution_attempted=execution_attempted,
        raw_process_exit_code=raw_exit,
        sanitized_stdout=sanitize_diagnostic_text(stdout),
        sanitized_stderr=sanitize_diagnostic_text(stderr),
        created_issue_url=created_url,
        created_issue_number=created_number,
        mutation_state=mutation,
        mutation_performed=mutation == MutationState.CONFIRMED,
        retry_allowed=retry_allowed,
        recovery_evidence=(
            "Do not retry automatically; verify the target manually using the operation identity."
            if uncertain
            else "No recovery action required."
        ,),
        validation_status=request.validation.status.value,
        validation_reason_codes=tuple(
            code.value for code in request.validation.reason_codes
        ),
        account_identity=capability.active_account if capability else None,
        capability_fingerprint=capability.fingerprint if capability else None,
        command_plan_digest=command_plan_digest,
    )


def _build_operation_identity(
    request: IssueCreateRequest,
    *,
    argv: Sequence[str],
    body_digest: str,
    body_bytes: int,
) -> str:
    payload = {
        "domain": "agent-os.issue-create-operation.v1",
        "target": request.target.canonical.casefold(),
        "title_digest": _sha256(request.validation.draft.title),
        "body_digest": body_digest,
        "body_bytes": body_bytes,
        "labels": sorted(request.validation.draft.proposed_labels),
        "optional_metadata": sorted(request.optional_metadata),
        "validation_status": request.validation.status.value,
        "validation_reason_codes": [
            code.value for code in request.validation.reason_codes
        ],
        "semantic_argv": list(_semantic_argv(argv)),
    }
    return _sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )


def _semantic_argv(argv: Sequence[str]) -> tuple[str, ...]:
    if not argv:
        return ()
    return ("gh", *tuple(argv)[1:])


def _resolve_executable(runner: GhRunner) -> str | None:
    resolver = getattr(runner, "resolve_executable", None)
    if callable(resolver):
        value = resolver()
        return str(value) if value else None
    return "gh"


def _help_has_flag(text: str, flag: str) -> bool:
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9_-]){re.escape(flag)}(?=$|[\s=,\[])",
            text,
        )
    )


def _valid_host(host: str) -> bool:
    if not host or len(host) > 253 or host != host.strip() or "." not in host:
        return False
    labels = host.split(".")
    return all(_HOST_LABEL_RE.fullmatch(label) for label in labels)


def _validate_text(
    value: str,
    name: str,
    *,
    max_length: int | None = None,
    max_bytes: int | None = None,
    multiline: bool,
) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    allowed_controls = "\n\r\t" if multiline else ""
    if any(
        ord(char) < 32 and char not in allowed_controls or ord(char) == 127
        for char in value
    ):
        raise ValueError(f"{name} contains unsupported control characters")
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"{name} is too long")
    if max_bytes is not None and len(value.encode("utf-8")) > max_bytes:
        raise ValueError(f"{name} is too large")


def _bounded_environment() -> dict[str, str]:
    allowed = {
        "PATH",
        "HOME",
        "USERPROFILE",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "GH_CONFIG_DIR",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "GITHUB_ENTERPRISE_TOKEN",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.update({"GH_PROMPT_DISABLED": "1", "GH_PAGER": "cat", "NO_COLOR": "1"})
    env.pop("GH_REPO", None)
    env.pop("GH_HOST", None)
    return env


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _coerce_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
