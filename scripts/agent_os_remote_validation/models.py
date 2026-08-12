from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

VALIDATION_PLAN_SCHEMA_NAME = "agent-os-validation-plan"
VALIDATION_PLAN_SCHEMA_VERSION = "1.0"
MAX_PLAN_STRING_LENGTH = 4096
MAX_PLAN_COMMANDS = 64
MAX_PLAN_REASON_CODES = 32
MAX_PLAN_SERIALIZED_BYTES = 262_144

ValidationProfile = Literal["static", "focused", "aggregate", "manual-review"]

PRE_PR_VALIDATION_SUBJECT_SCHEMA_NAME = "agent-os-pre-pr-validation-subject"
PRE_PR_VALIDATION_SUBJECT_SCHEMA_VERSION = "1.0"
PRE_PR_VALIDATION_PLAN_SCHEMA_NAME = "agent-os-pre-pr-validation-plan"
PRE_PR_VALIDATION_PLAN_SCHEMA_VERSION = "1.0"

PRE_PR_REPOSITORY = "Blummer92/agent-os"
PRE_PR_CANDIDATE_ISSUE_NUMBER = 726
PRE_PR_BASE_BRANCH = "main"
PRE_PR_EXECUTION_MODE = "validation-only"
PRE_PR_PROFILE = "focused"

PRE_PR_PER_COMMAND_TIMEOUT_SECONDS = 30
PRE_PR_TOTAL_VALIDATION_TIMEOUT_SECONDS = 300

MAX_PRE_PR_ALLOWED_FILES = 256
MAX_PRE_PR_FORBIDDEN_PATHS = 256
MAX_PRE_PR_COMMAND_IDENTITIES = 8
MAX_PRE_PR_REASON_CODES = 8
MAX_PRE_PR_PATH_LENGTH = 512
MAX_PRE_PR_SERIALIZED_BYTES = 65_536

PROTECTED_PRE_PR_REFS = frozenset({"main", "master"})


@dataclass(frozen=True)
class SelectionInput:
    repository: str
    pull_request: int
    base_sha: str
    head_sha: str
    changed_files: tuple[str, ...]
    selector_version: str = "1.0.0"


@dataclass(frozen=True)
class ValidationPlan:
    selector_version: str
    repository: str
    pull_request: int
    base_sha: str
    head_sha: str
    profile: ValidationProfile
    commands: tuple[str, ...]
    command_set_digest: str
    reason_codes: tuple[str, ...]
    remote_build_required: bool
    execution_authorized: bool = False
    side_effects_performed: bool = False


