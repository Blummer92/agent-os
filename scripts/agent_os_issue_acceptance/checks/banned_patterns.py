from __future__ import annotations

import re

from ..models import CheckResult, IssueMetadata, Status

DEFAULT_SENSITIVE_PATTERNS = [
    r"BEGIN (?:RSA |OPENSSH |DSA |EC )?PRIVATE KEY",
    r"(?i)api[_-]?key\s*=\s*['\"][^'\"]+['\"]",
    r"(?i)secret\s*=\s*['\"][^'\"]+['\"]",
    r"(?i)password\s*=\s*['\"][^'\"]+['\"]",
]


def check(metadata: IssueMetadata, diff_text: str) -> CheckResult:
    patterns = list(DEFAULT_SENSITIVE_PATTERNS)
    if metadata.present:
        patterns.extend(metadata.banned_patterns)
    matches: list[str] = []
    for pattern in patterns:
        try:
            if re.search(pattern, diff_text or "", re.MULTILINE):
                matches.append(pattern)
        except re.error:
            matches.append(f"invalid pattern: {pattern}")
    if matches:
        return CheckResult("banned patterns", Status.FAIL, "Diff contains banned or sensitive patterns.", matches)
    return CheckResult("banned patterns", Status.PASS, "No banned or sensitive patterns were detected.")
