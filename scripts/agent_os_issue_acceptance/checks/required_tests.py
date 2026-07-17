from __future__ import annotations

from fnmatch import fnmatch

from ..models import CheckResult, IssueMetadata, Status


def _matches(path: str, pattern: str) -> bool:
    return path == pattern or path.startswith(pattern.rstrip("/") + "/") or fnmatch(path, pattern)


def check(metadata: IssueMetadata, changed_files: list[str], pr_body: str) -> CheckResult:
    if not metadata.present:
        return CheckResult("required tests", Status.MANUAL_REVIEW, "Issue metadata is missing; required tests cannot be checked.")
    missing_files = [pattern for pattern in metadata.required_tests if not any(_matches(path, pattern) for path in changed_files)]
    mentioned = [pattern for pattern in metadata.required_tests if pattern.lower() in (pr_body or "").lower()]
    missing = [pattern for pattern in missing_files if pattern not in mentioned]
    if missing:
        return CheckResult("required tests", Status.FAIL, "Declared required tests were neither changed nor reported.", missing)
    return CheckResult("required tests", Status.PASS, "Declared required tests are changed or reported.")