_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$", re.ASCII)
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$", re.ASCII)
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$", re.ASCII)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FORBIDDEN_REF_CHARS = frozenset(" ~^:?*[\\")


@dataclass(frozen=True, slots=True, kw_only=True)
class PrePrValidationSubject:
    """One immutable issue- and invocation-bound validation subject with no pull request.

    A missing pull request is represented by the absence of the field, never by a
    placeholder number, dummy pull request, or unbound mutable branch. Candidate-
    bound subjects may additionally retain exact expected changed paths so packet
    identity changes when in-scope path expectations drift. Construction fails
    closed on malformed identifiers, SHAs, refs, scope, or execution mode.
    """

    schema_name: str = PRE_PR_VALIDATION_SUBJECT_SCHEMA_NAME
    schema_version: str = PRE_PR_VALIDATION_SUBJECT_SCHEMA_VERSION
    repository: str = PRE_PR_REPOSITORY
    issue_number: int = PRE_PR_CANDIDATE_ISSUE_NUMBER
    invocation_id: str
    base_branch: str = PRE_PR_BASE_BRANCH
    base_sha: str
    branch: str
    expected_source_sha: str
    tested_sha: str
    allowed_files: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_command_identities: tuple[str, ...]
    approval_id: str
    approval_revision: int
    projection_id: str
    implementation_contract_fingerprint: str
    expected_changed_paths: tuple[str, ...] = ()
    execution_mode: str = PRE_PR_EXECUTION_MODE
    candidate_bound: bool = False

    def __post_init__(self) -> None:
        _require_exact_value("schema_name", self.schema_name, PRE_PR_VALIDATION_SUBJECT_SCHEMA_NAME)
        _require_exact_value(
            "schema_version", self.schema_version, PRE_PR_VALIDATION_SUBJECT_SCHEMA_VERSION
        )
        if type(self.candidate_bound) is not bool:
            raise TypeError("candidate_bound must be an exact boolean")
        _require_positive_int("issue_number", self.issue_number)
        if self.candidate_bound:
            _require_exact_str("repository", self.repository)
            parts = self.repository.split("/")
            if len(parts) != 2 or not all(parts):
                raise ValueError("repository must use canonical owner/repository syntax")
            _validate_ref("base_branch", self.base_branch)
            _validate_identifier("execution_mode", self.execution_mode)
        else:
            _require_exact_value("repository", self.repository, PRE_PR_REPOSITORY)
            _require_exact_value("base_branch", self.base_branch, PRE_PR_BASE_BRANCH)
            _require_exact_value("execution_mode", self.execution_mode, PRE_PR_EXECUTION_MODE)
            if self.issue_number != PRE_PR_CANDIDATE_ISSUE_NUMBER:
                raise ValueError("issue_number must be the bound validation-only candidate issue")
        _validate_identifier("invocation_id", self.invocation_id)
        _validate_identifier("approval_id", self.approval_id)
        _validate_identifier("projection_id", self.projection_id)
        _require_positive_int("approval_revision", self.approval_revision)
        _validate_sha40("base_sha", self.base_sha)
        _validate_sha40("expected_source_sha", self.expected_source_sha)
        _validate_sha40("tested_sha", self.tested_sha)
        if not self.candidate_bound and self.tested_sha != self.expected_source_sha:
            raise ValueError("tested_sha must match expected_source_sha")
        _validate_sha256(
            "implementation_contract_fingerprint", self.implementation_contract_fingerprint
        )
        _validate_ref("branch", self.branch)
        if self.branch.casefold() in PROTECTED_PRE_PR_REFS or self.branch == self.base_branch:
            raise ValueError("branch must be a non-protected ref distinct from base_branch")
        _validate_path_tuple("allowed_files", self.allowed_files, MAX_PRE_PR_ALLOWED_FILES)
        _validate_path_tuple("forbidden_paths", self.forbidden_paths, MAX_PRE_PR_FORBIDDEN_PATHS)
        for allowed in self.allowed_files:
            for forbidden in self.forbidden_paths:
                if paths_overlap(allowed, forbidden):
                    raise ValueError("allowed_files and forbidden_paths must not overlap")
        _require_exact_tuple("expected_changed_paths", self.expected_changed_paths)
        if self.expected_changed_paths:
            if not self.candidate_bound:
                raise ValueError("expected_changed_paths requires candidate_bound mode")
            _validate_path_tuple(
                "expected_changed_paths",
                self.expected_changed_paths,
                MAX_PRE_PR_ALLOWED_FILES,
            )
            if any(path not in self.allowed_files for path in self.expected_changed_paths):
                raise ValueError("expected_changed_paths must be contained in allowed_files")
        _validate_command_identities(self.required_command_identities)


@dataclass(frozen=True, slots=True, kw_only=True)
class PrePrValidationPlan:
    """One additive pre-PR plan bound to exactly one immutable pre-PR subject.

    The plan is a planning artifact only: it never authorizes execution or merge and
    never records a side effect. Ordered command identities are preserved exactly as
    the subject declared them.
    """

    schema_name: str = PRE_PR_VALIDATION_PLAN_SCHEMA_NAME
    schema_version: str = PRE_PR_VALIDATION_PLAN_SCHEMA_VERSION
    selector_version: str
    subject: PrePrValidationSubject
    profile: str = PRE_PR_PROFILE
    commands: tuple[str, ...]
    command_set_digest: str
    reason_codes: tuple[str, ...]
    per_command_timeout_seconds: int = PRE_PR_PER_COMMAND_TIMEOUT_SECONDS
    total_validation_timeout_seconds: int = PRE_PR_TOTAL_VALIDATION_TIMEOUT_SECONDS
    remote_build_required: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_exact_value("schema_name", self.schema_name, PRE_PR_VALIDATION_PLAN_SCHEMA_NAME)
        _require_exact_value(
            "schema_version", self.schema_version, PRE_PR_VALIDATION_PLAN_SCHEMA_VERSION
        )
        _require_exact_value("profile", self.profile, PRE_PR_PROFILE)
        if type(self.subject) is not PrePrValidationSubject:
            raise TypeError("subject must be an exact PrePrValidationSubject")
        _require_exact_str("selector_version", self.selector_version)
        if not _SEMVER_RE.fullmatch(self.selector_version):
            raise ValueError("selector_version must be MAJOR.MINOR.PATCH")
        _validate_sha256("command_set_digest", self.command_set_digest)
        _validate_command_identities(self.commands)
        if self.commands != self.subject.required_command_identities:
            raise ValueError("commands must match the subject's ordered command identities")
        _require_exact_tuple("reason_codes", self.reason_codes)
        if not self.reason_codes or len(self.reason_codes) > MAX_PRE_PR_REASON_CODES:
            raise ValueError("reason_codes must be non-empty and bounded")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes must be unique")
        if any(not _bounded_text(reason) for reason in self.reason_codes):
            raise ValueError("reason_codes must contain bounded text")
        _require_bounded_timeout(
            "per_command_timeout_seconds",
            self.per_command_timeout_seconds,
            PRE_PR_PER_COMMAND_TIMEOUT_SECONDS,
        )
        _require_bounded_timeout(
            "total_validation_timeout_seconds",
            self.total_validation_timeout_seconds,
            PRE_PR_TOTAL_VALIDATION_TIMEOUT_SECONDS,
        )
        if self.per_command_timeout_seconds > self.total_validation_timeout_seconds:
            raise ValueError("per-command timeout cannot exceed the total validation timeout")


def paths_overlap(left: str, right: str) -> bool:
    """Return whether two canonical repository-relative paths share a scope."""
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def _bounded_text(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and len(value) <= MAX_PLAN_STRING_LENGTH
        and _CONTROL_RE.search(value) is None
    )


def _require_exact_str(name: str, value: object) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")


def _require_exact_tuple(name: str, value: object) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")


def _require_exact_value(name: str, value: object, expected: str) -> None:
    _require_exact_str(name, value)
    if value != expected:
        raise ValueError(f"{name} must be exactly {expected!r}")


def _require_positive_int(name: str, value: object) -> None:
    if type(value) is not int or value <= 0:
        raise TypeError(f"{name} must be a positive exact integer")


def _require_bounded_timeout(name: str, value: object, ceiling: int) -> None:
    _require_positive_int(name, value)
    if value > ceiling:
        raise ValueError(f"{name} exceeds the {ceiling}-second ceiling")


def _validate_identifier(name: str, value: object) -> None:
    _require_exact_str(name, value)
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{name} must use bounded ASCII identifier syntax")


def _validate_sha40(name: str, value: object) -> None:
    _require_exact_str(name, value)
    if not _SHA40_RE.fullmatch(value):
        raise ValueError(f"{name} must be a full lowercase commit SHA")


def _validate_sha256(name: str, value: object) -> None:
    _require_exact_str(name, value)
    if not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _validate_ref(name: str, value: object) -> None:
    _require_exact_str(name, value)
    if not _REF_RE.fullmatch(value):
        raise ValueError(f"{name} must use canonical ASCII ref syntax")
    if value.endswith("/") or "//" in value or ".." in value or "@{" in value:
        raise ValueError(f"{name} is not canonical")
    if any(char in value for char in _FORBIDDEN_REF_CHARS):
        raise ValueError(f"{name} contains a forbidden ref character")


def _validate_path(value: object) -> None:
    _require_exact_str("path", value)
    if not value or len(value) > MAX_PRE_PR_PATH_LENGTH or value.startswith("/") or "\\" in value:
        raise ValueError("path must be a bounded repository-relative POSIX path")
    if _CONTROL_RE.search(value) is not None:
        raise ValueError("path contains a control character")
    if any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("path contains a non-canonical segment")


def _validate_path_tuple(name: str, values: object, ceiling: int) -> None:
    _require_exact_tuple(name, values)
    if not values:
        raise ValueError(f"{name} must not be empty")
    if len(values) > ceiling:
        raise ValueError(f"{name} exceeds the path ceiling")
    for item in values:
        _validate_path(item)
    if values != tuple(sorted(values)) or len(set(values)) != len(values):
        raise ValueError(f"{name} must be sorted and unique")
    for index, left in enumerate(values):
        for right in values[index + 1 :]:
            if paths_overlap(left, right):
                raise ValueError(f"{name} must not contain overlapping paths")


def _validate_command_identities(values: object) -> None:
    _require_exact_tuple("required_command_identities", values)
    if not values:
        raise ValueError("required_command_identities must not be empty")
    if len(values) > MAX_PRE_PR_COMMAND_IDENTITIES:
        raise ValueError("required_command_identities exceeds the command ceiling")
    if any(not _bounded_text(item) for item in values):
        raise ValueError("required_command_identities must contain bounded text")
    if len(set(values)) != len(values):
        raise ValueError("required_command_identities must be unique")
