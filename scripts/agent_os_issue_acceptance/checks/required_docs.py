from __future__ import annotations

from ..models import CheckResult, IssueMetadata, Status
from ..path_contract import (
    DeclaredPathError,
    declared_path_matches,
    normalize_declared_pattern,
)

_MISSING_METADATA_MESSAGE = "Issue metadata is missing; required docs cannot be checked."
_UNSATISFIED_MESSAGE = "Declared required docs were not changed."
_SATISFIED_MESSAGE = "Declared required docs are satisfied."
_UNMATCHED_CODE = "unmatched"
_MAX_EVIDENCE_VALUE = 120


def _bounded(value: object) -> str:
    text = repr(value)
    if len(text) > _MAX_EVIDENCE_VALUE:
        text = f"{text[: _MAX_EVIDENCE_VALUE - 3]}..."
    return text


def _evidence(declaration: object, code: str) -> str:
    return f"field=required_docs; value={_bounded(declaration)}; code={code}"


def _is_covered(declaration: str, changed_files: list[str]) -> bool:
    """Return True when at least one changed file matches the valid declaration.

    ``declaration`` has already passed ``normalize_declared_pattern``, so any
    ``DeclaredPathError`` raised here comes from an unparseable changed-file
    path, which cannot satisfy the declaration and is skipped. Every comparison
    delegates to the canonical ``declared_path_matches``; this check owns no
    independent path grammar or wildcard semantics.
    """
    for path in changed_files:
        try:
            if declared_path_matches(path, declaration):
                return True
        except DeclaredPathError:
            continue
    return False


def check(metadata: IssueMetadata, changed_files: list[str]) -> CheckResult:
    """Report declared documentation-path coverage against supplied changed files.

    Coverage only: a match proves that a declared documentation path appears in
    the supplied ``changed_files`` list. It does not prove the list is current
    (see #323 for PR-head provenance) or that the selected documentation is
    canonical, relevant, or sufficient (see DOC5 for quality review). Matching
    delegates entirely to the canonical declared-path contract; invalid
    declarations fail closed with the stable ``DeclaredPathError.code``.
    """
    if not metadata.present:
        return CheckResult("required docs", Status.MANUAL_REVIEW, _MISSING_METADATA_MESSAGE)

    problems: set[str] = set()
    for declaration in metadata.required_docs:
        try:
            normalize_declared_pattern(declaration)
        except DeclaredPathError as error:
            problems.add(_evidence(declaration, error.code))
            continue
        if not _is_covered(declaration, changed_files):
            problems.add(_evidence(declaration, _UNMATCHED_CODE))

    if problems:
        return CheckResult("required docs", Status.FAIL, _UNSATISFIED_MESSAGE, sorted(problems))
    return CheckResult("required docs", Status.PASS, _SATISFIED_MESSAGE)
