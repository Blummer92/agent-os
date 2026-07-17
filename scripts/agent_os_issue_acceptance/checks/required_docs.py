from __future__ import annotations

from fnmatch import fnmatch

from ..models import CheckResult, IssueMetadata, Status


def _matches(path: str, pattern: str) -> bool:
    return path == pattern or path.startswith(pattern.rstrip("/") + "/") or fnmatch(path, pattern)


def check(metadata: IssueMetadata, changed_files: list[str]) -> CheckResult:
    if not metadata.present:
        return CheckResult("required docs", Status.MANUAL_REVIEW, "Issue metadata is missing; required docs cannot be checked.")
    missing = [pattern for pattern in metadata.required_docs if not any(_matches(path, pattern) for path in changed_files)]
    if missing:
        return CheckResult("required docs", Status.FAIL, "Declared required docs were not changed.", missing)
    return CheckResult("required docs", Status.PASS, "Declared required docs are satisfied.")
