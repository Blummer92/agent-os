from __future__ import annotations

import re

from ..models import CheckResult, Status

_PARENT_HEADING_RE = re.compile(r"^##\s*Parent\s*$", re.IGNORECASE | re.MULTILINE)
_RELATED_HEADING_RE = re.compile(r"^##\s*Related issues\s*$", re.IGNORECASE | re.MULTILINE)
_DEPENDENCIES_HEADING_RE = re.compile(r"^##\s*Dependencies\s*$", re.IGNORECASE | re.MULTILINE)
_NEXT_HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)

_ISSUE_REF_RE = re.compile(r"#\d+")
_BLOCKED_LANGUAGE_RE = re.compile(r"\bblock(?:ed|s|ing)?\b", re.IGNORECASE)
_UNBLOCK_LANGUAGE_RE = re.compile(
    r"\b(unblock|until|once|when|after)\b", re.IGNORECASE
)

_NO_BODY_MESSAGE = "Issue body is missing; dependency and blocker state cannot be checked."


def _section_body(issue_body: str, heading_re: re.Pattern[str]) -> str | None:
    match = heading_re.search(issue_body)
    if not match:
        return None
    rest = issue_body[match.end():]
    next_heading = _NEXT_HEADING_RE.search(rest)
    section = rest[: next_heading.start()] if next_heading else rest
    return section.strip()


def _has_issue_reference(section: str | None) -> bool:
    return bool(section and _ISSUE_REF_RE.search(section))


def check_parent_reference(issue_body: str) -> CheckResult:
    """Report whether the issue declares a parent reference."""
    if not issue_body or not issue_body.strip():
        return CheckResult("parent reference", Status.MANUAL_REVIEW, _NO_BODY_MESSAGE)

    section = _section_body(issue_body, _PARENT_HEADING_RE)
    if section is None:
        return CheckResult(
            "parent reference",
            Status.WARN,
            "No '## Parent' section was found.",
        )
    if not _has_issue_reference(section):
        return CheckResult(
            "parent reference",
            Status.WARN,
            "A '## Parent' section exists but declares no issue reference.",
            [f"section={section!r}"],
        )
    return CheckResult(
        "parent reference",
        Status.PASS,
        "Parent issue reference is declared.",
        [f"section={section!r}"],
    )


def check_related_references(issue_body: str) -> CheckResult:
    """Report whether the issue declares related issue references."""
    if not issue_body or not issue_body.strip():
        return CheckResult("related references", Status.MANUAL_REVIEW, _NO_BODY_MESSAGE)

    section = _section_body(issue_body, _RELATED_HEADING_RE)
    if section is None:
        return CheckResult(
            "related references",
            Status.WARN,
            "No '## Related issues' section was found.",
        )
    references = _ISSUE_REF_RE.findall(section)
    if not references:
        return CheckResult(
            "related references",
            Status.WARN,
            "A '## Related issues' section exists but declares no issue references.",
            [f"section={section!r}"],
        )
    return CheckResult(
        "related references",
        Status.PASS,
        f"Found {len(references)} related issue reference(s).",
        [f"references={sorted(set(references))}"],
    )


def check_blocker_state(issue_body: str) -> CheckResult:
    """Report whether blocker language, when present, includes an unblock condition."""
    if not issue_body or not issue_body.strip():
        return CheckResult("blocker state", Status.MANUAL_REVIEW, _NO_BODY_MESSAGE)

    dependencies_section = _section_body(issue_body, _DEPENDENCIES_HEADING_RE)
    search_text = dependencies_section if dependencies_section is not None else issue_body

    if not _BLOCKED_LANGUAGE_RE.search(search_text):
        return CheckResult(
            "blocker state",
            Status.PASS,
            "No blocker language detected.",
        )
    if _UNBLOCK_LANGUAGE_RE.search(search_text):
        return CheckResult(
            "blocker state",
            Status.PASS,
            "Blocker language includes an unblock condition.",
            [f"section={search_text!r}"],
        )
    return CheckResult(
        "blocker state",
        Status.MANUAL_REVIEW,
        "Blocker language was detected without a clear unblock condition.",
        [f"section={search_text!r}"],
    )


def check(issue_body: str) -> list[CheckResult]:
    """Run all dependency and blocker taxonomy checks for one issue body."""
    return [
        check_parent_reference(issue_body),
        check_related_references(issue_body),
        check_blocker_state(issue_body),
    ]
