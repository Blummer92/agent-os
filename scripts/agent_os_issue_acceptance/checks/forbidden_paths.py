from __future__ import annotations

from fnmatch import fnmatch

from ..models import CheckResult, IssueMetadata, Status


def _matches(path: str, pattern: str) -> bool:
    return path == pattern or path.startswith(pattern.rstrip("/") + "/") or fnmatch(path, pattern)


def check(metadata: IssueMetadata, changed_files: list[str]) -> CheckResult:
    if not metadata.present:
        return CheckResult("forbidden paths", Status.MANUAL_REVIEW, "Issue metadata is missing; forbidden paths cannot be checked.")
    violations = [path for path in changed_files for pattern in metadata.forbidden_paths if _matches(path, pattern)]
    if violations:
        return CheckResult("forbidden paths", Status.FAIL, "Changed files include forbidden paths.", sorted(set(violations)))
    return CheckResult("forbidden paths", Status.PASS, "No declared forbidden paths were changed.")
