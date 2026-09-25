"""Bounded Cloud Build PR-comment publication policy for #686.

This module owns only target-bound managed-comment planning and canonical
readback reconciliation. It performs no GitHub request, credential discovery,
pagination, retry, Cloud Build call, or external mutation. Connected callers
must execute the returned create/update action through the canonical GitHub
operation and supply complete canonical readback afterward.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from scripts.agent_os_issue_acceptance.comment_mutation_readback import (
    CommentPersistenceStatus,
    CommentReadback,
    evaluate_comment_persistence,
)

from .models import (
    MAX_REASON_CODES,
    CloudBuildCommentProjection,
    CloudBuildEvidenceError,
    CloudBuildResultEvidence,
    PullRequestResolutionResult,
    ResolutionStatus,
)

MAX_COMMENT_SNAPSHOTS = 100


class PublicationAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    NOOP = "noop"
    MANUAL_REVIEW = "manual-review"


@dataclass(frozen=True, slots=True)
class ManagedCommentSnapshot:
    comment_id: int
    body: str

    def __post_init__(self) -> None:
        if type(self.comment_id) is not int or self.comment_id < 1:
            raise CloudBuildEvidenceError("comment_id must be a positive integer")
        if type(self.body) is not str:
            raise CloudBuildEvidenceError("comment body must be text")


@dataclass(frozen=True, slots=True)
class PublicationPlan:
    repository: str
    pull_request_number: int | None
    tested_sha: str
    action: PublicationAction
    stable_marker: str
    body: str
    managed_comment_id: int | None
    reason_codes: tuple[str, ...]
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.action, PublicationAction):
            raise CloudBuildEvidenceError("action must be a PublicationAction")
        if len(self.reason_codes) > MAX_REASON_CODES or not self.reason_codes:
            raise CloudBuildEvidenceError("reason_codes must be bounded and non-empty")
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        if self.action in {PublicationAction.CREATE, PublicationAction.UPDATE, PublicationAction.NOOP}:
            if self.pull_request_number is None:
                raise CloudBuildEvidenceError("publishable plan requires a pull request")
        if self.action == PublicationAction.UPDATE and self.managed_comment_id is None:
            raise CloudBuildEvidenceError("update requires managed_comment_id")
        if self.action == PublicationAction.CREATE and self.managed_comment_id is not None:
            raise CloudBuildEvidenceError("create cannot target an existing comment")


@dataclass(frozen=True, slots=True)
class PublicationReconciliation:
    status: str
    pull_request_number: int
    persisted_comment_id: int | None
    retry_safe: bool
    reason_codes: tuple[str, ...]
    side_effects_performed: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    review_authorized: Literal[False] = field(default=False, init=False)
    required_check_authorized: Literal[False] = field(default=False, init=False)


def _manual_plan(
    evidence: CloudBuildResultEvidence,
    projection: CloudBuildCommentProjection,
    *reasons: str,
) -> PublicationPlan:
    return PublicationPlan(
        repository=evidence.repository,
        pull_request_number=None,
        tested_sha=evidence.tested_sha,
        action=PublicationAction.MANUAL_REVIEW,
        stable_marker=projection.stable_marker,
        body=projection.rendered_body,
        managed_comment_id=None,
        reason_codes=tuple(reasons),
    )


def plan_publication(
    evidence: CloudBuildResultEvidence,
    resolution: PullRequestResolutionResult,
    projection: CloudBuildCommentProjection,
    *,
    comments_complete: bool,
    comments: tuple[ManagedCommentSnapshot, ...],
) -> PublicationPlan:
    """Plan create/update/no-op only after exact #685 target proof."""
    if type(comments_complete) is not bool or type(comments) is not tuple:
        raise TypeError("comments_complete must be bool and comments must be tuple")
    if any(type(item) is not ManagedCommentSnapshot for item in comments):
        raise TypeError("comments must contain ManagedCommentSnapshot values")
    if len(comments) > MAX_COMMENT_SNAPSHOTS:
        return _manual_plan(evidence, projection, "publication.too-many-comments")
    if projection.tested_sha != evidence.tested_sha:
        return _manual_plan(evidence, projection, "publication.projection-sha-mismatch")
    if projection.stable_marker not in projection.rendered_body:
        return _manual_plan(evidence, projection, "publication.marker-missing")
    if resolution.status is not ResolutionStatus.RESOLVED or resolution.pull_request_number is None:
        return _manual_plan(evidence, projection, "publication.target-unresolved", *resolution.reason_codes)
    if not comments_complete:
        return _manual_plan(evidence, projection, "publication.comment-readback-incomplete")

    managed = tuple(item for item in comments if projection.stable_marker in item.body)
    if len(managed) > 1:
        return _manual_plan(evidence, projection, "publication.multiple-managed-comments")
    if not managed:
        return PublicationPlan(
            repository=evidence.repository,
            pull_request_number=resolution.pull_request_number,
            tested_sha=evidence.tested_sha,
            action=PublicationAction.CREATE,
            stable_marker=projection.stable_marker,
            body=projection.rendered_body,
            managed_comment_id=None,
            reason_codes=("publication.create-managed-comment",),
        )

    current = managed[0]
    if current.body == projection.rendered_body:
        return PublicationPlan(
            repository=evidence.repository,
            pull_request_number=resolution.pull_request_number,
            tested_sha=evidence.tested_sha,
            action=PublicationAction.NOOP,
            stable_marker=projection.stable_marker,
            body=projection.rendered_body,
            managed_comment_id=current.comment_id,
            reason_codes=("publication.already-current",),
        )
    return PublicationPlan(
        repository=evidence.repository,
        pull_request_number=resolution.pull_request_number,
        tested_sha=evidence.tested_sha,
        action=PublicationAction.UPDATE,
        stable_marker=projection.stable_marker,
        body=projection.rendered_body,
        managed_comment_id=current.comment_id,
        reason_codes=("publication.update-managed-comment",),
    )


