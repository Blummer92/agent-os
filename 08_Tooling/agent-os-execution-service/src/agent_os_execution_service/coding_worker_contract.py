"""Provider-neutral semantic coding-worker evidence contract for #2318.

This module is deliberately a pure contract boundary. Agent OS governance selects
and authorizes work upstream; a semantic coding worker receives bounded references
and returns evidence. Nothing here executes a provider, mutates a repository,
grants authority, validates a lifecycle, retries work, or persists state.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Literal

CODING_WORKER_SCHEMA_VERSION = "1.0"
MAX_IDENTIFIER_LENGTH = 256
MAX_TEXT_BYTES = 4096
MAX_ITEMS = 256
MAX_PATH_LENGTH = 512

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$", re.ASCII)
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", re.ASCII)
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)


class CodingWorkerOperation(str, Enum):
    """Small semantic operation vocabulary; it carries no governance authority."""

    INSPECT = "inspect"
    IMPLEMENT = "implement"
    REPAIR = "repair"
    TEST = "test"
    REFACTOR = "refactor"
    GENERATE_REGRESSION_TEST = "generate-regression-test"


class CodingWorkerStatus(str, Enum):
    """Evidence-only outcome vocabulary returned by a semantic coding worker."""

    COMPLETED = "completed"
    NO_CHANGE_NEEDED = "no-change-needed"
    NEEDS_REPAIR = "needs-repair"
    BLOCKED = "blocked"
    NEEDS_DECISION = "needs-decision"
    SCOPE_VIOLATION = "scope-violation"
    EXECUTION_FAILURE = "execution-failure"


def _text(name: str, value: object, maximum: int = MAX_TEXT_BYTES) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if not value or len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{name} is empty or exceeds its byte bound")
    return value


def _identifier(name: str, value: object) -> str:
    text = _text(name, value, MAX_IDENTIFIER_LENGTH)
    if not _IDENTIFIER_RE.fullmatch(text):
        raise ValueError(f"{name} must use bounded ASCII identifier syntax")
    return text


def _repository(value: object) -> str:
    text = _text("repository", value, MAX_IDENTIFIER_LENGTH)
    if not _REPOSITORY_RE.fullmatch(text):
        raise ValueError("repository must use owner/name syntax")
    return text


def _sha(name: str, value: object) -> str:
    text = _text(name, value, 40)
    if not _SHA40_RE.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase 40-hex SHA")
    return text


def _tuple(name: str, value: object, *, identifiers: bool = False) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    if len(value) > MAX_ITEMS:
        raise ValueError(f"{name} exceeds its item bound")
    checked = tuple(
        _identifier(name, item) if identifiers else _text(name, item)
        for item in value
    )
    if len(set(checked)) != len(checked):
        raise ValueError(f"{name} must not contain duplicates")
    return checked


def _path_tuple(name: str, value: object) -> tuple[str, ...]:
    items = _tuple(name, value)
    checked: list[str] = []
    for item in items:
        if len(item.encode("utf-8")) > MAX_PATH_LENGTH:
            raise ValueError(f"{name} contains an overlong path")
        if item.startswith("/") or "\\" in item or any(
            part in {"", ".", ".."} for part in item.split("/")
        ):
            raise ValueError(f"{name} contains an unsafe repository path")
        checked.append(item)
    return tuple(checked)


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(domain: str, payload: object) -> str:
    material = f"{domain}:v1\0".encode("ascii") + _canonical_json(payload).encode("utf-8")
    return f"{domain}:{hashlib.sha256(material).hexdigest()}"


def _paths_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


@dataclass(frozen=True, slots=True, kw_only=True)
class CodingWorkerRequest:
    """Bounded semantic-work request referencing existing Agent OS owners."""

    schema_version: str
    task_id: str
    repository: str
    issue_or_handoff_identity: str
    base_sha: str
    workspace_identity: str
    operation: CodingWorkerOperation
    implementation_packet_source_identity: str
    executor_handoff_id: str
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    validation_command_plan_id_or_none: str | None = None
    checkpoint_id_or_none: str | None = None
    normalized_failure_evidence_id_or_none: str | None = None
    request_id: str = ""
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    closure_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != CODING_WORKER_SCHEMA_VERSION:
            raise ValueError("schema_version is unsupported")
        _identifier("task_id", self.task_id)
        _repository(self.repository)
        _identifier("issue_or_handoff_identity", self.issue_or_handoff_identity)
        _sha("base_sha", self.base_sha)
        _identifier("workspace_identity", self.workspace_identity)
        if type(self.operation) is not CodingWorkerOperation:
            raise TypeError("operation must be an exact CodingWorkerOperation")
        _identifier("implementation_packet_source_identity", self.implementation_packet_source_identity)
        _identifier("executor_handoff_id", self.executor_handoff_id)
        allowed = _path_tuple("allowed_paths", self.allowed_paths)
        forbidden = _path_tuple("forbidden_paths", self.forbidden_paths)
        if any(_paths_overlap(left, right) for left in allowed for right in forbidden):
            raise ValueError("allowed_paths and forbidden_paths must not overlap")
        for name in (
            "validation_command_plan_id_or_none",
            "checkpoint_id_or_none",
            "normalized_failure_evidence_id_or_none",
        ):
            value = getattr(self, name)
            if value is not None:
                _identifier(name, value)
        computed = coding_worker_request_id(self)
        if self.request_id and self.request_id != computed:
            raise ValueError("request_id does not match request content")
        object.__setattr__(self, "request_id", computed)

    def to_dict(self) -> dict[str, object]:
        return _request_payload(self, include_id=True)

    @classmethod
    def from_dict(cls, payload: object) -> "CodingWorkerRequest":
        if type(payload) is not dict or set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("coding-worker request contains unknown or missing fields")
        for name in (
            "execution_authorized",
            "merge_authorized",
            "closure_authorized",
            "external_writes_authorized",
        ):
            if payload[name] is not False:
                raise ValueError(f"{name} must be false")
        values = dict(payload)
        for name in (
            "execution_authorized",
            "merge_authorized",
            "closure_authorized",
            "external_writes_authorized",
        ):
            values.pop(name)
        values["operation"] = CodingWorkerOperation(values["operation"])
        values["allowed_paths"] = tuple(values["allowed_paths"])
        values["forbidden_paths"] = tuple(values["forbidden_paths"])
        return cls(**values)


@dataclass(frozen=True, slots=True, kw_only=True)
class CodingWorkerResult:
    """Structured worker evidence. Successful status never creates authority."""

    schema_version: str
    request_id: str
    task_id: str
    repository: str
    base_sha: str
    workspace_identity: str
    status: CodingWorkerStatus
    summary: str
    files_inspected: tuple[str, ...]
    files_changed: tuple[str, ...]
    commands_run: tuple[str, ...]
    tests_run: tuple[str, ...]
    test_result_ids: tuple[str, ...]
    diagnostic_ids: tuple[str, ...]
    assumption_ids: tuple[str, ...]
    unresolved_question_ids: tuple[str, ...]
    scope_violation_paths: tuple[str, ...]
    blocked_reason_or_none: str | None
    patch_identity_or_none: str | None
    result_sha_or_none: str | None
    result_id: str = ""
    execution_authorized: Literal[False] = field(default=False, init=False)
    validation_authorized: Literal[False] = field(default=False, init=False)
    ready_for_review_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    closure_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != CODING_WORKER_SCHEMA_VERSION:
            raise ValueError("schema_version is unsupported")
        _identifier("request_id", self.request_id)
        _identifier("task_id", self.task_id)
        _repository(self.repository)
        _sha("base_sha", self.base_sha)
        _identifier("workspace_identity", self.workspace_identity)
        if type(self.status) is not CodingWorkerStatus:
            raise TypeError("status must be an exact CodingWorkerStatus")
        _text("summary", self.summary)
        _path_tuple("files_inspected", self.files_inspected)
        _path_tuple("files_changed", self.files_changed)
        _tuple("commands_run", self.commands_run)
        _tuple("tests_run", self.tests_run)
        for name in (
            "test_result_ids",
            "diagnostic_ids",
            "assumption_ids",
            "unresolved_question_ids",
        ):
            _tuple(name, getattr(self, name), identifiers=True)
        violations = _path_tuple("scope_violation_paths", self.scope_violation_paths)
        if self.status is CodingWorkerStatus.SCOPE_VIOLATION and not violations:
            raise ValueError("scope-violation status requires scope_violation_paths")
        if violations and self.status is not CodingWorkerStatus.SCOPE_VIOLATION:
            raise ValueError("scope_violation_paths require scope-violation status")
        if self.status in {CodingWorkerStatus.BLOCKED, CodingWorkerStatus.NEEDS_DECISION}:
            if self.blocked_reason_or_none is None:
                raise ValueError("blocked/needs-decision status requires blocked_reason_or_none")
        if self.blocked_reason_or_none is not None:
            _identifier("blocked_reason_or_none", self.blocked_reason_or_none)
        if self.patch_identity_or_none is not None:
            _identifier("patch_identity_or_none", self.patch_identity_or_none)
        if self.result_sha_or_none is not None:
            _sha("result_sha_or_none", self.result_sha_or_none)
        computed = coding_worker_result_id(self)
        if self.result_id and self.result_id != computed:
            raise ValueError("result_id does not match result content")
        object.__setattr__(self, "result_id", computed)

    def to_dict(self) -> dict[str, object]:
        return _result_payload(self, include_id=True)

    @classmethod
    def from_dict(cls, payload: object) -> "CodingWorkerResult":
        if type(payload) is not dict or set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("coding-worker result contains unknown or missing fields")
        authority_fields = (
            "execution_authorized",
            "validation_authorized",
            "ready_for_review_authorized",
            "merge_authorized",
            "closure_authorized",
            "external_writes_authorized",
        )
        for name in authority_fields:
            if payload[name] is not False:
                raise ValueError(f"{name} must be false")
        values = dict(payload)
        for name in authority_fields:
            values.pop(name)
        values["status"] = CodingWorkerStatus(values["status"])
        for name in (
            "files_inspected",
            "files_changed",
            "commands_run",
            "tests_run",
            "test_result_ids",
            "diagnostic_ids",
            "assumption_ids",
            "unresolved_question_ids",
            "scope_violation_paths",
        ):
            values[name] = tuple(values[name])
        return cls(**values)


def _request_payload(value: CodingWorkerRequest, *, include_id: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": value.schema_version,
        "task_id": value.task_id,
        "repository": value.repository,
        "issue_or_handoff_identity": value.issue_or_handoff_identity,
        "base_sha": value.base_sha,
        "workspace_identity": value.workspace_identity,
        "operation": value.operation.value,
        "implementation_packet_source_identity": value.implementation_packet_source_identity,
        "executor_handoff_id": value.executor_handoff_id,
        "allowed_paths": list(value.allowed_paths),
        "forbidden_paths": list(value.forbidden_paths),
        "validation_command_plan_id_or_none": value.validation_command_plan_id_or_none,
        "checkpoint_id_or_none": value.checkpoint_id_or_none,
        "normalized_failure_evidence_id_or_none": value.normalized_failure_evidence_id_or_none,
        "execution_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "external_writes_authorized": False,
    }
    if include_id:
        payload["request_id"] = value.request_id
    return payload


def _result_payload(value: CodingWorkerResult, *, include_id: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": value.schema_version,
        "request_id": value.request_id,
        "task_id": value.task_id,
        "repository": value.repository,
        "base_sha": value.base_sha,
        "workspace_identity": value.workspace_identity,
        "status": value.status.value,
        "summary": value.summary,
        "files_inspected": list(value.files_inspected),
        "files_changed": list(value.files_changed),
        "commands_run": list(value.commands_run),
        "tests_run": list(value.tests_run),
        "test_result_ids": list(value.test_result_ids),
        "diagnostic_ids": list(value.diagnostic_ids),
        "assumption_ids": list(value.assumption_ids),
        "unresolved_question_ids": list(value.unresolved_question_ids),
        "scope_violation_paths": list(value.scope_violation_paths),
        "blocked_reason_or_none": value.blocked_reason_or_none,
        "patch_identity_or_none": value.patch_identity_or_none,
        "result_sha_or_none": value.result_sha_or_none,
        "execution_authorized": False,
        "validation_authorized": False,
        "ready_for_review_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "external_writes_authorized": False,
    }
    if include_id:
        payload["result_id"] = value.result_id
    return payload


def coding_worker_request_id(value: CodingWorkerRequest) -> str:
    return _digest("coding-worker-request", _request_payload(value, include_id=False))


def coding_worker_result_id(value: CodingWorkerResult) -> str:
    return _digest("coding-worker-result", _result_payload(value, include_id=False))


def serialize_coding_worker_request(value: CodingWorkerRequest) -> str:
    return _canonical_json(value.to_dict())


def serialize_coding_worker_result(value: CodingWorkerResult) -> str:
    return _canonical_json(value.to_dict())


__all__ = [
    "CODING_WORKER_SCHEMA_VERSION",
    "CodingWorkerOperation",
    "CodingWorkerStatus",
    "CodingWorkerRequest",
    "CodingWorkerResult",
    "coding_worker_request_id",
    "coding_worker_result_id",
    "serialize_coding_worker_request",
    "serialize_coding_worker_result",
]
