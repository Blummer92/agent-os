from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    MANUAL_REVIEW = "manual-review"


_STATUS_RANK = {
    Status.PASS: 0,
    Status.WARN: 1,
    Status.MANUAL_REVIEW: 2,
    Status.FAIL: 3,
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    message: str
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IssueMetadata:
    present: bool
    owner_agent: str | None = None
    source_of_truth: str | None = None
    external_writes: str | None = None
    required_files: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    required_tests: list[str] = field(default_factory=list)
    required_docs: list[str] = field(default_factory=list)
    banned_patterns: list[str] = field(default_factory=list)
    manual_review: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "IssueMetadata":
        return cls(present=False)


@dataclass(frozen=True)
class AcceptanceInput:
    issue_body: str
    pr_body: str
    changed_files: list[str]
    diff_text: str = ""


@dataclass(frozen=True)
class AcceptanceReport:
    linked_issue: int | None
    overall_status: Status
    checks: list[CheckResult]
    manual_review_items: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    remaining_risks: list[str] = field(default_factory=list)


def strongest_status(results: list[CheckResult]) -> Status:
    if not results:
        return Status.MANUAL_REVIEW
    return max((result.status for result in results), key=lambda status: _STATUS_RANK[status])
