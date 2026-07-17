from __future__ import annotations

import re

LINKED_ISSUE_RE = re.compile(
    r"(?:(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+)?#(?P<number>\d+)",
    re.IGNORECASE,
)

REQUIRED_PR_FIELDS = [
    "linked issue",
    "summary",
    "files changed",
    "tests run",
    "docs updated",
    "unresolved blockers",
    "handoff recommendations",
    "remaining risks",
]


def parse_linked_issue(pr_body: str, pr_title: str = "") -> int | None:
    """Return the first issue number referenced by PR title or body."""
    text = f"{pr_title}\n{pr_body or ''}"
    match = LINKED_ISSUE_RE.search(text)
    if not match:
        return None
    return int(match.group("number"))


def has_markdown_heading(text: str, heading: str) -> bool:
    pattern = re.compile(rf"^#+\s+{re.escape(heading)}\s*$", re.IGNORECASE | re.MULTILINE)
    return bool(pattern.search(text or ""))


def missing_final_report_fields(pr_body: str) -> list[str]:
    return [field for field in REQUIRED_PR_FIELDS if not has_markdown_heading(pr_body, field)]


def has_validation_command(pr_body: str) -> bool:
    lowered = (pr_body or "").lower()
    commands = [
        "validate-all.sh",
        "pytest",
        "validate-repo-structure.sh",
        "cloud build",
        "cloudbuild",
    ]
    return any(command in lowered for command in commands)
