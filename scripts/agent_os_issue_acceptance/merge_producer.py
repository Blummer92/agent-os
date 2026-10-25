"""E2 producer: post a merge approval triple and merge authorization (issue #3463).

The producer is the GitHub Service Agent's posting path for the
merge-approval repair. It takes an exact owner merge decision plus
live PR evidence, builds the triple with the merge adapter
(:mod:`merge_approval`), builds the merge authorization with the
existing canonical builders, posts all four records to the target
PR's conversation, and readbacks both trusted sources before
reporting success.

Posting contract (design section 8):

- ``post_comment`` is a callable ``post_comment(*, repository,
  pr_number, body) -> comment_id`` supplied by the route (the
  Service Agent client in production; a fake in tests). This module
  defines no transport of its own and performs no GitHub I/O
  itself.
- Reads use the existing transport protocols
  (``ApprovalSourceTransport``,
  ``MergeAuthorizationSourceTransport``) and the existing trusted
  readers. The producer never trusts its own posts: it returns
  success only when ``reacquire_approval_source`` is CURRENT for
  the approval id and ``reacquire_merge_authorization_source`` is
  CURRENT for the authorization id, with exact comment authorship
  (comment author == snapshot owner login, ``User`` type — the
  reader enforces this; the record's ``authorizer_id`` field is NOT
  verified by any reader, see N-4) and exact content
  (reconstruction + id/revision linkage).
- Failure semantics: on a readback failure the producer RAISES. The
  posted records are NOT retracted (there is no delete path);
  "not verified" is not "not posted". Dispatch will independently
  fail closed unless a later readback succeeds, because the records
  themselves are valid — only this producer's verification failed.
  Callers must surface a producer failure, never proceed to
  dispatch on it.
- The producer posts NOTHING else and never merges. It is not a
  renderer: its output is posted records verified by readback.
- The merge authorization's expiry is the decision's expiry, and
  the canonical builders enforce that it cannot outlive the
  approval's expiry (same value here, so the constraint holds by
  construction).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .approval_records import (
    serialize_approval_applicability_result,
    serialize_approval_record,
)
from .approval_source import (
    APPLICABILITY_MARKER,
    APPROVAL_MARKER,
    PROJECTION_MARKER,
    ApprovalSourceTransport,
    reacquire_approval_source,
    serialize_approval_comment,
)
from .approved_execution_projection import (
    serialize_approved_execution_projection,
)
from .merge_approval import (
    MergeApprovalDecision,
    build_merge_approval_triple,
)
from .merge_authorization import (
    MergeAuthorizationState,
    PullRequestMergeEvidence,
    build_merge_authorization_candidate,
    build_merge_proposal,
    record_merge_authorization_decision,
)
from .merge_authorization_source import (
    MergeAuthorizationSourceStatus,
    MergeAuthorizationSourceTransport,
    reacquire_merge_authorization_source,
    serialize_merge_authorization_comment,
)

PostComment = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class MergeProducerResult:
    approval_id: str
    approval_revision: str
    authorization_id: str
    authorization_revision: str
    approval_source_status: str
    authorization_source_status: str
    posted_comment_ids: tuple[Any, ...]


def produce_merge_authorization(
    decision: MergeApprovalDecision,
    pr_evidence: PullRequestMergeEvidence,
    *,
    evaluated_at: str,
    post_comment: PostComment,
    approval_transport: ApprovalSourceTransport,
    authorization_transport: MergeAuthorizationSourceTransport,
) -> MergeProducerResult:
    """Post a merge approval triple + merge authorization, verified by readback.

    Raises ``TypeError``/``ValueError`` on invalid inputs or on any
    readback that is not CURRENT. See the module docstring for the
    failure semantics: a raise after posting means "not verified",
    never "not posted".
    """
    if not isinstance(decision, MergeApprovalDecision):
        raise TypeError("decision must be a MergeApprovalDecision")
    if not isinstance(pr_evidence, PullRequestMergeEvidence):
        raise TypeError("pr_evidence must be a PullRequestMergeEvidence")
    if not callable(post_comment):
        raise TypeError("post_comment must be callable")

    approval, applicability, projection = build_merge_approval_triple(
        decision, pr_evidence, evaluated_at=evaluated_at
    )
    posted: list[Any] = []
    posted.append(
        post_comment(
            repository=decision.repository,
            pr_number=decision.pr_number,
            body=serialize_approval_comment(
                APPROVAL_MARKER, serialize_approval_record(approval)
            ),
        )
    )
    posted.append(
        post_comment(
            repository=decision.repository,
            pr_number=decision.pr_number,
            body=serialize_approval_comment(
                APPLICABILITY_MARKER,
                serialize_approval_applicability_result(applicability),
            ),
        )
    )
    posted.append(
        post_comment(
            repository=decision.repository,
            pr_number=decision.pr_number,
            body=serialize_approval_comment(
                PROJECTION_MARKER,
                serialize_approved_execution_projection(projection),
            ),
        )
    )

    proposal = build_merge_proposal(approval, applicability, projection, pr_evidence)
    candidate = build_merge_authorization_candidate(
        approval,
        applicability,
        projection,
        pr_evidence,
        current_proposal=proposal,
        current_issueplan_evidence=None,
        current_repository_state_evidence=None,
        authorizer_id=decision.authorizer_id,
        decision_id=decision.decision_id,
        decision_at=decision.decision_at,
        expires_at=decision.expires_at,
        permitted_merge_method=decision.merge_method,
    )
    authorized = record_merge_authorization_decision(
        candidate,
        state=MergeAuthorizationState.AUTHORIZED,
        decision_id=decision.decision_id,
        authorizer_id=decision.authorizer_id,
        decision_at=decision.decision_at,
        details=("merge-authorization:authorized",),
    )
    posted.append(
        post_comment(
            repository=decision.repository,
            pr_number=decision.pr_number,
            body=serialize_merge_authorization_comment(authorized),
        )
    )

    approval_result = reacquire_approval_source(
        transport=approval_transport,
        repository=decision.repository,
        pr_number=decision.pr_number,
        expected_approval_id=approval.approval_id,
    )
    if approval_result.status.value != "current":
        raise ValueError(
            "producer readback failed: approval source is "
            f"{approval_result.status.value} ({','.join(approval_result.reason_codes)})"
        )
    authorization_result = reacquire_merge_authorization_source(
        transport=authorization_transport,
        repository=decision.repository,
        pr_number=decision.pr_number,
        expected_authorization_id=authorized.authorization_id,
    )
    if authorization_result.status != MergeAuthorizationSourceStatus.CURRENT:
        raise ValueError(
            "producer readback failed: authorization source is "
            f"{authorization_result.status.value} ({','.join(authorization_result.reason_codes)})"
        )
    matching = [
        record
        for record in authorization_result.records
        if record.authorization_id == authorized.authorization_id
    ]
    if len(matching) != 1 or matching[0].authorization_revision != authorized.authorization_revision:
        raise ValueError(
            "producer readback failed: authorization record mismatch after posting"
        )
    return MergeProducerResult(
        approval_id=approval.approval_id,
        approval_revision=approval.approval_revision,
        authorization_id=authorized.authorization_id,
        authorization_revision=authorized.authorization_revision,
        approval_source_status=approval_result.status.value,
        authorization_source_status=authorization_result.status.value,
        posted_comment_ids=tuple(posted),
    )
