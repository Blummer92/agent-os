"""Deterministic exact-head, PR-state, scope, and evidence preflight."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.agent_os_issue_acceptance.models import CheckResult, Status, strongest_status

from .models import EvidenceValidationError, NormalizedPRSnapshot, NormalizedReviewThread
from .normalization import MAX_CHANGED_FILES, MAX_STRING_LENGTH, MAX_THREADS


@dataclass(frozen=True)
class PreflightResult:
    overall_status: Status
    checks: tuple[CheckResult, ...]
    expected_head: str
    allowed_files: tuple[str, ...]
    outside_allowed_files: tuple[str, ...] = ()
    duplicate_thread_ids: tuple[str, ...] = ()
    duplicate_comment_ids: tuple[int, ...] = ()
    manual_review_items: tuple[str, ...] = ()
    execution_authorized: bool = False
    external_write_authorized: bool = False
    merge_authorized: bool = False
    side_effects_performed: bool = False


def _validate_sha(value: str, field: str) -> str:
    if type(value) is not str:
        raise EvidenceValidationError(f"{field} must be exactly str")
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value.lower()):
        raise EvidenceValidationError(f"{field} must be a 40-character hexadecimal SHA")
    return value.lower()


def _allowed_files(value: object) -> tuple[str, ...]:
    if type(value) not in {list, tuple}:
        raise EvidenceValidationError("allowed_files must be a list or tuple")
    if len(value) > MAX_CHANGED_FILES:
        raise EvidenceValidationError("allowed_files exceeds size limit")
    result: list[str] = []
    for index, path in enumerate(value):
        if type(path) is not str or not path or len(path) > MAX_STRING_LENGTH:
            raise EvidenceValidationError(
                f"allowed_files[{index}] must be a non-empty string within size limits"
            )
        result.append(path)
    if len(set(result)) != len(result):
        raise EvidenceValidationError("allowed_files contains duplicates")
    return tuple(sorted(result))


def _duplicates(values: list[object]) -> tuple[object, ...]:
    seen: set[object] = set()
    duplicates: set[object] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)
    return tuple(sorted(duplicates))


def _validate_review_threads(
    review_threads: tuple[NormalizedReviewThread, ...],
) -> None:
    if type(review_threads) is not tuple:
        raise EvidenceValidationError("review_threads must be a tuple of NormalizedReviewThread")
    if len(review_threads) > MAX_THREADS:
        raise EvidenceValidationError("review_threads exceeds size limit")
    for index, thread in enumerate(review_threads):
        if type(thread) is not NormalizedReviewThread:
            raise EvidenceValidationError(
                "review_threads must be a tuple of NormalizedReviewThread"
            )
        if (
            type(thread.thread_id) is not str
            or not thread.thread_id
            or len(thread.thread_id) > MAX_STRING_LENGTH
        ):
            raise EvidenceValidationError(
                f"review_threads[{index}].thread_id must be a non-empty string within size limits"
            )
        if type(thread.top_level_comment_id) is not int or thread.top_level_comment_id <= 0:
            raise EvidenceValidationError(
                f"review_threads[{index}].top_level_comment_id must be a positive integer"
            )
        if thread.path is not None and (
            type(thread.path) is not str
            or not thread.path
            or len(thread.path) > MAX_STRING_LENGTH
        ):
            raise EvidenceValidationError(
                f"review_threads[{index}].path must be a non-empty string within size limits"
            )


def preflight(
    snapshot: NormalizedPRSnapshot,
    *,
    expected_head: str,
    allowed_files: list[str] | tuple[str, ...],
    review_threads: tuple[NormalizedReviewThread, ...] = (),
    draft_allowed: bool = True,
) -> PreflightResult:
    if type(snapshot) is not NormalizedPRSnapshot:
        raise EvidenceValidationError("snapshot must be NormalizedPRSnapshot")
    _validate_review_threads(review_threads)
    if type(draft_allowed) is not bool:
        raise EvidenceValidationError("draft_allowed must be exactly bool")

    expected = _validate_sha(expected_head, "expected_head")
    normalized_allowed = _allowed_files(allowed_files)
    allowed = set(normalized_allowed)
    checks: list[CheckResult] = []
    manual_review: list[str] = []

    head_matches = snapshot.head_sha == expected
    checks.append(
        CheckResult(
            name="exact-head",
            status=Status.PASS if head_matches else Status.FAIL,
            message="exact head matches supplied expectation" if head_matches else "head moved",
            evidence=[f"expected={expected}", f"actual={snapshot.head_sha}"],
        )
    )

    state_ok = snapshot.state == "open" and not snapshot.merged
    checks.append(
        CheckResult(
            name="pr-state",
            status=Status.PASS if state_ok else Status.FAIL,
            message="PR is open and unmerged" if state_ok else "PR is closed or merged",
            evidence=[f"state={snapshot.state}", f"merged={snapshot.merged}"],
        )
    )

    draft_ok = draft_allowed or not snapshot.draft
    checks.append(
        CheckResult(
            name="draft-compatibility",
            status=Status.PASS if draft_ok else Status.FAIL,
            message="Draft state is compatible" if draft_ok else "Draft PR is not allowed",
            evidence=[f"draft={snapshot.draft}", f"draft_allowed={draft_allowed}"],
        )
    )

    outside = tuple(path for path in snapshot.changed_files if path not in allowed)
    checks.append(
        CheckResult(
            name="allowed-files",
            status=Status.PASS if not outside else Status.FAIL,
            message="all changed files are allowed" if not outside else "changed files exceed allowlist",
            evidence=list(outside) if outside else list(snapshot.changed_files),
        )
    )

    duplicate_thread_ids = tuple(
        str(item) for item in _duplicates([thread.thread_id for thread in review_threads])
    )
    duplicate_comment_ids = tuple(
        int(item)
        for item in _duplicates([thread.top_level_comment_id for thread in review_threads])
    )
    identity_duplicates = bool(duplicate_thread_ids or duplicate_comment_ids)
    identity_evidence = [f"thread_id={item}" for item in duplicate_thread_ids] + [
        f"top_level_comment_id={item}" for item in duplicate_comment_ids
    ]
    checks.append(
        CheckResult(
            name="thread-identities",
            status=Status.MANUAL_REVIEW if identity_duplicates else Status.PASS,
            message=(
                "duplicate thread identities supplied"
                if identity_duplicates
                else "thread identities are unique"
            ),
            evidence=identity_evidence,
        )
    )
    if identity_duplicates:
        manual_review.append("duplicate supplied thread identities require manual review")

    unavailable = tuple(
        thread.thread_id for thread in review_threads if thread.classification == "unavailable"
    )
    checks.append(
        CheckResult(
            name="thread-evidence",
            status=Status.PASS if not unavailable else Status.MANUAL_REVIEW,
            message="thread evidence is complete" if not unavailable else "thread evidence is incomplete",
            evidence=list(unavailable),
        )
    )
    if unavailable:
        manual_review.append("one or more current threads lack path/line evidence")

    return PreflightResult(
        overall_status=strongest_status(checks),
        checks=tuple(checks),
        expected_head=expected,
        allowed_files=normalized_allowed,
        outside_allowed_files=outside,
        duplicate_thread_ids=duplicate_thread_ids,
        duplicate_comment_ids=duplicate_comment_ids,
        manual_review_items=tuple(manual_review),
    )
