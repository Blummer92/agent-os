"""Bounded, read-only Sprint evidence collection for explicitly supplied candidates.

Implements the provider half of the merged
``01_Shared_Standards/github/sprint-evidence-ingestion-contract.md`` (#376).
This module owns connected reads, same-invocation repository identity proof,
fixed bounds, pagination validation with positive terminal proof, permission and
quota classification, the single explicitly safe retry, and source/PR-head
movement detection.

It reuses the canonical provider primitives rather than restating them:
``TrustedRepositoryIdentity`` and ``TransportResponse`` from :mod:`.models`,
``parse_link_header`` plus the ``PaginationDiagnosticError`` kind vocabulary from
:mod:`.pagination`, ``issue_source_revision`` from :mod:`.revision`, and
``GitHubTransportError`` from :mod:`.transport`. The canonical
``pagination.validated_next_page`` accepts only ``/issues`` endpoints, so
continuation checks here apply the identical rule set through an
endpoint-parameterised allow list built from that same canonical parser.

The collector performs reads only. It never writes, discovers candidates, polls,
schedules, persists state, or authorizes execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Protocol, Sequence
from urllib.parse import parse_qsl, urlparse

from .models import TransportResponse, TrustedRepositoryIdentity
from .pagination import PaginationDiagnosticError, parse_link_header
from .revision import issue_source_revision
from .transport import GitHubTransportError

SPRINT_EVIDENCE_CONTRACT_VERSION = "0.1.0"
SUPPORTED_REPORTING_SCHEMA_VERSIONS = frozenset({"0.1.0"})

# The accepted reporting schema models one to three lanes, so a bounded
# collection can never carry more than three explicitly supplied candidates.
MAX_SUPPORTED_CANDIDATES = 3
MAX_SUPPORTED_PAGES = 10
MAX_SUPPORTED_PAGE_SIZE = 100
MAX_SUPPORTED_EVIDENCE_ITEMS = 300

EVIDENCE_MODE = "connected-read-only"

_API_HOST = "api.github.com"
_INSTALLATION_REPOSITORIES_PATH = "/installation/repositories"
# Mirrors the canonical owner/name form enforced by TrustedRepositoryIdentity.
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

_SAFE_TRANSIENT_RETRY_ATTRIBUTE = "safe_transient_retry"

#: Fixed, non-sensitive reason vocabulary. Reason evidence never contains
#: tokens, URLs, raw response bodies, or unbounded exception text.
SPRINT_EVIDENCE_REASON_CODES = frozenset(
    {
        "blockers:unknown",
        "bounds:candidates-exceeded",
        "bounds:items-exceeded",
        "bounds:pages-exceeded",
        "candidate:closed",
        "checks:unknown",
        "dependencies:unknown",
        "evidence:conflicting",
        "evidence:stale",
        "files:unknown",
        "pagination:continuation-rejected",
        "pagination:incomplete",
        "pagination:terminal-proof-absent",
        "permission:denied",
        "pull-request:ambiguous",
        "pull-request:base-changed",
        "pull-request:head-changed",
        "pull-request:none-linked",
        "quota:exhausted-first-page",
        "quota:exhausted-later-page",
        "repository:fork-ambiguous",
        "repository:id-mismatch",
        "repository:identity-unverified",
        "repository:name-mismatch",
        "retry:safe-retry-exhausted",
        "retry:unsafe-signal",
        "schema:unsupported-version",
        "source:malformed",
        "source:mutated",
        "source:unavailable",
    }
)

_RESULT_STATUSES = frozenset(
    {
        "complete",
        "incomplete",
        "denied",
        "exhausted",
        "unavailable",
        "malformed",
        "not-retrieved",
    }
)
_PERMISSION_STATUSES = frozenset({"granted", "denied", "unknown"})
_PAGINATION_STATUSES = frozenset(
    {"complete", "incomplete", "not-applicable", "unverified"}
)
_FRESHNESS_VALUES = ("conflicting", "stale", "incomplete", "current")

# Lane facts, not evidence gaps: a proven-closed candidate and a proven absence
# of linked pull requests are complete evidence about an explicit state.
_FRESHNESS_NEUTRAL_REASONS = frozenset(
    {"candidate:closed", "pull-request:none-linked"}
)
_STALE_REASONS = frozenset(
    {"source:mutated", "pull-request:head-changed", "pull-request:base-changed"}
)
_CONFLICTING_REASONS = frozenset({"evidence:conflicting"})

_FAILING_CONCLUSIONS = frozenset(
    {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}
)
_PASSING_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})


class SprintEvidenceRequestError(ValueError):
    """Fail-closed request rejection carrying one bounded reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        if reason_code not in SPRINT_EVIDENCE_REASON_CODES:
            raise ValueError("unknown sprint evidence reason code")
        super().__init__(message)
        self.reason_code = reason_code


def _reject(reason_code: str, message: str) -> None:
    raise SprintEvidenceRequestError(reason_code, message)


def _require_positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _require_timestamp(value: object, name: str) -> str:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise ValueError(f"{name} must be RFC3339 UTC")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError(f"{name} must be RFC3339 UTC") from error
    return value


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def _bounded_reasons(reasons: Sequence[str]) -> tuple[str, ...]:
    collected = tuple(reasons)
    for reason in collected:
        if reason not in SPRINT_EVIDENCE_REASON_CODES:
            raise ValueError("unknown sprint evidence reason code")
    return tuple(sorted(set(collected)))


