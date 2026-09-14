"""Finite sequential BM2 coordinator over canonical per-PR owners.

The coordinator owns batch progression only. It never retrieves GitHub state,
refreshes a branch, validates code, grants merge authority, or merges a PR.
Instead, each transition requires freshly reacquired evidence and emits exactly
one bounded next operation for the existing canonical owner to execute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from .pr_batch_merge_plan import PrBatchDisposition, PrBatchMergePlan


class BatchMergeAction(str, Enum):
    REACQUIRE = "reacquire-current-state"
    REFRESH = "invoke-governed-refresh"
    VALIDATE = "obtain-exact-head-validation"
    AUTHORIZE = "obtain-content-bound-merge-authorization"
    MERGE = "merge-exact-expected-head"
    READBACK = "read-back-merged-pr-and-main"
    COMPLETE = "complete"
    HALT = "halt"


class BatchItemDisposition(str, Enum):
    MERGED = "merged"
    ALREADY_TERMINAL = "already-terminal"
    SKIPPED_ITEM_LOCAL = "skipped-item-local"
    BLOCKED_SHARED = "blocked-shared"
    MANUAL_REVIEW = "manual-review"


@dataclass(frozen=True, slots=True)
class CurrentPrEvidence:
    pull_request_number: int
    main_sha: str
    head_sha: str
    state: Literal["open", "closed", "merged"]
    branch_freshness: Literal["current", "behind", "diverged", "unknown"]
    semantic_conflict: bool = False
    provider_available: bool = True

    def __post_init__(self) -> None:
        if type(self.pull_request_number) is not int or self.pull_request_number < 1:
            raise ValueError("pull_request_number must be a positive integer")
        if not self.main_sha or not self.head_sha:
            raise ValueError("main_sha and head_sha are required fresh identities")
        if self.state not in {"open", "closed", "merged"}:
            raise ValueError("state is non-canonical")
        if self.branch_freshness not in {"current", "behind", "diverged", "unknown"}:
            raise ValueError("branch_freshness is non-canonical")


@dataclass(frozen=True, slots=True)
class ItemAdmissionEvidence:
    pull_request_number: int
    main_sha: str
    head_sha: str
    validation_status: Literal["passed", "failed", "pending", "missing", "manual-review"]
    authorization_status: Literal["authorized", "blocked", "stale", "missing", "manual-review"]


@dataclass(frozen=True, slots=True)
class MergeReadbackEvidence:
    pull_request_number: int
    expected_head_sha: str
    merged: bool
    new_main_sha: str
    provider_available: bool = True


@dataclass(frozen=True, slots=True)
class BatchItemResult:
    pull_request_number: int
    disposition: BatchItemDisposition
    starting_head_sha: str | None
    final_head_sha: str | None
    starting_main_sha: str | None
    final_main_sha: str | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BatchMergeCursor:
    requested_pull_requests: tuple[int, ...]
    index: int = 0
    current_main_sha: str | None = None
    current_head_sha: str | None = None
    results: tuple[BatchItemResult, ...] = ()
    action: BatchMergeAction = BatchMergeAction.REACQUIRE
    halted: bool = False
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    @property
    def current_pull_request(self) -> int | None:
        return None if self.index >= len(self.requested_pull_requests) else self.requested_pull_requests[self.index]


def start_batch_execution(plan: PrBatchMergePlan) -> BatchMergeCursor:
    """Start only from a finite BM1 plan; BM1 dispositions remain authoritative."""
    if type(plan) is not PrBatchMergePlan:
        raise TypeError("plan must be PrBatchMergePlan")
    admitted: list[int] = []
    results: list[BatchItemResult] = []
    for item in plan.items:
        if item.disposition is PrBatchDisposition.CANDIDATE:
            admitted.append(item.pull_request_number)
        elif item.disposition is PrBatchDisposition.ALREADY_TERMINAL:
            results.append(_result(item.pull_request_number, BatchItemDisposition.ALREADY_TERMINAL, "bm1-already-terminal"))
        elif item.disposition is PrBatchDisposition.ITEM_LOCAL_BLOCKED:
            results.append(_result(item.pull_request_number, BatchItemDisposition.SKIPPED_ITEM_LOCAL, "bm1-item-local-blocked"))
        else:
            results.append(_result(item.pull_request_number, BatchItemDisposition.BLOCKED_SHARED, "bm1-shared-blocked"))
            return BatchMergeCursor(tuple(admitted), results=tuple(results), action=BatchMergeAction.HALT, halted=True)
    action = BatchMergeAction.REACQUIRE if admitted else BatchMergeAction.COMPLETE
    return BatchMergeCursor(tuple(admitted), results=tuple(results), action=action)


def apply_current_state(cursor: BatchMergeCursor, evidence: CurrentPrEvidence) -> BatchMergeCursor:
    _expect(cursor, BatchMergeAction.REACQUIRE, evidence.pull_request_number)
    if not evidence.provider_available or evidence.branch_freshness == "unknown":
        return _halt(cursor, evidence, "canonical-state-unavailable")
    if evidence.state in {"closed", "merged"}:
        return _advance(cursor, _result(evidence.pull_request_number, BatchItemDisposition.ALREADY_TERMINAL, "pr-already-terminal", evidence))
    if evidence.semantic_conflict:
        return _advance(cursor, _result(evidence.pull_request_number, BatchItemDisposition.SKIPPED_ITEM_LOCAL, "semantic-conflict", evidence))
    action = BatchMergeAction.REFRESH if evidence.branch_freshness in {"behind", "diverged"} else BatchMergeAction.VALIDATE
    return _replace(cursor, current_main_sha=evidence.main_sha, current_head_sha=evidence.head_sha, action=action)


def apply_refresh_readback(cursor: BatchMergeCursor, evidence: CurrentPrEvidence) -> BatchMergeCursor:
    _expect(cursor, BatchMergeAction.REFRESH, evidence.pull_request_number)
    if not evidence.provider_available:
        return _halt(cursor, evidence, "refresh-readback-unavailable")
    if evidence.semantic_conflict:
        return _advance(cursor, _result(evidence.pull_request_number, BatchItemDisposition.SKIPPED_ITEM_LOCAL, "refresh-semantic-conflict", evidence))
    if evidence.state != "open" or evidence.branch_freshness != "current":
        return _halt(cursor, evidence, "refresh-currentness-unproven")
    return _replace(cursor, current_main_sha=evidence.main_sha, current_head_sha=evidence.head_sha, action=BatchMergeAction.VALIDATE)


def apply_validation(cursor: BatchMergeCursor, evidence: ItemAdmissionEvidence) -> BatchMergeCursor:
    _expect(cursor, BatchMergeAction.VALIDATE, evidence.pull_request_number)
    if not _same_identity(cursor, evidence.main_sha, evidence.head_sha):
        return _restart(cursor)
    if evidence.validation_status == "passed":
        return _replace(cursor, action=BatchMergeAction.AUTHORIZE)
    if evidence.validation_status == "manual-review":
        return _advance(cursor, _result(evidence.pull_request_number, BatchItemDisposition.MANUAL_REVIEW, "validation-manual-review", cursor=cursor))
    return _advance(cursor, _result(evidence.pull_request_number, BatchItemDisposition.SKIPPED_ITEM_LOCAL, f"validation-{evidence.validation_status}", cursor=cursor))


def apply_merge_authorization(cursor: BatchMergeCursor, evidence: ItemAdmissionEvidence) -> BatchMergeCursor:
    _expect(cursor, BatchMergeAction.AUTHORIZE, evidence.pull_request_number)
    if not _same_identity(cursor, evidence.main_sha, evidence.head_sha):
        return _restart(cursor)
    if evidence.validation_status != "passed":
        return _restart(cursor)
    if evidence.authorization_status == "authorized":
        return _replace(cursor, action=BatchMergeAction.MERGE)
    if evidence.authorization_status == "manual-review":
        return _advance(cursor, _result(evidence.pull_request_number, BatchItemDisposition.MANUAL_REVIEW, "authorization-manual-review", cursor=cursor))
    return _advance(cursor, _result(evidence.pull_request_number, BatchItemDisposition.SKIPPED_ITEM_LOCAL, f"authorization-{evidence.authorization_status}", cursor=cursor))


def expected_merge(cursor: BatchMergeCursor) -> tuple[int, str]:
    """Return the exact PR/head pair for the canonical merge path; grants no authority."""
    if cursor.action is not BatchMergeAction.MERGE or cursor.current_pull_request is None or cursor.current_head_sha is None:
        raise ValueError("cursor is not ready for an exact-head merge")
    return cursor.current_pull_request, cursor.current_head_sha


def record_merge_attempt(cursor: BatchMergeCursor, *, pull_request_number: int, expected_head_sha: str, accepted: bool) -> BatchMergeCursor:
    _expect(cursor, BatchMergeAction.MERGE, pull_request_number)
    if expected_head_sha != cursor.current_head_sha:
        return _restart(cursor)
    if not accepted:
        return _advance(cursor, _result(pull_request_number, BatchItemDisposition.SKIPPED_ITEM_LOCAL, "expected-head-merge-rejected", cursor=cursor))
    return _replace(cursor, action=BatchMergeAction.READBACK)


def apply_merge_readback(cursor: BatchMergeCursor, evidence: MergeReadbackEvidence) -> BatchMergeCursor:
    _expect(cursor, BatchMergeAction.READBACK, evidence.pull_request_number)
    if not evidence.provider_available:
        return _halt(cursor, None, "post-merge-readback-unavailable")
    if evidence.expected_head_sha != cursor.current_head_sha or not evidence.merged or not evidence.new_main_sha:
        return _halt(cursor, None, "post-merge-terminal-proof-failed")
    result = BatchItemResult(evidence.pull_request_number, BatchItemDisposition.MERGED, cursor.current_head_sha, cursor.current_head_sha, cursor.current_main_sha, evidence.new_main_sha, ())
    return _advance(cursor, result, new_main=evidence.new_main_sha)


def final_batch_report(cursor: BatchMergeCursor) -> tuple[BatchItemResult, ...]:
    if cursor.action not in {BatchMergeAction.COMPLETE, BatchMergeAction.HALT}:
        raise ValueError("batch is not terminal")
    return cursor.results


def _expect(cursor: BatchMergeCursor, action: BatchMergeAction, pr: int) -> None:
    if type(cursor) is not BatchMergeCursor or cursor.action is not action or cursor.current_pull_request != pr:
        raise ValueError("evidence does not match the current batch transition")


def _same_identity(cursor: BatchMergeCursor, main: str, head: str) -> bool:
    return main == cursor.current_main_sha and head == cursor.current_head_sha


def _restart(cursor: BatchMergeCursor) -> BatchMergeCursor:
    return _replace(cursor, current_main_sha=None, current_head_sha=None, action=BatchMergeAction.REACQUIRE)


def _advance(cursor: BatchMergeCursor, result: BatchItemResult, *, new_main: str | None = None) -> BatchMergeCursor:
    index = cursor.index + 1
    action = BatchMergeAction.COMPLETE if index >= len(cursor.requested_pull_requests) else BatchMergeAction.REACQUIRE
    return BatchMergeCursor(cursor.requested_pull_requests, index, new_main, None, cursor.results + (result,), action, False)


def _halt(cursor: BatchMergeCursor, evidence: CurrentPrEvidence | None, reason: str) -> BatchMergeCursor:
    pr = cursor.current_pull_request
    results = cursor.results
    if pr is not None:
        results += (_result(pr, BatchItemDisposition.BLOCKED_SHARED, reason, evidence, cursor),)
    return BatchMergeCursor(cursor.requested_pull_requests, cursor.index, cursor.current_main_sha, cursor.current_head_sha, results, BatchMergeAction.HALT, True)


def _replace(cursor: BatchMergeCursor, **changes: object) -> BatchMergeCursor:
    values = {"requested_pull_requests": cursor.requested_pull_requests, "index": cursor.index, "current_main_sha": cursor.current_main_sha, "current_head_sha": cursor.current_head_sha, "results": cursor.results, "action": cursor.action, "halted": cursor.halted}
    values.update(changes)
    return BatchMergeCursor(**values)


def _result(pr: int, disposition: BatchItemDisposition, reason: str, evidence: CurrentPrEvidence | None = None, cursor: BatchMergeCursor | None = None) -> BatchItemResult:
    head = evidence.head_sha if evidence else (cursor.current_head_sha if cursor else None)
    main = evidence.main_sha if evidence else (cursor.current_main_sha if cursor else None)
    return BatchItemResult(pr, disposition, head, head, main, main, (reason,))
