from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
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


class RetrievalStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class RetrievalFinding(str, Enum):
    COMPLETE = "scan-complete"
    PAGE_MISSING_NEXT = "pagination-unknown"
    API_ERROR = "source-inaccessible"
    MISSING_FIELD = "source-partial"
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

    @property
    def complete(self) -> bool:
        return self.status == RetrievalStatus.COMPLETE


class IssuePageSource(Protocol):
    def fetch_page(self, page: int) -> IssueScanPage:
        """Return one page of issue search/list results."""


def scan_open_issues(source: IssuePageSource, *, source_query: str = "state=open") -> IssueScanResult:
    """Collect all open issue records from a paginated source.

    The scanner is intentionally evidence-only. It does not call GitHub directly,
    mutate issues, infer missing fields, or normalize metadata. Callers supply a
    page source so pagination can be tested offline and implemented separately.
    """
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
            return _incomplete(records, findings, reasons, page_count, source_query)

        if not page.complete:
            findings.append(RetrievalFinding.PAGE_MISSING_NEXT)
            reasons.append(f"page {page_number}: pagination completeness is unknown")
            return _incomplete(records, findings, reasons, page_count, source_query)

        for raw_item in page.items:
            missing = [field for field in REQUIRED_ISSUE_FIELDS if field not in raw_item]
            if missing:
                findings.append(RetrievalFinding.MISSING_FIELD)
                reasons.append(
                    "issue record missing required field(s): " + ", ".join(sorted(missing))
                )
                return _incomplete(records, findings, reasons, page_count, source_query)

            record = issue_record_from_mapping(raw_item)
            if record.issue_number in seen_issue_numbers:
                findings.append(RetrievalFinding.DUPLICATE_ISSUE)
                reasons.append(f"duplicate issue number encountered: #{record.issue_number}")
                return _incomplete(records, findings, reasons, page_count, source_query)

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
                source_query=source_query,
            )

        if page.next_page <= page_number:
            findings.append(RetrievalFinding.PAGE_MISSING_NEXT)
            reasons.append(
                f"page {page_number}: next_page={page.next_page} does not advance pagination"
            )
            return _incomplete(records, findings, reasons, page_count, source_query)

        page_number = page.next_page


def issue_record_from_mapping(raw_item: Mapping[str, object]) -> IssueScannerRecord:
    """Create a scanner record without guessing missing source fields."""
    labels = tuple(_label_name(label) for label in _as_sequence(raw_item["labels"]))
    return IssueScannerRecord(
        issue_number=int(raw_item["number"]),
        title=str(raw_item["title"]),
        state=str(raw_item["state"]),
        body=str(raw_item["body"] or ""),
        labels=tuple(sorted(labels)),
        url=str(raw_item["html_url"]),
        created_at=str(raw_item["created_at"]),
        updated_at=str(raw_item["updated_at"]),
        source_revision=str(raw_item["updated_at"]),
    )


def _incomplete(
    records: Iterable[IssueScannerRecord],
    findings: Sequence[RetrievalFinding],
    reasons: Sequence[str],
    page_count: int,
    source_query: str,
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
    )


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return ()


def _label_name(label: object) -> str:
    if isinstance(label, Mapping):
        name = label.get("name")
        if name is not None:
            return str(name)
    return str(label)
