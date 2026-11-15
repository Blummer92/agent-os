from __future__ import annotations

from fnmatch import fnmatch

from ..models import CheckResult, IssueMetadata, Status


def _matches(path: str, pattern: str) -> bool:
    return path == pattern or path.startswith(pattern.rstrip("/") + "/") or fnmatch(path, pattern)


def check(metadata: IssueMetadata, changed_files: list[str], pr_body: str) -> CheckResult:
    if not metadata.present:
        return CheckResult("required tests", Status.MANUAL_REVIEW, "Issue metadata is missing; required tests cannot be checked.")
    if not metadata.required_tests:
        # E8 (#3506): an empty declaration is not evidence that any test ran.
        # Say so explicitly instead of a vacuous "changed or reported" pass.
        return CheckResult("required tests", Status.PASS, "No required tests declared; none checked.")
    missing_files = [pattern for pattern in metadata.required_tests if not any(_matches(path, pattern) for path in changed_files)]
    if not missing_files:
        return CheckResult("required tests", Status.PASS, "Declared required tests are changed.")
    mentioned = [pattern for pattern in missing_files if pattern.lower() in (pr_body or "").lower()]
    missing = [pattern for pattern in missing_files if pattern not in mentioned]
    if missing:
        return CheckResult("required tests", Status.FAIL, "Declared required tests were neither changed nor reported.", missing)
    # E2 (#3506): a test path merely mentioned in PR prose is not execution
    # evidence. It was the old "reported" path that let a PR which changed
    # no required test (and said no tests ran) pass this check. A mention
    # alone now routes to manual review, never to PASS.
    return CheckResult(
        "required tests",
        Status.MANUAL_REVIEW,
        "Declared required tests were only mentioned in the PR body, not changed; a mention is not test-execution evidence.",
        mentioned,
    )
