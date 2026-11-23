from __future__ import annotations

import re

from ..models import CheckResult, IssueMetadata, Status

DEFAULT_SENSITIVE_PATTERNS = [
    r"BEGIN (?:RSA |OPENSSH |DSA |EC )?PRIVATE KEY",
    r"(?i)api[_-]?key\s*=\s*['\"][^'\"]+['\"]",
    r"(?i)secret\s*=\s*['\"][^'\"]+['\"]",
    r"(?i)password\s*=\s*['\"][^'\"]+['\"]",
]


def _added_sections(diff_text: str) -> tuple[str, ...]:
    """Return contiguous added lines, excluding diff headers and removed lines.

    Secret detection concerns newly introduced code, not deleted test fixtures.
    Keeping added runs separate prevents a match spanning an unchanged or
    deleted line, while retaining multiline banned patterns within a run.
    """
    sections: list[str] = []
    current: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++ "):
            current.append(line[1:])
        elif current:
            sections.append("\n".join(current))
            current = []
    if current:
        sections.append("\n".join(current))
    return tuple(sections)


def check(metadata: IssueMetadata, diff_text: str) -> CheckResult:
    patterns = list(DEFAULT_SENSITIVE_PATTERNS)
    if metadata.present:
        patterns.extend(metadata.banned_patterns)
    added_sections = _added_sections(diff_text or "")
    matches: list[str] = []
    for pattern in patterns:
        try:
            compiled = re.compile(pattern, re.MULTILINE)
        except re.error:
            matches.append(f"invalid pattern: {pattern}")
            continue
        if any(compiled.search(section) for section in added_sections):
            matches.append(pattern)
    if matches:
        return CheckResult("banned patterns", Status.FAIL, "Diff contains banned or sensitive patterns.", matches)
    return CheckResult("banned patterns", Status.PASS, "No banned or sensitive patterns were detected.")
