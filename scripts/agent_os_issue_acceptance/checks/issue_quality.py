from __future__ import annotations

import re
from enum import Enum

from ..models import CheckResult, Status


class IssueFamily(str, Enum):
    ROADMAP = "roadmap"
    IMPLEMENTATION = "implementation"
    VALIDATION = "validation"
    GOVERNANCE = "governance"
    CLEANUP = "cleanup"


_REQUIRED: dict[IssueFamily, tuple[str, ...]] = {
    IssueFamily.ROADMAP: ("goal", "scope", "dependencies"),
    IssueFamily.IMPLEMENTATION: (
        "goal",
        "scope",
        "acceptance criteria",
        "definition of done",
        "tests / validation",
    ),
    IssueFamily.VALIDATION: (
        "goal",
        "scope",
        "acceptance criteria",
        "definition of done",
        "tests / validation",
    ),
    IssueFamily.GOVERNANCE: ("goal", "scope", "acceptance criteria", "definition of done"),
    IssueFamily.CLEANUP: ("goal", "scope"),
}

_RECOMMENDED = (
    "acceptance criteria",
    "dependencies",
    "definition of done",
    "tests / validation",
    "parent",
    "related issues",
    "handoff notes",
    "remaining risks",
)

_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_ISSUE_REF_RE = re.compile(r"#\d+")
_BLOCKER_RE = re.compile(r"\bblock(?:ed|ing|s)?\b", re.IGNORECASE)
_UNBLOCK_RE = re.compile(r"\b(?:unblock|until|once|when|after)\b", re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(
    r"^(?:tbd|todo|_?no response_?|n/a\?|placeholder)[.!\s]*$", re.IGNORECASE
)
_ITEM_RE = re.compile(
    r"^\s*(?:[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+)(?P<item>.+?)\s*$"
)
_OBSERVABLE_RE = re.compile(
    r"\b(?:passes|returns|contains|creates|rejects|preserves|matches|reports|exists)\b",
    re.IGNORECASE,
)


def _normalize_heading(value: str) -> str:
    heading = re.sub(r"[`*_]", "", value).strip().lower()
    if heading in {"objective", "goal / objective"}:
        return "goal"
    if heading in {"tests", "validation", "tests/validation", "tests and validation"}:
        return "tests / validation"
    return heading


def parse_sections(issue_body: str) -> dict[str, str]:
    """Parse level-two Markdown sections without interpreting their meaning."""
    matches = list(_HEADING_RE.finditer(issue_body))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(issue_body)
        key = _normalize_heading(match.group(1))
        sections.setdefault(key, issue_body[start:end].strip())
    return sections


def _content_status(content: str) -> Status:
    if not content.strip():
        return Status.FAIL
    if _PLACEHOLDER_RE.fullmatch(content.strip()):
        return Status.MANUAL_REVIEW
    return Status.PASS


def check_completeness(issue_body: str, family: IssueFamily) -> list[CheckResult]:
    """Check required and recommended sections for one supported issue family."""
    if type(issue_body) is not str or type(family) is not IssueFamily:
        raise TypeError("issue_body must be str and family must be IssueFamily")
    sections = parse_sections(issue_body)
    results: list[CheckResult] = []
    required = set(_REQUIRED[family])
    expected = tuple(dict.fromkeys((*_REQUIRED[family], *_RECOMMENDED)))
    for section in expected:
        if section not in sections:
            status = Status.FAIL if section in required else Status.WARN
            results.append(CheckResult(f"section: {section}", status, f"Missing {section} section."))
            continue
        content_status = _content_status(sections[section])
        if content_status == Status.FAIL:
            status = Status.FAIL if section in required else Status.WARN
            message = f"{section} section is empty."
        elif content_status == Status.MANUAL_REVIEW:
            status = Status.MANUAL_REVIEW
            message = f"{section} section contains placeholder-only content."
        else:
            status = Status.PASS
            message = f"{section} section is present."
        results.append(CheckResult(f"section: {section}", status, message))
    return results


def check_parent_reference(issue_body: str) -> CheckResult:
    sections = parse_sections(issue_body)
    content = sections.get("parent")
    if content is None:
        return CheckResult("parent reference", Status.WARN, "No Parent section was found.")
    if _content_status(content) == Status.MANUAL_REVIEW:
        return CheckResult(
            "parent reference", Status.MANUAL_REVIEW, "Parent section contains placeholder-only content."
        )
    if not _ISSUE_REF_RE.search(content):
        return CheckResult("parent reference", Status.WARN, "Parent section contains no issue reference.")
    return CheckResult("parent reference", Status.PASS, "Parent issue reference is present.")


def check_related_references(issue_body: str) -> CheckResult:
    sections = parse_sections(issue_body)
    content = sections.get("related issues")
    if content is None:
        return CheckResult("related references", Status.WARN, "No Related issues section was found.")
    if _content_status(content) == Status.MANUAL_REVIEW:
        return CheckResult(
            "related references",
            Status.MANUAL_REVIEW,
            "Related issues section contains placeholder-only content.",
        )
    refs = sorted(set(_ISSUE_REF_RE.findall(content)))
    if not refs:
        return CheckResult("related references", Status.WARN, "Related issues contains no issue reference.")
    return CheckResult("related references", Status.PASS, "Related issue references are present.", refs)


def check_blocker_quality(issue_body: str) -> CheckResult:
    sections = parse_sections(issue_body)
    content = sections.get("dependencies", issue_body)
    if not _BLOCKER_RE.search(content):
        return CheckResult("blocker quality", Status.PASS, "No blocker language detected.")
    if _UNBLOCK_RE.search(content):
        return CheckResult("blocker quality", Status.PASS, "Blocker includes an unblock condition.")
    return CheckResult(
        "blocker quality",
        Status.MANUAL_REVIEW,
        "Blocker language is present without a clear unblock condition.",
    )


def check_acceptance_criteria(issue_body: str, family: IssueFamily) -> list[CheckResult]:
    sections = parse_sections(issue_body)
    content = sections.get("acceptance criteria")
    required = "acceptance criteria" in _REQUIRED[family]
    if content is None or not content.strip():
        status = Status.FAIL if required else Status.WARN
        return [CheckResult("acceptance criteria", status, "Acceptance criteria are missing.")]
    if _PLACEHOLDER_RE.fullmatch(content.strip()):
        quality = CheckResult(
            "acceptance criteria", Status.MANUAL_REVIEW, "Acceptance criteria are placeholder-only."
        )
    else:
        criterion_lines = [line for line in content.splitlines() if line.strip()]
        item_matches = [_ITEM_RE.fullmatch(line) for line in criterion_lines]
        items = [match.group("item") for match in item_matches if match is not None]
        if (
            not criterion_lines
            or len(items) != len(criterion_lines)
            or any(_OBSERVABLE_RE.search(item) is None for item in items)
        ):
            quality = CheckResult(
                "acceptance criteria",
                Status.MANUAL_REVIEW,
                "Acceptance criteria are present but not deterministically testable.",
            )
        else:
            quality = CheckResult(
                "acceptance criteria", Status.PASS, "Acceptance criteria are itemized and observable."
            )
    validation = sections.get("tests / validation")
    support = CheckResult(
        "acceptance validation support",
        Status.PASS if validation and validation.strip() else Status.WARN,
        "Tests / validation evidence is present."
        if validation and validation.strip()
        else "Acceptance criteria have no Tests / validation section.",
    )
    return [quality, support]


def check(issue_body: str, family: IssueFamily) -> list[CheckResult]:
    """Return deterministic report-only issue-quality findings."""
    return [
        *check_completeness(issue_body, family),
        check_parent_reference(issue_body),
        check_related_references(issue_body),
        check_blocker_quality(issue_body),
        *check_acceptance_criteria(issue_body, family),
    ]