def reconcile_publication(
    plan: PublicationPlan,
    *,
    provider_reported_success: bool | None,
    readback_complete: bool,
    comments: tuple[ManagedCommentSnapshot, ...],
) -> PublicationReconciliation:
    """Require canonical exact-body readback before publication is converged."""
    if plan.pull_request_number is None or plan.action is PublicationAction.MANUAL_REVIEW:
        raise ValueError("manual-review plans cannot be reconciled as mutations")
    if plan.action is PublicationAction.NOOP:
        return PublicationReconciliation(
            status="converged",
            pull_request_number=plan.pull_request_number,
            persisted_comment_id=plan.managed_comment_id,
            retry_safe=False,
            reason_codes=("publication.noop-current",),
        )

    readback = tuple(
        CommentReadback(item.comment_id, plan.pull_request_number, item.body)
        for item in comments
    )
    result = evaluate_comment_persistence(
        issue_number=plan.pull_request_number,
        intended_body=plan.body,
        provider_reported_success=provider_reported_success,
        readback_complete=readback_complete,
        comments=readback,
    )

    if (
        plan.action is PublicationAction.UPDATE
        and result.status is CommentPersistenceStatus.PERSISTED
        and result.persisted_comment_id != plan.managed_comment_id
    ):
        return PublicationReconciliation(
            status="uncertain",
            pull_request_number=plan.pull_request_number,
            persisted_comment_id=None,
            retry_safe=False,
            reason_codes=("publication.update-target-mismatch",),
        )

    status = {
        CommentPersistenceStatus.PERSISTED: "converged",
        CommentPersistenceStatus.NOT_PERSISTED: "not-persisted",
        CommentPersistenceStatus.UNCERTAIN: "uncertain",
    }[result.status]
    return PublicationReconciliation(
        status=status,
        pull_request_number=plan.pull_request_number,
        persisted_comment_id=result.persisted_comment_id,
        retry_safe=result.retry_safe,
        reason_codes=result.reason_codes,
    )
