"""Deterministic exact-head, PR-state, scope, and evidence preflight."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.agent_os_issue_acceptance.models import CheckResult, Status, strongest_status

from .models import EvidenceValidationError, NormalizedPRSnapshot, NormalizedReviewThread


@dataclass(frozen=True)
class PreflightResult:
    overall_status: Status
    checks: tuple[CheckResult, ...]
    expected_head: str
    allowed_files: tuple[str, ...]
    outside_allowed_files: tuple[str, ...] = ()
    duplicate_thread_ids: tuple[str, ...] = ()
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
    result: list[str] = []
    for index, path in enumerate(value):
        if type(path) is not str or not path:
            raise EvidenceValidationError(f"allowed_files[{index}] must be a non-empty string")
        result.append(path)
    if len(set(result)) != len(result):
        raise EvidenceValidationError("allowed_files contains duplicates")
    return tuple(sorted(result))


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
    if type(review_threads) is not tuple or any(
        type(thread) is not NormalizedReviewThread for thread in review_threads
    ):
        raise EvidenceValidationError("review_threads must be a tuple of NormalizedReviewThread")
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

    ids = [thread.thread_id for thread in review_threads]
    duplicates = tuple(sorted({item for item in ids if ids.count(item) > 1}))
    checks.append(
        CheckResult(
            name="thread-identities",
            status=Status.PASS if not duplicates else Status.MANUAL_REVIEW,
            message="thread identities are unique" if not duplicates else "duplicate thread identities supplied",
            evidence=list(duplicates),
        )
    )
    if duplicates:
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
        duplicate_thread_ids=duplicates,
        manual_review_items=tuple(manual_review),
    )