@dataclass(frozen=True, slots=True)
class SprintEvidenceLimits:
    """Fixed collection bounds frozen before any connected read."""

    max_candidates: int
    max_pages: int
    page_size: int
    max_evidence_items: int

    def __post_init__(self) -> None:
        _require_positive_int(self.max_candidates, "max_candidates")
        _require_positive_int(self.max_pages, "max_pages")
        _require_positive_int(self.page_size, "page_size")
        _require_positive_int(self.max_evidence_items, "max_evidence_items")
        if self.max_candidates > MAX_SUPPORTED_CANDIDATES:
            _reject(
                "bounds:candidates-exceeded",
                "max_candidates exceeds the supported bound",
            )
        if self.max_pages > MAX_SUPPORTED_PAGES:
            _reject("bounds:pages-exceeded", "max_pages exceeds the supported bound")
        if self.page_size > MAX_SUPPORTED_PAGE_SIZE:
            _reject("bounds:items-exceeded", "page_size exceeds the supported bound")
        if self.max_evidence_items > MAX_SUPPORTED_EVIDENCE_ITEMS:
            _reject(
                "bounds:items-exceeded",
                "max_evidence_items exceeds the supported bound",
            )


@dataclass(frozen=True, slots=True)
class SprintEvidenceRequest:
    """Explicitly supplied collection inputs, validated before any read."""

    repository: str
    repository_id: int
    base_branch: str
    candidates: tuple[int, ...]
    sprint_id: str
    correlation_id: str
    collected_at: str
    reporting_schema_version: str
    limits: SprintEvidenceLimits

    def __post_init__(self) -> None:
        if not isinstance(self.repository, str) or not _REPOSITORY_RE.fullmatch(
            self.repository
        ):
            raise ValueError("repository must use owner/name form")
        _require_positive_int(self.repository_id, "repository_id")
        _require_text(self.base_branch, "base_branch")
        _require_text(self.sprint_id, "sprint_id")
        _require_text(self.correlation_id, "correlation_id")
        _require_timestamp(self.collected_at, "collected_at")
        if not isinstance(self.limits, SprintEvidenceLimits):
            raise TypeError("limits must be SprintEvidenceLimits")
        if self.reporting_schema_version not in SUPPORTED_REPORTING_SCHEMA_VERSIONS:
            _reject(
                "schema:unsupported-version",
                "reporting schema version is not supported",
            )
        if not isinstance(self.candidates, tuple):
            raise TypeError("candidates must be a tuple of issue numbers")
        if not self.candidates:
            raise ValueError("candidates must be explicitly supplied")
        for candidate in self.candidates:
            _require_positive_int(candidate, "candidate issue number")
        if len(set(self.candidates)) != len(self.candidates):
            raise ValueError("candidates must be unique")
        if len(self.candidates) > self.limits.max_candidates:
            _reject(
                "bounds:candidates-exceeded",
                "supplied candidate count exceeds the frozen bound",
            )

    @property
    def repository_key(self) -> str:
        return self.repository.lower()


