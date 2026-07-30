"""Pure-local admission evidence for governed GitHub lifecycle mutations."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

SCHEMA_VERSION = "1.0"
MAX_MUTATIONS = 8
MAX_LABELS = 32
MAX_REASONS = 32
MAX_DETAILS = 32
MAX_DETAIL_LENGTH = 500
MAX_AUTHORIZATION_BYTES = 16 * 1024
MAX_SNAPSHOT_BYTES = 12 * 1024
MAX_RESULT_BYTES = 12 * 1024

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

MUTATIONS = frozenset({"mark-ready", "mark-draft", "merge", "close-issue", "reopen-issue", "add-lifecycle-label", "remove-lifecycle-label", "replace-lifecycle-labels"})
AUTHORIZATION_STATES = frozenset({"pending", "authorized", "rejected", "expired", "invalidated", "consumed", "superseded"})
ISSUE_STATES = frozenset({"open", "closed"})
PR_STATES = frozenset({"draft", "ready", "none"})
REVIEW_STATES = frozenset({"clear", "blocked", "unknown"})
REASON_CODES = frozenset({"authorization-not-authorized", "authorization-stale", "authorization-mutation-not-permitted", "mutation-precondition-not-met", "identity-repository-mismatch", "identity-issue-mismatch", "identity-pull-request-mismatch", "pull-request-head-changed", "pull-request-base-changed", "pull-request-ready-state-changed", "pull-request-merged-state-changed", "issue-state-changed", "review-state-changed", "review-thread-state-changed", "lifecycle-label-state-changed"})


class AdmissionStatus(str, Enum):
    ADMITTED = "admitted"
    BLOCKED = "blocked"
    STALE = "stale"
    INVALID = "invalid"


def _exact_text(value: object, name: str, *, maximum: int = 128) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a built-in string")
    if not value or len(value) > maximum or _CONTROL_RE.search(value):
        raise ValueError(f"{name} is outside bounds")
    return value


def _identity(value: object, name: str) -> str:
    text = _exact_text(value, name)
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{name} is malformed")
    return text


def _repository(value: object) -> str:
    text = _exact_text(value, "repository")
    if not _REPOSITORY_RE.fullmatch(text):
        raise ValueError("repository is malformed")
    return text


def _sha40(value: object, name: str) -> str:
    text = _exact_text(value, name, maximum=40)
    if not _SHA40_RE.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase SHA-1")
    return text


def _optional_sha40(value: object, name: str) -> str | None:
    return None if value is None else _sha40(value, name)


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise TypeError(f"{name} must be a positive built-in integer")
    return value


def _optional_positive_int(value: object, name: str) -> int | None:
    return None if value is None else _positive_int(value, name)


def _bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a built-in bool")
    return value


def _canonical_strings(values: object, *, name: str, maximum: int, allowed: frozenset[str] | None = None) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    if len(values) > maximum:
        raise ValueError(f"{name} exceeds its bound")
    checked = [_exact_text(value, name) for value in values]
    if allowed is not None and any(value not in allowed for value in checked):
        raise ValueError(f"{name} contains an unsupported value")
    if len(set(checked)) != len(checked):
        raise ValueError(f"{name} contains duplicates")
    return tuple(sorted(checked))


def _labels(values: object) -> tuple[str, ...]:
    labels = _canonical_strings(values, name="lifecycle labels", maximum=MAX_LABELS)
    if any(not _LABEL_RE.fullmatch(item) for item in labels):
        raise ValueError("lifecycle label is malformed")
    return labels


def _detail(value: object) -> str:
    if type(value) is not str:
        return "lifecycle admission detail unavailable"
    return _CONTROL_RE.sub(" ", value)[:MAX_DETAIL_LENGTH]


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(prefix: str, payload: object) -> str:
    return f"{prefix}:{hashlib.sha256(_canonical_bytes(payload)).hexdigest()}"


def _bounded(payload: object, maximum: int, name: str) -> None:
    if len(_canonical_bytes(payload)) > maximum:
        raise ValueError(f"{name} exceeds its serialized bound")


@dataclass(frozen=True, slots=True)
class LifecycleMutationAuthorization:
    schema_version: str
    repository: str
    issue_number: int
    pull_request_number: int | None
    authorized_mutations: tuple[str, ...]
    expected_source_head: str | None
    expected_base_head: str | None
    expected_pr_state: Literal["draft", "ready", "none"]
    expected_merged: bool
    expected_issue_state: Literal["open", "closed"]
    expected_review_state: Literal["clear", "blocked", "unknown"]
    expected_unresolved_threads: int
    expected_lifecycle_labels: tuple[str, ...]
    observed_at_revision: str
    state: str
    authorizer_id: str
    decision_id: str
    authorization_id: str = ""
    authorization_revision: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported lifecycle authorization schema version")
        _repository(self.repository)
        _positive_int(self.issue_number, "issue_number")
        _optional_positive_int(self.pull_request_number, "pull_request_number")
        object.__setattr__(self, "authorized_mutations", _canonical_strings(self.authorized_mutations, name="authorized mutations", maximum=MAX_MUTATIONS, allowed=MUTATIONS))
        _optional_sha40(self.expected_source_head, "expected_source_head")
        _optional_sha40(self.expected_base_head, "expected_base_head")
        if self.expected_pr_state not in PR_STATES:
            raise ValueError("expected_pr_state is unsupported")
        _bool(self.expected_merged, "expected_merged")
        if self.expected_issue_state not in ISSUE_STATES or self.expected_review_state not in REVIEW_STATES:
            raise ValueError("expected lifecycle state is unsupported")
        if type(self.expected_unresolved_threads) is not int or not 0 <= self.expected_unresolved_threads <= 256:
            raise ValueError("expected_unresolved_threads is outside bounds")
        object.__setattr__(self, "expected_lifecycle_labels", _labels(self.expected_lifecycle_labels))
        _identity(self.observed_at_revision, "observed_at_revision")
        if self.state not in AUTHORIZATION_STATES:
            raise ValueError("authorization state is unsupported")
        _identity(self.authorizer_id, "authorizer_id")
        _identity(self.decision_id, "decision_id")
        expected_id = _digest("lifecycle-authorization", self._payload())
        if self.authorization_id and self.authorization_id != expected_id:
            raise ValueError("authorization_id does not match content")
        object.__setattr__(self, "authorization_id", expected_id)
        expected_revision = _digest("lifecycle-authorization-revision", {"authorization_id": expected_id, "observed_at_revision": self.observed_at_revision, "state": self.state})
        if self.authorization_revision and self.authorization_revision != expected_revision:
            raise ValueError("authorization_revision does not match content")
        object.__setattr__(self, "authorization_revision", expected_revision)
        _bounded(self.to_dict(), MAX_AUTHORIZATION_BYTES, "authorization")

    def _payload(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "repository": self.repository, "issue_number": self.issue_number, "pull_request_number": self.pull_request_number, "authorized_mutations": list(self.authorized_mutations), "expected_source_head": self.expected_source_head, "expected_base_head": self.expected_base_head, "expected_pr_state": self.expected_pr_state, "expected_merged": self.expected_merged, "expected_issue_state": self.expected_issue_state, "expected_review_state": self.expected_review_state, "expected_unresolved_threads": self.expected_unresolved_threads, "expected_lifecycle_labels": list(self.expected_lifecycle_labels), "observed_at_revision": self.observed_at_revision, "state": self.state, "authorizer_id": self.authorizer_id, "decision_id": self.decision_id}

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "authorization_id": self.authorization_id, "authorization_revision": self.authorization_revision}


@dataclass(frozen=True, slots=True)
class LifecycleStateSnapshot:
    repository: str
    issue_number: int
    pull_request_number: int | None
    source_head: str | None
    base_head: str | None
    pr_state: Literal["draft", "ready", "none"]
    merged: bool
    issue_state: Literal["open", "closed"]
    review_state: Literal["clear", "blocked", "unknown"]
    unresolved_threads: int
    lifecycle_labels: tuple[str, ...]
    observed_revision: str
    snapshot_id: str = ""

    def __post_init__(self) -> None:
        _repository(self.repository)
        _positive_int(self.issue_number, "issue_number")
        _optional_positive_int(self.pull_request_number, "pull_request_number")
        _optional_sha40(self.source_head, "source_head")
        _optional_sha40(self.base_head, "base_head")
        if self.pr_state not in PR_STATES or self.issue_state not in ISSUE_STATES or self.review_state not in REVIEW_STATES:
            raise ValueError("snapshot lifecycle state is unsupported")
        _bool(self.merged, "merged")
        if type(self.unresolved_threads) is not int or not 0 <= self.unresolved_threads <= 256:
            raise ValueError("unresolved_threads is outside bounds")
        object.__setattr__(self, "lifecycle_labels", _labels(self.lifecycle_labels))
        _identity(self.observed_revision, "observed_revision")
        expected = _digest("lifecycle-state-snapshot", self._payload())
        if self.snapshot_id and self.snapshot_id != expected:
            raise ValueError("snapshot_id does not match content")
        object.__setattr__(self, "snapshot_id", expected)
        _bounded(self.to_dict(), MAX_SNAPSHOT_BYTES, "snapshot")

    def _payload(self) -> dict[str, object]:
        return {"repository": self.repository, "issue_number": self.issue_number, "pull_request_number": self.pull_request_number, "source_head": self.source_head, "base_head": self.base_head, "pr_state": self.pr_state, "merged": self.merged, "issue_state": self.issue_state, "review_state": self.review_state, "unresolved_threads": self.unresolved_threads, "lifecycle_labels": list(self.lifecycle_labels), "observed_revision": self.observed_revision}

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "snapshot_id": self.snapshot_id}


@dataclass(frozen=True, slots=True)
class LifecycleMutationAdmissionResult:
    requested_mutation: str
    admitted: bool
    status: AdmissionStatus
    reason_codes: tuple[str, ...]
    details: tuple[str, ...]
    authorization_id: str
    snapshot_id: str
    result_id: str = field(default="")

    def __post_init__(self) -> None:
        if self.requested_mutation not in MUTATIONS:
            raise ValueError("requested mutation is unsupported")
        _bool(self.admitted, "admitted")
        if type(self.status) is not AdmissionStatus:
            raise TypeError("status must be AdmissionStatus")
        object.__setattr__(self, "reason_codes", _canonical_strings(self.reason_codes, name="reason codes", maximum=MAX_REASONS, allowed=REASON_CODES))
        if type(self.details) is not tuple or len(self.details) > MAX_DETAILS:
            raise TypeError("details must be a bounded exact tuple")
        object.__setattr__(self, "details", tuple(_detail(item) for item in self.details))
        _exact_text(self.authorization_id, "authorization_id")
        _exact_text(self.snapshot_id, "snapshot_id")
        if self.admitted != (self.status is AdmissionStatus.ADMITTED and not self.reason_codes):
            raise ValueError("admitted, status, and reasons are inconsistent")
        expected = _digest("lifecycle-admission-result", self._payload())
        if self.result_id and self.result_id != expected:
            raise ValueError("result_id does not match content")
        object.__setattr__(self, "result_id", expected)
        _bounded(self.to_dict(), MAX_RESULT_BYTES, "result")

    def _payload(self) -> dict[str, object]:
        return {"requested_mutation": self.requested_mutation, "admitted": self.admitted, "status": self.status.value, "reason_codes": list(self.reason_codes), "details": list(self.details), "authorization_id": self.authorization_id, "snapshot_id": self.snapshot_id}

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "result_id": self.result_id}


def evaluate_lifecycle_mutation(authorization: object, snapshot: object, requested_mutation: object) -> LifecycleMutationAdmissionResult:
    if type(authorization) is not LifecycleMutationAuthorization:
        raise TypeError("authorization must be LifecycleMutationAuthorization")
    if type(snapshot) is not LifecycleStateSnapshot:
        raise TypeError("snapshot must be LifecycleStateSnapshot")
    mutation = _exact_text(requested_mutation, "requested_mutation")
    if mutation not in MUTATIONS:
        raise ValueError("requested mutation is unsupported")
    reasons: list[str] = []
    details: list[str] = []

    def mismatch(reason: str, detail: str) -> None:
        if reason not in reasons:
            reasons.append(reason)
            details.append(detail)

    if authorization.state != "authorized":
        mismatch("authorization-not-authorized", "authorization state is not authorized")
    if authorization.observed_at_revision != snapshot.observed_revision:
        mismatch("authorization-stale", "authorization freshness revision does not match snapshot")
    if mutation not in authorization.authorized_mutations:
        mismatch("authorization-mutation-not-permitted", "requested mutation is not explicitly authorized")
    precondition_met = {"mark-ready": snapshot.pr_state == "draft" and not snapshot.merged, "mark-draft": snapshot.pr_state == "ready" and not snapshot.merged, "merge": snapshot.pr_state == "ready" and not snapshot.merged, "close-issue": snapshot.issue_state == "open", "reopen-issue": snapshot.issue_state == "closed", "add-lifecycle-label": True, "remove-lifecycle-label": True, "replace-lifecycle-labels": True}[mutation]
    if not precondition_met:
        mismatch("mutation-precondition-not-met", "current state cannot admit the requested mutation")
    comparisons = ((authorization.repository, snapshot.repository, "identity-repository-mismatch", "repository identity changed"), (authorization.issue_number, snapshot.issue_number, "identity-issue-mismatch", "issue identity changed"), (authorization.pull_request_number, snapshot.pull_request_number, "identity-pull-request-mismatch", "pull request identity changed"), (authorization.expected_source_head, snapshot.source_head, "pull-request-head-changed", "source head changed"), (authorization.expected_base_head, snapshot.base_head, "pull-request-base-changed", "base head changed"), (authorization.expected_pr_state, snapshot.pr_state, "pull-request-ready-state-changed", "Draft or Ready state changed"), (authorization.expected_merged, snapshot.merged, "pull-request-merged-state-changed", "merged state changed"), (authorization.expected_issue_state, snapshot.issue_state, "issue-state-changed", "issue state changed"), (authorization.expected_review_state, snapshot.review_state, "review-state-changed", "review state changed"), (authorization.expected_unresolved_threads, snapshot.unresolved_threads, "review-thread-state-changed", "unresolved review thread count changed"), (authorization.expected_lifecycle_labels, snapshot.lifecycle_labels, "lifecycle-label-state-changed", "lifecycle label state changed"))
    for expected, observed, reason, detail in comparisons:
        if expected != observed:
            mismatch(reason, detail)
    if reasons:
        status = AdmissionStatus.STALE if any(reason.endswith("-changed") or reason == "authorization-stale" for reason in reasons) else AdmissionStatus.BLOCKED
        return LifecycleMutationAdmissionResult(mutation, False, status, tuple(reasons), tuple(details), authorization.authorization_id, snapshot.snapshot_id)
    return LifecycleMutationAdmissionResult(mutation, True, AdmissionStatus.ADMITTED, (), (), authorization.authorization_id, snapshot.snapshot_id)
