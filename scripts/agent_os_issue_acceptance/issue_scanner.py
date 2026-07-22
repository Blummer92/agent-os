from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re
from typing import Iterable, Mapping, Protocol, Sequence


REQUIRED_ISSUE_FIELDS = (
    "number",
    "title",
    "state",
    "body",
    "html_url",
    "created_at",
    "updated_at",
    "labels",
)

_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class IssueStateFilter(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    ALL = "all"


class RetrievalStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class RetrievalFinding(str, Enum):
    COMPLETE = "scan-complete"
    PAGE_MISSING_NEXT = "pagination-unknown"
    API_ERROR = "source-inaccessible"
    MISSING_FIELD = "source-partial"
    SOURCE_STATE_MISMATCH = "source-state-mismatch"
    DUPLICATE_ISSUE = "metadata-duplicated-identical"


@dataclass(frozen=True)
class IssueScannerRecord:
    issue_number: int
    title: str
    state: str
    body: str
    labels: tuple[str, ...]
    url: str
    created_at: str
    updated_at: str
    source_revision: str
    closed_at: str | None = None
    state_reason: str | None = None


@dataclass(frozen=True)
class IssueScanPage:
    items: tuple[Mapping[str, object], ...]
    next_page: int | None
    complete: bool = True
    error: str | None = None


@dataclass(frozen=True)
class IssueScanResult:
    status: RetrievalStatus
    records: tuple[IssueScannerRecord, ...] = ()
    findings: tuple[RetrievalFinding, ...] = ()
    reasons: tuple[str, ...] = ()
    page_count: int = 0
    item_count: int = 0
    source_query: str = "state=open"
    requested_state: IssueStateFilter = IssueStateFilter.OPEN
    retrieved_at: str | None = None

    @property
    def complete(self) -> bool:
        return self.status == RetrievalStatus.COMPLETE


class IssuePageSource(Protocol):
    def fetch_page(self, page: int) -> IssueScanPage:
        """Return one page of issue search/list results."""


class _RecordValidationError(ValueError):
    def __init__(self, finding: RetrievalFinding, reason: str) -> None:
        super().__init__(reason)
        self.finding = finding
        self.reason = reason


def scan_issues(
    source: IssuePageSource,
    *,
    requested_state: IssueStateFilter,
    retrieved_at: str | None,
    source_query: str | None = None,
    _allow_missing_retrieved_at: bool = False,
) -> IssueScanResult:
    """Collect deterministic issue evidence for one explicit state filter.

    The scanner is evidence-only. It does not call GitHub directly, mutate issues,
    infer state, read the system clock, or normalize malformed source metadata.
    """
    _validate_requested_state(requested_state)
    _validate_retrieved_at(retrieved_at, allow_none=_allow_missing_retrieved_at)
    resolved_source_query = _validate_source_query(
        source_query if source_query is not None else f"state={requested_state.value}"
    )

    page_number = 1
    page_count = 0
    records: list[IssueScannerRecord] = []
    findings: list[RetrievalFinding] = []
    reasons: list[str] = []
    seen_issue_numbers: set[int] = set()

    while True:
        page = source.fetch_page(page_number)
        page_count += 1

        if page.error:
            findings.append(RetrievalFinding.API_ERROR)
            reasons.append(f"page {page_number}: {page.error}")
            return _incomplete(
                records,
                findings,
                reasons,
                page_count,
                resolved_source_query,
                requested_state,
                retrieved_at,
            )

        if not page.complete:
            findings.append(RetrievalFinding.PAGE_MISSING_NEXT)
            reasons.append(f"page {page_number}: pagination completeness is unknown")
            return _incomplete(
                records,
                findings,
                reasons,
                page_count,
                resolved_source_query,
                requested_state,
                retrieved_at,
            )

        for raw_item in page.items:
            if not isinstance(raw_item, Mapping):
                findings.append(RetrievalFinding.MISSING_FIELD)
                reasons.append("issue record must be a mapping")
                return _incomplete(
                    records,
                    findings,
                    reasons,
                    page_count,
                    resolved_source_query,
                    requested_state,
                    retrieved_at,
                )

            try:
                record = issue_record_from_mapping(raw_item, requested_state=requested_state)
            except _RecordValidationError as error:
                findings.append(error.finding)
                reasons.append(error.reason)
                return _incomplete(
                    records,
                    findings,
                    reasons,
                    page_count,
                    resolved_source_query,
                    requested_state,
                    retrieved_at,
                )

            if record.issue_number in seen_issue_numbers:
                findings.append(RetrievalFinding.DUPLICATE_ISSUE)
                reasons.append(f"duplicate issue number encountered: #{record.issue_number}")
                return _incomplete(
                    records,
                    findings,
                    reasons,
                    page_count,
                    resolved_source_query,
                    requested_state,
                    retrieved_at,
                )

            seen_issue_numbers.add(record.issue_number)
            records.append(record)

        if page.next_page is None:
            findings.append(RetrievalFinding.COMPLETE)
            ordered_records = tuple(sorted(records, key=lambda item: item.issue_number))
            return IssueScanResult(
                status=RetrievalStatus.COMPLETE,
                records=ordered_records,
                findings=tuple(findings),
                reasons=tuple(reasons),
                page_count=page_count,
                item_count=len(ordered_records),
                source_query=resolved_source_query,
                requested_state=requested_state,
                retrieved_at=retrieved_at,
            )

        if (
            not isinstance(page.next_page, int)
            or isinstance(page.next_page, bool)
            or page.next_page <= page_number
        ):
            findings.append(RetrievalFinding.PAGE_MISSING_NEXT)
            reasons.append(
                f"page {page_number}: next_page={page.next_page!r} does not advance pagination"
            )
            return _incomplete(
                records,
                findings,
                reasons,
                page_count,
                resolved_source_query,
                requested_state,
                retrieved_at,
            )

        page_number = page.next_page


def scan_open_issues(source: IssuePageSource, *, source_query: str = "state=open") -> IssueScanResult:
    """Compatibility wrapper for the legacy open-only scanner contract."""
    return scan_issues(
        source,
        requested_state=IssueStateFilter.OPEN,
        retrieved_at=None,
        source_query=source_query,
        _allow_missing_retrieved_at=True,
    )


def issue_record_from_mapping(
    raw_item: Mapping[str, object],
    *,
    requested_state: IssueStateFilter,
) -> IssueScannerRecord:
    """Create one strictly validated record without coercing source evidence."""
    missing = [field for field in REQUIRED_ISSUE_FIELDS if field not in raw_item]
    if missing:
        raise _RecordValidationError(
            RetrievalFinding.MISSING_FIELD,
            "issue record missing required field(s): " + ", ".join(sorted(missing)),
        )

    issue_number = raw_item["number"]
    if not isinstance(issue_number, int) or isinstance(issue_number, bool) or issue_number <= 0:
        raise _RecordValidationError(
            RetrievalFinding.MISSING_FIELD,
            "issue record number must be a positive integer",
        )

    actual_state = raw_item["state"]
    if not isinstance(actual_state, str) or actual_state not in {"open", "closed"}:
        raise _RecordValidationError(
            RetrievalFinding.MISSING_FIELD,
            "issue record state must be exactly 'open' or 'closed'",
        )

    if requested_state != IssueStateFilter.ALL and actual_state != requested_state.value:
        raise _RecordValidationError(
            RetrievalFinding.SOURCE_STATE_MISMATCH,
            f"issue #{issue_number} returned state={actual_state} for requested state={requested_state.value}",
        )

    title = _required_string(raw_item["title"], "title")
    body = _body_string(raw_item["body"])
    url = _required_string(raw_item["html_url"], "html_url")
    created_at = _required_timestamp(raw_item["created_at"], "created_at")
    updated_at = _required_timestamp(raw_item["updated_at"], "updated_at")
    source_revision = _optional_source_revision(raw_item.get("source_revision"), updated_at)

    closed_at = _optional_timestamp(raw_item.get("closed_at"), "closed_at")
    state_reason = _optional_string(raw_item.get("state_reason"), "state_reason")
    labels = _labels(raw_item["labels"])

    return IssueScannerRecord(
        issue_number=issue_number,
        title=title,
        state=actual_state,
        body=body,
        labels=tuple(sorted(labels)),
        url=url,
        created_at=created_at,
        updated_at=updated_at,
        source_revision=source_revision,
        closed_at=closed_at,
        state_reason=state_reason,
    )


def _incomplete(
    records: Iterable[IssueScannerRecord],
    findings: Sequence[RetrievalFinding],
    reasons: Sequence[str],
    page_count: int,
    source_query: str,
    requested_state: IssueStateFilter,
    retrieved_at: str | None,
) -> IssueScanResult:
    ordered_records = tuple(sorted(records, key=lambda item: item.issue_number))
    return IssueScanResult(
        status=RetrievalStatus.INCOMPLETE,
        records=ordered_records,
        findings=tuple(findings),
        reasons=tuple(reasons),
        page_count=page_count,
        item_count=len(ordered_records),
        source_query=source_query,
        requested_state=requested_state,
        retrieved_at=retrieved_at,
    )


def _validate_requested_state(requested_state: object) -> None:
    if not isinstance(requested_state, IssueStateFilter):
        raise TypeError("requested_state must be an IssueStateFilter")


def _validate_retrieved_at(value: object, *, allow_none: bool) -> None:
    if value is None and allow_none:
        return
    if value is None:
        raise TypeError("retrieved_at is required for state-aware scans")
    _required_timestamp(value, "retrieved_at")


def _validate_source_query(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("source_query must be a non-empty string")
    return value


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _RecordValidationError(
            RetrievalFinding.MISSING_FIELD,
            f"issue record {field} must be a non-empty string",
        )
    return value


def _body_string(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _RecordValidationError(
            RetrievalFinding.MISSING_FIELD,
            "issue record body must be a string or null",
        )
    return value


def _required_timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise _RecordValidationError(
            RetrievalFinding.MISSING_FIELD,
            f"issue record {field} must use YYYY-MM-DDTHH:MM:SSZ",
        )
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise _RecordValidationError(
            RetrievalFinding.MISSING_FIELD,
            f"issue record {field} must use a valid UTC timestamp",
        ) from error
    return value


def _optional_timestamp(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_timestamp(value, field)


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _RecordValidationError(
            RetrievalFinding.MISSING_FIELD,
            f"issue record {field} must be a non-empty string when supplied",
        )
    return value


def _optional_source_revision(value: object, fallback: str) -> str:
    if value is None:
        return fallback
    if not isinstance(value, str) or not value.strip():
        raise _RecordValidationError(
            RetrievalFinding.MISSING_FIELD,
            "issue record source_revision must be a non-empty string when supplied",
        )
    return value


def _labels(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _RecordValidationError(
            RetrievalFinding.MISSING_FIELD,
            "issue record labels must be a sequence",
        )
    labels: list[str] = []
    for label in value:
        if isinstance(label, Mapping):
            if "name" not in label:
                raise _RecordValidationError(
                    RetrievalFinding.MISSING_FIELD,
                    "issue label mapping must include name",
                )
            labels.append(_label_string(label["name"]))
        else:
            labels.append(_label_string(label))
    return tuple(labels)


def _label_string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _RecordValidationError(
            RetrievalFinding.MISSING_FIELD,
            "issue label name must be a non-empty string",
        )
    return value