class SprintEvidenceReader(Protocol):
    """Bounded read-only port. Every method returns one transport response.

    Implementations perform reads only. No write, mutation, discovery, polling,
    scheduling, or persistence method exists on this port.
    """

    def get_installation_repositories(
        self, *, page: int, per_page: int
    ) -> TransportResponse:
        """Return one bounded installation-repository page for identity proof."""

    def get_issue(self, *, repository: str, issue_number: int) -> TransportResponse:
        """Return one issue record."""

    def get_linked_pull_requests(
        self, *, repository: str, issue_number: int, page: int, per_page: int
    ) -> TransportResponse:
        """Return one bounded page of pull requests linked to the issue."""

    def get_pull_request(
        self, *, repository: str, pull_number: int
    ) -> TransportResponse:
        """Return one pull-request record."""

    def get_pull_request_files(
        self, *, repository: str, pull_number: int, page: int, per_page: int
    ) -> TransportResponse:
        """Return one bounded page of changed-file records."""

    def get_check_runs(
        self, *, repository: str, ref: str, page: int, per_page: int
    ) -> TransportResponse:
        """Return one bounded page of check runs for an exact ref."""


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Provider-owned source evidence, richer than the reporting projection."""

    object_type: str
    object_id: str
    repository: str
    retrieved_at: str
    updated_at: str | None
    result_status: str
    permission_status: str
    pagination_status: str
    terminal_page_proven: bool
    pages_read: int
    source_revision: str | None = None
    evidence_digest: str | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.object_type not in {"issue", "pull-request", "check", "file-list"}:
            raise ValueError("unsupported source object type")
        if self.result_status not in _RESULT_STATUSES:
            raise ValueError("unsupported result status")
        if self.permission_status not in _PERMISSION_STATUSES:
            raise ValueError("unsupported permission status")
        if self.pagination_status not in _PAGINATION_STATUSES:
            raise ValueError("unsupported pagination status")
        object.__setattr__(self, "reason_codes", _bounded_reasons(self.reason_codes))


@dataclass(frozen=True, slots=True)
class CheckEvidence:
    name: str
    status: str
    conclusion: str | None


@dataclass(frozen=True, slots=True)
class PullRequestEvidence:
    """Evidence bound to repository, PR number, exact base, and exact head."""

    number: int
    state: str | None
    base_ref: str | None
    head_sha: str | None
    created_at: str | None
    updated_at: str | None
    changed_files: tuple[str, ...] | None
    checks: tuple[CheckEvidence, ...] | None
    checks_status: str
    base_branch_matches_request: bool


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    """Bounded evidence for exactly one explicitly supplied candidate."""

    issue_number: int
    title: str | None
    state: str | None
    labels: tuple[str, ...] | None
    created_at: str | None
    updated_at: str | None
    closed_at: str | None
    dependencies: tuple[str, ...] | None
    blockers: tuple[str, ...] | None
    source_revision: str | None
    linked_pull_request_status: str
    pull_request: PullRequestEvidence | None
    freshness: str
    reason_codes: tuple[str, ...]
    sources: tuple[SourceRecord, ...]

    def __post_init__(self) -> None:
        if self.freshness not in _FRESHNESS_VALUES:
            raise ValueError("unsupported freshness value")
        object.__setattr__(self, "reason_codes", _bounded_reasons(self.reason_codes))


@dataclass(frozen=True, slots=True)
class RepositoryIdentityEvidence:
    """Same-invocation repository identity proof."""

    repository: str
    repository_id: int
    verified: bool
    pages_read: int
    terminal_page_proven: bool
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_codes", _bounded_reasons(self.reason_codes))


@dataclass(frozen=True, slots=True)
class SprintEvidenceCollection:
    """Immutable bounded evidence from exactly one collection invocation."""

    contract_version: str
    reporting_schema_version: str
    sprint_id: str
    correlation_id: str
    repository: str
    repository_id: int
    base_branch: str
    collected_at: str
    requested_candidates: tuple[int, ...]
    identity: RepositoryIdentityEvidence
    candidates: tuple[CandidateEvidence, ...]
    freshness: str
    manual_review_reasons: tuple[str, ...]
    reads_attempted: int
    reads_stopped: int
    pages_read: int
    retry_count: int
    evidence_mode: str = field(default=EVIDENCE_MODE, init=False)
    execution_authorized: bool = field(default=False, init=False)
    side_effects_performed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.freshness not in _FRESHNESS_VALUES:
            raise ValueError("unsupported freshness value")
        object.__setattr__(
            self, "manual_review_reasons", _bounded_reasons(self.manual_review_reasons)
        )


def _safe_transient_signal(error: BaseException) -> bool:
    """Only an explicit ``safe_transient_retry is True`` marker permits a retry."""

    return getattr(error, _SAFE_TRANSIENT_RETRY_ATTRIBUTE, False) is True


def _quota_reason(page: int) -> str:
    return "quota:exhausted-first-page" if page <= 1 else "quota:exhausted-later-page"


def _status_reason(status: int, *, page: int) -> str:
    if status in {401, 403}:
        return "permission:denied"
    if status == 429:
        return _quota_reason(page)
    if status == 404:
        return "source:unavailable"
    return "source:malformed"


def _query_values(query: str) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for name, value in parse_qsl(query, keep_blank_values=True):
        values.setdefault(name, []).append(value)
    return values


def _validated_next_page(
    link_header: str | None,
    *,
    allowed_paths: frozenset[str],
    current_page: int,
    per_page: int,
    state: str | None,
) -> tuple[int | None, bool]:
    """Apply the canonical continuation rules to an endpoint allow list."""

    relations = parse_link_header(link_header)
    next_url = relations.get("next")
    if next_url is None:
        return None, (link_header is not None) or (current_page == 1)

    parsed = urlparse(next_url)
    if parsed.scheme != "https":
        raise PaginationDiagnosticError(
            "pagination:next-scheme", "next link must use HTTPS"
        )
    if parsed.netloc != _API_HOST:
        raise PaginationDiagnosticError(
            "pagination:next-host", "next link changed the API authority"
        )
    if parsed.path not in allowed_paths:
        raise PaginationDiagnosticError(
            "pagination:next-path", "next link changed repository or endpoint"
        )

    query = _query_values(parsed.query)
    page_values = query.get("page")
    if page_values is None:
        raise PaginationDiagnosticError(
            "pagination:next-page-missing", "next link is missing page"
        )
    if len(page_values) != 1:
        raise PaginationDiagnosticError(
            "pagination:next-page-ambiguous", "next link has multiple page values"
        )
    try:
        page = int(page_values[0])
    except (TypeError, ValueError) as error:
        raise PaginationDiagnosticError(
            "pagination:next-page-invalid", "next link has invalid page"
        ) from error
    if page <= current_page:
        raise PaginationDiagnosticError(
            "pagination:next-page-non-advancing", "next link does not advance"
        )

    linked_per_page = query.get("per_page")
    if linked_per_page is not None:
        if len(linked_per_page) != 1:
            raise PaginationDiagnosticError(
                "pagination:next-per-page-ambiguous",
                "next link has multiple per_page values",
            )
        if linked_per_page[0]:
            try:
                parsed_per_page = int(linked_per_page[0])
            except (TypeError, ValueError) as error:
                raise PaginationDiagnosticError(
                    "pagination:next-per-page-invalid",
                    "next link has invalid per_page",
                ) from error
            if parsed_per_page != per_page:
                raise PaginationDiagnosticError(
                    "pagination:next-per-page-changed",
                    "next link changed the requested page size",
                )

    linked_state = query.get("state")
    if linked_state is not None:
        if len(linked_state) != 1:
            raise PaginationDiagnosticError(
                "pagination:next-state-ambiguous",
                "next link has multiple state values",
            )
        if linked_state[0] and linked_state[0] != state:
            raise PaginationDiagnosticError(
                "pagination:next-state-changed",
                "next link changed the requested state",
            )

    return page, False


def _mapping(payload: object) -> Mapping[str, object] | None:
    return payload if isinstance(payload, Mapping) else None


def _sequence(payload: object) -> Sequence[object] | None:
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return payload
    return None


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _string_tuple(value: object) -> tuple[str, ...] | None:
    items = _sequence(value)
    if items is None:
        return None
    collected: list[str] = []
    for item in items:
        text = _text_or_none(item.get("name") if isinstance(item, Mapping) else item)
        if text is None:
            return None
        collected.append(text)
    return tuple(collected)


def _result_for(failure: Sequence[str]) -> str:
    if "permission:denied" in failure:
        return "denied"
    if any(reason.startswith("quota:") for reason in failure):
        return "exhausted"
    if "source:malformed" in failure:
        return "malformed"
    return "unavailable"


@dataclass(frozen=True, slots=True)
class _PagedRead:
    items: tuple[object, ...]
    pages_read: int
    terminal_page_proven: bool
    complete: bool
    reason_codes: tuple[str, ...]
    permission_status: str

    @property
    def pagination_status(self) -> str:
        return "complete" if self.complete else "incomplete"


class _Collector:
    """One bounded collection pass with a single shared safe-retry budget."""

    def __init__(
        self, request: SprintEvidenceRequest, reader: SprintEvidenceReader
    ) -> None:
        self.request = request
        self.reader = reader
        self._retry_budget = 1
        self.retry_count = 0
        self.reads_attempted = 0
        self.reads_stopped = 0
        self.pages_read = 0

    def read(
        self, call, *, attempt_page: int = 1, **kwargs
    ) -> tuple[TransportResponse | None, tuple[str, ...]]:
        response, reasons = self._attempt(call, attempt_page=attempt_page, **kwargs)
        if response is None:
            self.reads_stopped += 1
        return response, reasons

    def _attempt(
        self, call, *, attempt_page: int, **kwargs
    ) -> tuple[TransportResponse | None, tuple[str, ...]]:
        self.reads_attempted += 1
        try:
            response = call(**kwargs)
        except GitHubTransportError as error:
            kind = getattr(error, "kind", "api-error")
            if kind != "api-error":
                return None, (self._classify(kind, page=attempt_page),)
            if not _safe_transient_signal(error):
                return None, ("retry:unsafe-signal", "source:unavailable")
            if self._retry_budget < 1:
                return None, ("retry:safe-retry-exhausted", "source:unavailable")
            self._retry_budget -= 1
            self.retry_count += 1
            self.reads_attempted += 1
            try:
                response = call(**kwargs)
            except GitHubTransportError as retry_error:
                retry_kind = getattr(retry_error, "kind", "api-error")
                if retry_kind == "api-error":
                    return None, ("retry:safe-retry-exhausted", "source:unavailable")
                return None, (
                    "retry:safe-retry-exhausted",
                    self._classify(retry_kind, page=attempt_page),
                )
        if not isinstance(response, TransportResponse):
            return None, ("source:malformed",)
        if response.status != 200:
            return None, (_status_reason(response.status, page=attempt_page),)
        return response, ()

    @staticmethod
    def _classify(kind: str, *, page: int) -> str:
        if kind == "permission-denied":
            return "permission:denied"
        if kind == "rate-limited":
            return _quota_reason(page)
        if kind == "malformed-response":
            return "source:malformed"
        return "source:unavailable"

    def paged(
        self, call, *, allowed_paths: frozenset[str], state: str | None = None, **kwargs
    ) -> _PagedRead:
        limits = self.request.limits
        items: list[object] = []
        reasons: list[str] = []
        permission_status = "granted"
        page = 1
        pages_read = 0
        terminal_proven = False
        complete = True

        while True:
            if pages_read >= limits.max_pages:
                reasons.extend(
                    ("bounds:pages-exceeded", "pagination:terminal-proof-absent")
                )
                complete = False
                break

            response, failure = self.read(
                call,
                attempt_page=page,
                page=page,
                per_page=limits.page_size,
                **kwargs,
            )
            if response is None:
                reasons.extend(failure)
                permission_status = (
                    "denied" if "permission:denied" in failure else "unknown"
                )
                complete = False
                break

            pages_read += 1
            self.pages_read += 1
            page_items = self._page_items(response.payload)
            if page_items is None:
                reasons.append("source:malformed")
                complete = False
                break
            items.extend(page_items)
            if len(items) > limits.max_evidence_items:
                reasons.append("bounds:items-exceeded")
                complete = False
                break

            headers = {key.lower(): value for key, value in response.headers.items()}
            try:
                next_page, terminal_proven = _validated_next_page(
                    headers.get("link"),
                    allowed_paths=allowed_paths,
                    current_page=page,
                    per_page=limits.page_size,
                    state=state,
                )
            except PaginationDiagnosticError:
                reasons.append("pagination:continuation-rejected")
                terminal_proven = False
                complete = False
                break

            if next_page is None:
                break
            page = next_page

        if complete and not terminal_proven:
            reasons.append("pagination:terminal-proof-absent")
            complete = False
        if not complete:
            reasons.append("pagination:incomplete")

        return _PagedRead(
            items=tuple(items),
            pages_read=pages_read,
            terminal_page_proven=terminal_proven,
            complete=complete,
            reason_codes=_bounded_reasons(reasons),
            permission_status=permission_status,
        )

    @staticmethod
    def _page_items(payload: object) -> Sequence[object] | None:
        items = _sequence(payload)
        if items is not None:
            return items
        mapping = _mapping(payload)
        if mapping is None:
            return None
        for key in ("repositories", "check_runs", "items"):
            if key in mapping:
                return _sequence(mapping[key])
        return None


def collect_sprint_evidence(
    request: SprintEvidenceRequest, reader: SprintEvidenceReader
) -> SprintEvidenceCollection:
    """Collect bounded, read-only evidence for explicitly supplied candidates.

    Limits are validated by :class:`SprintEvidenceRequest` before construction,
    so every bound is frozen before the first connected read. Repository
    identity is proven in this same invocation before any candidate is read; an
    unverified identity stops collection and attempts no candidate read.
    """

    if not isinstance(request, SprintEvidenceRequest):
        raise TypeError("request must be SprintEvidenceRequest")
    if reader is None:
        raise TypeError("reader is required")

    collector = _Collector(request, reader)
    identity = _verify_repository_identity(collector)

    if identity.verified:
        trusted = TrustedRepositoryIdentity(
            repository=request.repository, repository_id=request.repository_id
        )
        candidates = tuple(
            _collect_candidate(collector, trusted, number)
            for number in request.candidates
        )
    else:
        candidates = tuple(
            _unread_candidate(request, number, identity.reason_codes)
            for number in request.candidates
        )

    freshness = _aggregate_freshness(identity, candidates)
    reasons: list[str] = list(identity.reason_codes)
    for candidate in candidates:
        reasons.extend(candidate.reason_codes)
    if freshness == "stale":
        reasons.append("evidence:stale")
    elif freshness == "conflicting":
        reasons.append("evidence:conflicting")

    return SprintEvidenceCollection(
        contract_version=SPRINT_EVIDENCE_CONTRACT_VERSION,
        reporting_schema_version=request.reporting_schema_version,
        sprint_id=request.sprint_id,
        correlation_id=request.correlation_id,
        repository=request.repository,
        repository_id=request.repository_id,
        base_branch=request.base_branch,
        collected_at=request.collected_at,
        requested_candidates=request.candidates,
        identity=identity,
        candidates=candidates,
        freshness=freshness,
        manual_review_reasons=_bounded_reasons(reasons),
        reads_attempted=collector.reads_attempted,
        reads_stopped=collector.reads_stopped,
        pages_read=collector.pages_read,
        retry_count=collector.retry_count,
    )


def _verify_repository_identity(collector: _Collector) -> RepositoryIdentityEvidence:
    request = collector.request
    read = collector.paged(
        collector.reader.get_installation_repositories,
        allowed_paths=frozenset({_INSTALLATION_REPOSITORIES_PATH}),
    )

    def unverified(*codes: str) -> RepositoryIdentityEvidence:
        return RepositoryIdentityEvidence(
            repository=request.repository,
            repository_id=request.repository_id,
            verified=False,
            pages_read=read.pages_read,
            terminal_page_proven=read.terminal_page_proven,
            reason_codes=_bounded_reasons(
                (*read.reason_codes, "repository:identity-unverified", *codes)
            ),
        )

    if not read.complete:
        return unverified()

    entries = [entry for entry in read.items if isinstance(entry, Mapping)]
    if len(entries) != len(read.items):
        return unverified("source:malformed")

    name_matches = [
        entry
        for entry in entries
        if (_text_or_none(entry.get("full_name")) or "").lower()
        == request.repository_key
    ]
    if not name_matches:
        return unverified("repository:name-mismatch")
    if len(name_matches) > 1:
        return unverified()

    entry = name_matches[0]
    entry_id = entry.get("id")
    if (
        not isinstance(entry_id, int)
        or isinstance(entry_id, bool)
        or entry_id != request.repository_id
    ):
        return unverified("repository:id-mismatch")
    if any(other is not entry and other.get("id") == entry_id for other in entries):
        return unverified()
    if entry.get("fork") is not False or "parent" in entry or "source" in entry:
        return unverified("repository:fork-ambiguous")

    return RepositoryIdentityEvidence(
        repository=request.repository,
        repository_id=request.repository_id,
        verified=True,
        pages_read=read.pages_read,
        terminal_page_proven=read.terminal_page_proven,
        reason_codes=read.reason_codes,
    )


def _allowed_paths(trusted: TrustedRepositoryIdentity, suffix: str) -> frozenset[str]:
    return frozenset(
        {
            f"/repos/{trusted.repository}/{suffix}",
            f"/repositories/{trusted.repository_id}/{suffix}",
        }
    )


def _issue_source(
    request: SprintEvidenceRequest,
    number: int,
    *,
    result_status: str,
    permission_status: str,
    updated_at: str | None = None,
    revision: str | None = None,
    reasons: tuple[str, ...] = (),
) -> SourceRecord:
    return SourceRecord(
        object_type="issue",
        object_id=str(number),
        repository=request.repository,
        retrieved_at=request.collected_at,
        updated_at=updated_at,
        result_status=result_status,
        permission_status=permission_status,
        pagination_status="not-applicable",
        terminal_page_proven=True,
        pages_read=0,
        source_revision=revision,
        evidence_digest=revision,
        reason_codes=reasons,
    )


def _pull_request_source(
    request: SprintEvidenceRequest,
    pull_number: int,
    *,
    result_status: str,
    permission_status: str,
    updated_at: str | None = None,
    revision: str | None = None,
    reasons: tuple[str, ...] = (),
) -> SourceRecord:
    return SourceRecord(
        object_type="pull-request",
        object_id=str(pull_number),
        repository=request.repository,
        retrieved_at=request.collected_at,
        updated_at=updated_at,
        result_status=result_status,
        permission_status=permission_status,
        pagination_status="not-applicable",
        terminal_page_proven=True,
        pages_read=0,
        source_revision=revision,
        evidence_digest=revision,
        reason_codes=reasons,
    )


def _blank_candidate(
    number: int,
    *,
    reasons: Sequence[str],
    sources: Sequence[SourceRecord],
) -> CandidateEvidence:
    collected = (
        *reasons,
        "blockers:unknown",
        "checks:unknown",
        "dependencies:unknown",
        "files:unknown",
    )
    return CandidateEvidence(
        issue_number=number,
        title=None,
        state=None,
        labels=None,
        created_at=None,
        updated_at=None,
        closed_at=None,
        dependencies=None,
        blockers=None,
        source_revision=None,
        linked_pull_request_status="unknown",
        pull_request=None,
        freshness=_candidate_freshness(collected),
        reason_codes=collected,
        sources=tuple(sources),
    )


def _unread_candidate(
    request: SprintEvidenceRequest, number: int, reasons: tuple[str, ...]
) -> CandidateEvidence:
    """Record an honest not-retrieved candidate when identity is unproven."""

    source = SourceRecord(
        object_type="issue",
        object_id=str(number),
        repository=request.repository,
        retrieved_at=request.collected_at,
        updated_at=None,
        result_status="not-retrieved",
        permission_status="unknown",
        pagination_status="unverified",
        terminal_page_proven=False,
        pages_read=0,
        reason_codes=reasons,
    )
    return _blank_candidate(number, reasons=reasons, sources=(source,))


def _issue_revision(issue: Mapping[str, object] | None) -> str | None:
    if issue is None:
        return None
    try:
        return issue_source_revision(issue)
    except (TypeError, ValueError):
        return None


def _collect_candidate(
    collector: _Collector, trusted: TrustedRepositoryIdentity, number: int
) -> CandidateEvidence:
    request = collector.request
    reader = collector.reader

    response, failure = collector.read(
        reader.get_issue, repository=request.repository, issue_number=number
    )
    if response is None:
        source = _issue_source(
            request,
            number,
            result_status=_result_for(failure),
            permission_status="denied" if "permission:denied" in failure else "unknown",
            reasons=tuple(failure),
        )
        return _blank_candidate(number, reasons=failure, sources=(source,))

    issue = _mapping(response.payload)
    revision = _issue_revision(issue)
    if issue is None or revision is None:
        source = _issue_source(
            request,
            number,
            result_status="malformed",
            permission_status="granted",
            reasons=("source:malformed",),
        )
        return _blank_candidate(
            number, reasons=("source:malformed",), sources=(source,)
        )

    reasons: list[str] = []
    sources: list[SourceRecord] = []
    if _text_or_none(issue.get("state")) == "closed":
        reasons.append("candidate:closed")

    dependencies = _string_tuple(issue.get("dependencies"))
    blockers = _string_tuple(issue.get("blockers"))
    if dependencies is None:
        reasons.append("dependencies:unknown")
    if blockers is None:
        reasons.append("blockers:unknown")

    linked_status, pull_number, linked_reasons, linked_sources = _linked_pull_request(
        collector, trusted, number
    )
    reasons.extend(linked_reasons)
    sources.extend(linked_sources)

    pull_request: PullRequestEvidence | None = None
    if pull_number is not None:
        pull_request, pr_reasons, pr_sources = _collect_pull_request(
            collector, trusted, pull_number
        )
        reasons.extend(pr_reasons)
        sources.extend(pr_sources)
    elif linked_status != "none":
        # Linked-PR evidence is missing rather than proven absent.
        reasons.extend(("files:unknown", "checks:unknown"))

    # Single bounded freshness recheck required by the ingestion contract: the
    # issue is re-read exactly once so source mutation during collection is
    # detected instead of being silently normalized as current.
    recheck, recheck_failure = collector.read(
        reader.get_issue, repository=request.repository, issue_number=number
    )
    if recheck is None:
        reasons.extend(recheck_failure)
        recheck_revision = None
    else:
        recheck_revision = _issue_revision(_mapping(recheck.payload))
        if recheck_revision is None:
            reasons.append("source:malformed")
        elif recheck_revision != revision:
            reasons.append("source:mutated")

    sources.append(
        _issue_source(
            request,
            number,
            result_status="complete" if recheck_revision == revision else "incomplete",
            permission_status="granted",
            updated_at=_text_or_none(issue.get("updated_at")),
            revision=revision,
            reasons=("source:mutated",) if "source:mutated" in reasons else (),
        )
    )

    return CandidateEvidence(
        issue_number=number,
        title=_text_or_none(issue.get("title")),
        state=_text_or_none(issue.get("state")),
        labels=_string_tuple(issue.get("labels")),
        created_at=_text_or_none(issue.get("created_at")),
        updated_at=_text_or_none(issue.get("updated_at")),
        closed_at=_text_or_none(issue.get("closed_at")),
        dependencies=dependencies,
        blockers=blockers,
        source_revision=revision,
        linked_pull_request_status=linked_status,
        pull_request=pull_request,
        freshness=_candidate_freshness(reasons),
        reason_codes=tuple(reasons),
        sources=tuple(sources),
    )


def _linked_pull_request(
    collector: _Collector, trusted: TrustedRepositoryIdentity, number: int
) -> tuple[str, int | None, tuple[str, ...], tuple[SourceRecord, ...]]:
    request = collector.request
    read = collector.paged(
        collector.reader.get_linked_pull_requests,
        allowed_paths=_allowed_paths(trusted, f"issues/{number}/pulls"),
        repository=request.repository,
        issue_number=number,
    )
    source = SourceRecord(
        object_type="pull-request",
        object_id=f"issue-{number}-links",
        repository=request.repository,
        retrieved_at=request.collected_at,
        updated_at=None,
        result_status="complete" if read.complete else "incomplete",
        permission_status=read.permission_status,
        pagination_status=read.pagination_status,
        terminal_page_proven=read.terminal_page_proven,
        pages_read=read.pages_read,
        reason_codes=read.reason_codes,
    )
    if not read.complete:
        return "unknown", None, read.reason_codes, (source,)

    numbers: list[int] = []
    for item in read.items:
        mapping = _mapping(item)
        value = mapping.get("number") if mapping is not None else None
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return "unknown", None, ("source:malformed",), (source,)
        numbers.append(value)

    unique = sorted(set(numbers))
    if not unique:
        return "none", None, ("pull-request:none-linked",), (source,)
    if len(unique) > 1:
        return "ambiguous", None, ("pull-request:ambiguous",), (source,)
    return "resolved", unique[0], (), (source,)


def _head_sha(payload: Mapping[str, object] | None) -> str | None:
    head = _mapping(payload.get("head")) if payload is not None else None
    sha = _text_or_none(head.get("sha")) if head is not None else None
    return sha if sha is not None and _HEAD_SHA_RE.fullmatch(sha) else None


def _base_ref(payload: Mapping[str, object] | None) -> str | None:
    base = _mapping(payload.get("base")) if payload is not None else None
    return _text_or_none(base.get("ref")) if base is not None else None


def _collect_pull_request(
    collector: _Collector, trusted: TrustedRepositoryIdentity, pull_number: int
) -> tuple[PullRequestEvidence | None, tuple[str, ...], tuple[SourceRecord, ...]]:
    request = collector.request
    reader = collector.reader

    response, failure = collector.read(
        reader.get_pull_request,
        repository=request.repository,
        pull_number=pull_number,
    )
    if response is None:
        source = _pull_request_source(
            request,
            pull_number,
            result_status=_result_for(failure),
            permission_status="denied" if "permission:denied" in failure else "unknown",
            reasons=tuple(failure),
        )
        return None, (*failure, "files:unknown", "checks:unknown"), (source,)

    payload = _mapping(response.payload)
    head_sha = _head_sha(payload)
    base_ref = _base_ref(payload)
    if payload is None or head_sha is None or base_ref is None:
        source = _pull_request_source(
            request,
            pull_number,
            result_status="malformed",
            permission_status="granted",
            reasons=("source:malformed",),
        )
        return (
            None,
            ("source:malformed", "files:unknown", "checks:unknown"),
            (source,),
        )

    reasons: list[str] = []
    sources: list[SourceRecord] = []

    files, file_reasons, file_source = _changed_files(collector, trusted, pull_number)
    reasons.extend(file_reasons)
    sources.append(file_source)

    checks, checks_status, check_reasons, check_source = _check_runs(
        collector, trusted, head_sha
    )
    reasons.extend(check_reasons)
    sources.append(check_source)

    # Bounded revalidation of the exact PR head and base after dependent reads.
    recheck, recheck_failure = collector.read(
        reader.get_pull_request,
        repository=request.repository,
        pull_number=pull_number,
    )
    if recheck is None:
        reasons.extend(recheck_failure)
    else:
        recheck_payload = _mapping(recheck.payload)
        recheck_head = _head_sha(recheck_payload)
        recheck_base = _base_ref(recheck_payload)
        if recheck_head is None or recheck_base is None:
            reasons.append("source:malformed")
        else:
            if recheck_head != head_sha:
                reasons.append("pull-request:head-changed")
            if recheck_base != base_ref:
                reasons.append("pull-request:base-changed")

    if base_ref != request.base_branch:
        reasons.append("evidence:conflicting")

    moved = {"pull-request:head-changed", "pull-request:base-changed"} & set(reasons)
    sources.append(
        _pull_request_source(
            request,
            pull_number,
            result_status="incomplete" if moved else "complete",
            permission_status="granted",
            updated_at=_text_or_none(payload.get("updated_at")),
            revision=head_sha,
            reasons=tuple(sorted(moved)),
        )
    )

    evidence = PullRequestEvidence(
        number=pull_number,
        state=_text_or_none(payload.get("state")),
        base_ref=base_ref,
        head_sha=head_sha,
        created_at=_text_or_none(payload.get("created_at")),
        updated_at=_text_or_none(payload.get("updated_at")),
        changed_files=files,
        checks=checks,
        checks_status=checks_status,
        base_branch_matches_request=base_ref == request.base_branch,
    )
    return evidence, tuple(reasons), tuple(sources)


def _changed_files(
    collector: _Collector, trusted: TrustedRepositoryIdentity, pull_number: int
) -> tuple[tuple[str, ...] | None, tuple[str, ...], SourceRecord]:
    request = collector.request
    read = collector.paged(
        collector.reader.get_pull_request_files,
        allowed_paths=_allowed_paths(trusted, f"pulls/{pull_number}/files"),
        repository=request.repository,
        pull_number=pull_number,
    )
    source = SourceRecord(
        object_type="file-list",
        object_id=str(pull_number),
        repository=request.repository,
        retrieved_at=request.collected_at,
        updated_at=None,
        result_status="complete" if read.complete else "incomplete",
        permission_status=read.permission_status,
        pagination_status=read.pagination_status,
        terminal_page_proven=read.terminal_page_proven,
        pages_read=read.pages_read,
        reason_codes=read.reason_codes,
    )
    if not read.complete:
        return None, (*read.reason_codes, "files:unknown"), source

    names = _string_tuple(
        [
            item.get("filename") if isinstance(item, Mapping) else item
            for item in read.items
        ]
    )
    if names is None:
        return None, ("source:malformed", "files:unknown"), source
    return tuple(sorted(set(names))), (), source


def _check_runs(
    collector: _Collector, trusted: TrustedRepositoryIdentity, head_sha: str
) -> tuple[tuple[CheckEvidence, ...] | None, str, tuple[str, ...], SourceRecord]:
    request = collector.request
    read = collector.paged(
        collector.reader.get_check_runs,
        allowed_paths=_allowed_paths(trusted, f"commits/{head_sha}/check-runs"),
        repository=request.repository,
        ref=head_sha,
    )
    source = SourceRecord(
        object_type="check",
        object_id=head_sha,
        repository=request.repository,
        retrieved_at=request.collected_at,
        updated_at=None,
        result_status="complete" if read.complete else "incomplete",
        permission_status=read.permission_status,
        pagination_status=read.pagination_status,
        terminal_page_proven=read.terminal_page_proven,
        pages_read=read.pages_read,
        reason_codes=read.reason_codes,
    )
    if not read.complete:
        return None, "unknown", (*read.reason_codes, "checks:unknown"), source

    checks: list[CheckEvidence] = []
    for item in read.items:
        mapping = _mapping(item)
        name = _text_or_none(mapping.get("name")) if mapping is not None else None
        status = _text_or_none(mapping.get("status")) if mapping is not None else None
        if name is None or status is None:
            return None, "unknown", ("source:malformed", "checks:unknown"), source
        checks.append(
            CheckEvidence(
                name=name,
                status=status,
                conclusion=_text_or_none(mapping.get("conclusion")),
            )
        )

    resolved = tuple(sorted(checks, key=lambda check: (check.name, check.status)))
    status = _checks_status(resolved)
    reasons = ("checks:unknown",) if status == "unknown" else ()
    return resolved, status, reasons, source


def _checks_status(checks: tuple[CheckEvidence, ...]) -> str:
    if not checks:
        # No reported check run is unknown evidence, never a passing result.
        return "unknown"
    if any(check.conclusion in _FAILING_CONCLUSIONS for check in checks):
        return "failing"
    if any(check.status != "completed" for check in checks):
        return "pending"
    if all(check.conclusion in _PASSING_CONCLUSIONS for check in checks):
        return "passing"
    return "unknown"


def _candidate_freshness(reasons: Sequence[str]) -> str:
    present = set(reasons) - _FRESHNESS_NEUTRAL_REASONS
    if present & _CONFLICTING_REASONS:
        return "conflicting"
    if present & _STALE_REASONS:
        return "stale"
    if present:
        return "incomplete"
    return "current"


def _aggregate_freshness(
    identity: RepositoryIdentityEvidence, candidates: Sequence[CandidateEvidence]
) -> str:
    """Fixed precedence: conflicting beats stale, which beats incomplete."""

    if not identity.verified:
        mismatch = {"repository:name-mismatch", "repository:id-mismatch"}
        return "conflicting" if mismatch & set(identity.reason_codes) else "incomplete"
    values = {candidate.freshness for candidate in candidates}
    for value in _FRESHNESS_VALUES:
        if value in values:
            return value
    return "current"
