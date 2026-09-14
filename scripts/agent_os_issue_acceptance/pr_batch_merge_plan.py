"""Pure-local finite PR batch planning for governed merge admission.

Batch membership records finite owner intent only. It never grants merge authority
and performs no retrieval, merge, refresh, issue mutation, scheduling, or I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Literal

PR_BATCH_MERGE_PLAN_SCHEMA_VERSION = "1.0"
_MAX_BATCH_ITEMS = 100


class PrBatchDisposition(str, Enum):
    CANDIDATE = "candidate"
    ALREADY_TERMINAL = "already-terminal"
    ITEM_LOCAL_BLOCKED = "item-local-blocked"
    SHARED_BLOCKED = "shared-blocked"


@dataclass(frozen=True, slots=True)
class PrBatchItemEvidence:
    pull_request_number: int
    head_sha: str
    base_branch: str
    state: Literal["open", "closed", "merged"]
    merge_admission_status: Literal["applicable", "blocked", "stale", "needs-decision", "invalid"]
    blocker_scope: Literal["none", "item", "shared"] = "none"

    def __post_init__(self) -> None:
        if not isinstance(self.pull_request_number, int) or isinstance(self.pull_request_number, bool) or self.pull_request_number <= 0:
            raise ValueError("pull_request_number must be a positive integer")
        if not self.head_sha or not self.base_branch:
            raise ValueError("head_sha and base_branch are required canonical evidence")
        if self.blocker_scope == "none" and self.merge_admission_status != "applicable" and self.state == "open":
            raise ValueError("non-applicable open PR evidence must declare blocker_scope")


@dataclass(frozen=True, slots=True)
class PrBatchPlanItem:
    sequence: int
    pull_request_number: int
    disposition: PrBatchDisposition
    observed_head_sha: str
    observed_base_branch: str
    requires_pre_merge_reacquisition: Literal[True] = True
    merge_authorized: Literal[False] = False


@dataclass(frozen=True, slots=True)
class PrBatchMergePlan:
    schema_version: str
    repository: str
    base_revision: str
    requested_pull_requests: tuple[int, ...]
    items: tuple[PrBatchPlanItem, ...]
    halt_remaining: bool
    merge_authorized: Literal[False] = False
    side_effects_performed: Literal[False] = False


def normalize_finite_pr_targets(targets: Iterable[int]) -> tuple[int, ...]:
    if isinstance(targets, (str, bytes)):
        raise ValueError("PR batch targets must be an explicit finite integer iterable")
    values = tuple(targets)
    if not values or len(values) > _MAX_BATCH_ITEMS:
        raise ValueError("PR batch must contain between 1 and 100 explicit targets")
    normalized: list[int] = []
    seen: set[int] = set()
    for value in values:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("PR batch targets must be positive integers; wildcards/unbounded targets are unsupported")
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    return tuple(normalized)


def build_pr_batch_merge_plan(
    *,
    repository: str,
    base_revision: str,
    requested_pull_requests: Iterable[int],
    evidence: Iterable[PrBatchItemEvidence],
) -> PrBatchMergePlan:
    """Build a deterministic, non-authorizing plan from already-reacquired evidence."""
    if not repository or "/" not in repository:
        raise ValueError("repository must use owner/name form")
    if not base_revision:
        raise ValueError("base_revision is required")
    requested = normalize_finite_pr_targets(requested_pull_requests)
    by_number: dict[int, PrBatchItemEvidence] = {}
    for item in evidence:
        if item.pull_request_number in by_number:
            raise ValueError("duplicate canonical PR evidence is ambiguous")
        by_number[item.pull_request_number] = item
    if set(by_number) != set(requested):
        raise ValueError("canonical evidence must cover exactly the normalized target set")

    items: list[PrBatchPlanItem] = []
    halt_remaining = False
    for sequence, number in enumerate(requested, start=1):
        current = by_number[number]
        if current.state in {"closed", "merged"}:
            disposition = PrBatchDisposition.ALREADY_TERMINAL
        elif current.blocker_scope == "shared":
            disposition = PrBatchDisposition.SHARED_BLOCKED
            halt_remaining = True
        elif current.merge_admission_status != "applicable" or current.blocker_scope == "item":
            disposition = PrBatchDisposition.ITEM_LOCAL_BLOCKED
        else:
            disposition = PrBatchDisposition.CANDIDATE
        items.append(
            PrBatchPlanItem(
                sequence=sequence,
                pull_request_number=number,
                disposition=disposition,
                observed_head_sha=current.head_sha,
                observed_base_branch=current.base_branch,
            )
        )
        if halt_remaining:
            break

    return PrBatchMergePlan(
        schema_version=PR_BATCH_MERGE_PLAN_SCHEMA_VERSION,
        repository=repository,
        base_revision=base_revision,
        requested_pull_requests=requested,
        items=tuple(items),
        halt_remaining=halt_remaining,
    )
