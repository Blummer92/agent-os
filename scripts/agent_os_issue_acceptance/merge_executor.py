"""A2 executor: perform an exact-head merge behind both gates (issue #3463).

The executor is the GitHub Service Agent's merge route. It merges
ONLY when two independent gates both pass, and it never merges on
one gate alone (the corrected both-gates rule, design QA B1):

- Gate 1: a positive, trigger-correlated Actions
  ``dispatch_receipt.json`` from the ``merge_admission`` run
  (status ``applicable``, ``merge_authorized`` true, checks passed,
  canonical applicability evaluated, no reason codes), consistent
  with the owner trigger comment, the reacquired authorization,
  and live PR evidence.
- Gate 2: fresh in-run canonical applicability — fresh
  reacquisition of both trusted sources, a fresh live PR evidence
  read, ``build_merge_proposal``, and
  ``evaluate_merge_authorization_applicability`` (the canonical
  merge evaluator; the same evaluator the Actions dispatch consumer
  calls at the end of its run). The executor does NOT call the full
  dispatch consumer (``evaluate_merge_dispatch_applicability``):
  that function is the Actions-workflow path — it derives its
  trigger, receipt, and lifecycle admission from workflow transport
  and a workflow GitHub client, which do not exist on the Service
  Agent route. Gate 1 covers the admission receipt separately, and
  the workflow's lifecycle admission has no Service Agent-route
  counterpart (the route's authorization IS the owner decision +
  trigger + receipt). The executor reuses the canonical evaluator
  rather than re-implementing its checks; implementation QA is
  asked to verify this equivalence (see the design's section 12).

Gate-1 trigger-id note (design section 12): the merge-admit
logical trigger id is computed by the workflow ingress
(``github_issue_comment_ingress``), not by any repo Python module
(verified by search). The executor therefore does NOT recompute
the trigger id from scratch — a recomputation from an unverified
formula would be worse than useless. Instead it verifies
four-way consistency: trigger comment grammar + author +
(pr, head, method) == authorization binding == live PR evidence
== dispatch receipt (authorization id, approval id, expected
head/method, status, flags). If receipt, trigger, authorization,
and live evidence all agree on (pr, head, method, authorization),
the receipt is for the same merge operation regardless of
trigger-id derivation. No single artifact is trusted alone.

Result vocabulary (do not conflate these):

- ``blocked``: a gate failed; no merge was attempted. Safe to retry
  after the underlying evidence changes, with fresh full
  evaluation (a retry never reuses a stale gate result).
- ``dry-run-applicable``: both gates passed in dry-run mode; no
  merge was attempted and nothing was posted. This is the
  acceptance path for negative cases and for canary preparation.
- ``merged``: the merge was performed, post-merge readback agreed,
  and the CONSUMED revision was posted and read back.
- ``failed``: the merge may have happened but post-merge
  verification or consumption failed. This is NOT a success and
  NOT a clean block: the caller must escalate (the merge cannot be
  undone; the missing CONSUMED post leaves the authorization
  CURRENT until expiry, which the merged-state gate must then
  contain). Never report ``failed`` as ``merged`` or ``blocked``.

Consumption uses the PRE-merge applicability and PRE-merge PR
evidence (``record_merge_execution_observation`` requires the
applicability's evidence id to equal the evidence it is observed
against, and the binding to be unchanged against that evidence).
Post-merge readback is a separate explicit step via the
``read_pr_state`` callable (``{merged, merge_commit_sha,
head_sha}``), because ``PullRequestMergeEvidence`` models an open
PR (draft XOR ready) and cannot represent a merged PR.

``decision_id`` is correlation/audit only, never a single-use
enforcement key (design QA B3). Single-use is the posted CONSUMED
revision plus the merged-state gate. A failed merge (blocked
before any merge call) may retry only with fresh full evaluation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping

from .approval_source import (
    ApprovalSourceTransport,
    reacquire_approval_source,
)
from .merge_approval import OWNER_ACTOR_ID, OWNER_LOGIN
from .merge_authorization import (
    PullRequestMergeEvidence,
    build_merge_proposal,
    evaluate_merge_authorization_applicability,
    record_merge_execution_observation,
)
from .merge_authorization_source import (
    AUTHORIZATION_MARKER,
    MergeAuthorizationSourceSnapshot,
    MergeAuthorizationSourceStatus,
    MergeAuthorizationSourceTransport,
    reacquire_merge_authorization_source,
    reconstruct_merge_authorization_record,
    serialize_merge_authorization_comment,
)

_TRIGGER_RE = re.compile(
    r"^/agent-os merge-admit (\d+) ([0-9a-f]{40}) ([0-9a-f]{64}) (merge|squash|rebase)$"
)
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")

ExecutorStatus = Literal["merged", "blocked", "dry-run-applicable", "failed"]


@dataclass(frozen=True, slots=True)
class MergeExecutorResult:
    status: ExecutorStatus
    reason_codes: tuple[str, ...]
    authorization_id: str | None
    approval_id: str | None
    merge_commit_sha: str | None = None
    consumed_authorization_revision: str | None = None
    details: tuple[str, ...] = ()


def _blocked(reason: str, *, authorization_id: str | None, approval_id: str | None, detail: str = "") -> MergeExecutorResult:
    return MergeExecutorResult(
        status="blocked",
        reason_codes=(reason,),
        authorization_id=authorization_id,
        approval_id=approval_id,
        details=(detail,) if detail else (),
    )


def _failed(reason: str, *, authorization_id: str | None, approval_id: str | None, detail: str = "") -> MergeExecutorResult:
    return MergeExecutorResult(
        status="failed",
        reason_codes=(reason,),
        authorization_id=authorization_id,
        approval_id=approval_id,
        details=(detail,) if detail else (),
    )


def _parse_trigger(trigger_comment: Mapping[str, Any]) -> tuple[int, str, str, str]:
    body = trigger_comment.get("body")
    if not isinstance(body, str):
        raise ValueError("trigger comment body must be a string")
    match = _TRIGGER_RE.fullmatch(body.strip())
    if match is None:
        raise ValueError("trigger comment does not match merge-admit grammar")
    pr_number = int(match.group(1))
    if pr_number < 1:
        raise ValueError("trigger PR number must be positive")
    return pr_number, match.group(2), match.group(3), match.group(4)


def _actor_matches(value: Any) -> bool:
    return str(value) == OWNER_ACTOR_ID


def execute_merge(
    *,
    repository: str,
    pr_number: int,
    trigger_comment: Mapping[str, Any],
    dispatch_receipt: Mapping[str, Any],
    read_pr_evidence: Callable[..., PullRequestMergeEvidence],
    approval_transport: ApprovalSourceTransport,
    authorization_transport: MergeAuthorizationSourceTransport,
    merge_pull_request: Callable[..., Mapping[str, Any]],
    post_comment: Callable[..., Any],
    read_pr_state: Callable[..., Mapping[str, Any]],
    evaluated_at: str,
    dry_run: bool = False,
) -> MergeExecutorResult:
    """Run both merge gates and, unless dry-run, the exact-head merge.

    Callables supplied by the Service Agent route: ``read_pr_evidence``
    (live PR evidence read), ``merge_pull_request`` (returns
    ``{merge_commit_sha, actor_id}``), ``post_comment`` (same shape as
    the producer's), ``read_pr_state`` (returns ``{merged,
    merge_commit_sha, head_sha}``). Transports are the existing
    trusted-source read protocols. Every gate failure returns
    ``blocked`` without a merge call; every post-merge failure
    returns ``failed`` (see the module docstring — never conflate
    the two).
    """
    # Gate 1, part 1: trigger comment grammar + owner authorship.
    try:
        trigger_pr, trigger_head, _trigger_body_sha, trigger_method = _parse_trigger(trigger_comment)
        if trigger_comment.get("author_login") != OWNER_LOGIN:
            return _blocked("trigger.author-not-owner", authorization_id=None, approval_id=None)
        if not _actor_matches(trigger_comment.get("author_id")):
            return _blocked("trigger.actor-not-owner", authorization_id=None, approval_id=None)
        if trigger_pr != pr_number:
            return _blocked("trigger.pr-mismatch", authorization_id=None, approval_id=None)
    except (ValueError, TypeError, AttributeError) as exc:
        return _blocked("trigger.invalid", authorization_id=None, approval_id=None, detail=str(exc))

    # Gate 1, part 2: dispatch receipt consistency.
    try:
        receipt_authorization_id = dispatch_receipt.get("authorization_id")
        receipt_approval_id = dispatch_receipt.get("approval_id")
        if dispatch_receipt.get("schema_version") != "1.0":
            return _blocked("receipt.schema-unsupported", authorization_id=None, approval_id=None)
        if dispatch_receipt.get("operation") != "merge-dispatch-applicability":
            return _blocked("receipt.operation-mismatch", authorization_id=None, approval_id=None)
        if dispatch_receipt.get("repository") != repository:
            return _blocked("receipt.repository-mismatch", authorization_id=None, approval_id=None)
        if dispatch_receipt.get("pr_number") != pr_number:
            return _blocked("receipt.pr-mismatch", authorization_id=None, approval_id=None)
        trigger_id = dispatch_receipt.get("logical_trigger_id")
        if not isinstance(trigger_id, str) or not trigger_id.startswith("issue-comment-trigger:"):
            return _blocked("receipt.trigger-id-malformed", authorization_id=None, approval_id=None)
        if dispatch_receipt.get("expected_head_sha") != trigger_head:
            return _blocked("receipt.head-mismatch", authorization_id=None, approval_id=None)
        if dispatch_receipt.get("expected_method") != trigger_method:
            return _blocked("receipt.method-mismatch", authorization_id=None, approval_id=None)
        if not isinstance(receipt_authorization_id, str) or not receipt_authorization_id:
            return _blocked("receipt.authorization-missing", authorization_id=None, approval_id=None)
        if not isinstance(receipt_approval_id, str) or not receipt_approval_id:
            return _blocked("receipt.approval-missing", authorization_id=None, approval_id=None)
        if dispatch_receipt.get("status") != "applicable":
            return _blocked(
                "receipt.not-applicable", authorization_id=receipt_authorization_id,
                approval_id=receipt_approval_id,
            )
        if dispatch_receipt.get("merge_authorized") is not True:
            return _blocked(
                "receipt.not-authorized", authorization_id=receipt_authorization_id,
                approval_id=receipt_approval_id,
            )
        if dispatch_receipt.get("dispatch_checks_passed") is not True:
            return _blocked(
                "receipt.checks-not-passed", authorization_id=receipt_authorization_id,
                approval_id=receipt_approval_id,
            )
        if dispatch_receipt.get("canonical_applicability_evaluated") is not True:
            return _blocked(
                "receipt.canonical-not-evaluated", authorization_id=receipt_authorization_id,
                approval_id=receipt_approval_id,
            )
        if dispatch_receipt.get("reason_codes") not in ([], ()):
            return _blocked(
                "receipt.has-reasons", authorization_id=receipt_authorization_id,
                approval_id=receipt_approval_id,
            )
    except (AttributeError, TypeError) as exc:
        return _blocked("receipt.invalid", authorization_id=None, approval_id=None, detail=str(exc))

    # Gate 2, part 1: fresh reacquisition of both trusted sources.
    try:
        authorization_result = reacquire_merge_authorization_source(
            transport=authorization_transport,
            repository=repository,
            pr_number=pr_number,
            expected_authorization_id=receipt_authorization_id,
        )
    except Exception as exc:  # transport failure fails closed
        return _blocked(
            "authorization.record-unavailable-at-dispatch",
            authorization_id=receipt_authorization_id, approval_id=receipt_approval_id,
            detail=str(exc),
        )
    if authorization_result.status != MergeAuthorizationSourceStatus.CURRENT:
        return _blocked(
            "authorization.record-unavailable-at-dispatch",
            authorization_id=receipt_authorization_id, approval_id=receipt_approval_id,
            detail=",".join(authorization_result.reason_codes),
        )
    matching = [
        record
        for record in authorization_result.records
        if record.authorization_id == receipt_authorization_id
    ]
    if len(matching) != 1:
        return _blocked(
            "authorization.record-unavailable-at-dispatch",
            authorization_id=receipt_authorization_id, approval_id=receipt_approval_id,
        )
    authorization = matching[0]
    binding = authorization.binding
    if (
        binding.repository != repository
        or binding.pull_request_number != pr_number
        or binding.exact_head_sha != trigger_head
        or binding.permitted_merge_method != trigger_method
        or binding.approval_id != receipt_approval_id
    ):
        return _blocked(
            "authorization.binding-mismatch",
            authorization_id=receipt_authorization_id, approval_id=receipt_approval_id,
        )
    try:
        approval_result = reacquire_approval_source(
            transport=approval_transport,
            repository=repository,
            pr_number=pr_number,
            expected_approval_id=binding.approval_id,
        )
    except Exception as exc:  # transport failure fails closed
        return _blocked(
            "approval-source-not-current",
            authorization_id=receipt_authorization_id, approval_id=receipt_approval_id,
            detail=str(exc),
        )
    if approval_result.status.value != "current":
        return _blocked(
            "approval-source-not-current",
            authorization_id=receipt_authorization_id, approval_id=receipt_approval_id,
            detail=",".join(approval_result.reason_codes),
        )
    approval = approval_result.approval
    applicability = approval_result.applicability
    projection = approval_result.projection
    if approval is None or applicability is None or projection is None:
        return _blocked(
            "approval-source-not-current",
            authorization_id=receipt_authorization_id, approval_id=receipt_approval_id,
        )
    if (
        approval.approval_id != binding.approval_id
        or approval.approval_revision != binding.approval_revision
    ):
        return _blocked(
            "authorization.binding-mismatch",
            authorization_id=receipt_authorization_id, approval_id=receipt_approval_id,
        )

    # Gate 2, part 2: fresh live PR evidence + canonical applicability.
    try:
        pr_evidence = read_pr_evidence(repository, pr_number)
    except Exception as exc:
        return _blocked(
            "evidence.unavailable",
            authorization_id=receipt_authorization_id, approval_id=receipt_approval_id,
            detail=str(exc),
        )
    if not isinstance(pr_evidence, PullRequestMergeEvidence):
        return _blocked(
            "evidence.invalid",
            authorization_id=receipt_authorization_id, approval_id=receipt_approval_id,
        )
    if (
        pr_evidence.repository != repository
        or pr_evidence.pull_request_number != pr_number
        or pr_evidence.head_sha != trigger_head
        or pr_evidence.base_branch != binding.target_base_branch
        or pr_evidence.base_sha_or_evidence_id != binding.base_sha_or_evidence_id
        or pr_evidence.proposed_merge_method != trigger_method
        or pr_evidence.draft
    ):
        return _blocked(
            "evidence.mismatch",
            authorization_id=receipt_authorization_id, approval_id=receipt_approval_id,
        )
    try:
        proposal = build_merge_proposal(approval, applicability, projection, pr_evidence)
    except (TypeError, ValueError) as exc:
        return _blocked(
            "merge-proposal-evidence-invalid",
            authorization_id=receipt_authorization_id, approval_id=receipt_approval_id,
            detail=str(exc),
        )
    try:
        canonical = evaluate_merge_authorization_applicability(
            authorization,
            approval,
            applicability,
            projection,
            pr_evidence,
            current_proposal=proposal,
            current_issueplan_evidence=None,
            current_repository_state_evidence=None,
            evaluated_at=evaluated_at,
        )
    except (TypeError, ValueError) as exc:
        return _blocked(
            "canonical-applicability-error",
            authorization_id=receipt_authorization_id, approval_id=receipt_approval_id,
            detail=str(exc),
        )
    if (
        canonical.status != "applicable"
        or not canonical.merge_authorized
        or canonical.authorization_id != authorization.authorization_id
        or canonical.authorization_revision != authorization.authorization_revision
        or canonical.current_pull_request_evidence_id != pr_evidence.evidence_id
    ):
        return _blocked(
            "canonical-not-applicable",
            authorization_id=receipt_authorization_id, approval_id=receipt_approval_id,
            detail=",".join(canonical.reason_codes),
        )

    if dry_run:
        return MergeExecutorResult(
            status="dry-run-applicable",
            reason_codes=(),
            authorization_id=authorization.authorization_id,
            approval_id=approval.approval_id,
        )

    # Merge: exact head, bound method, nothing else.
    try:
        merge_result = merge_pull_request(
            repository=repository,
            pr_number=pr_number,
            sha=trigger_head,
            method=trigger_method,
        )
    except Exception as exc:
        return _failed(
            "merge.call-failed",
            authorization_id=authorization.authorization_id, approval_id=approval.approval_id,
            detail=str(exc),
        )
    if not isinstance(merge_result, Mapping):
        return _failed(
            "merge.result-invalid",
            authorization_id=authorization.authorization_id, approval_id=approval.approval_id,
        )
    merge_commit = merge_result.get("merge_commit_sha")
    if not isinstance(merge_commit, str) or _SHA40_RE.fullmatch(merge_commit) is None:
        return _failed(
            "merge.result-invalid",
            authorization_id=authorization.authorization_id, approval_id=approval.approval_id,
        )
    if not _actor_matches(merge_result.get("actor_id")):
        return _failed(
            "merge.actor-mismatch",
            authorization_id=authorization.authorization_id, approval_id=approval.approval_id,
        )

    # Post-merge readback: merged state must agree with the merge call.
    try:
        state = read_pr_state(repository, pr_number)
    except Exception as exc:
        return _failed(
            "merge.readback-unavailable",
            authorization_id=authorization.authorization_id, approval_id=approval.approval_id,
            detail=str(exc),
        )
    if (
        not isinstance(state, Mapping)
        or state.get("merged") is not True
        or state.get("merge_commit_sha") != merge_commit
        or state.get("head_sha") != trigger_head
    ):
        return _failed(
            "merge.readback-mismatch",
            authorization_id=authorization.authorization_id, approval_id=approval.approval_id,
        )

    # Consumption: pre-merge applicability + pre-merge evidence, observed
    # merge only. Any failure here is "failed", never "merged": the
    # merge happened but the single-use record is missing.
    try:
        _observation, consumed = record_merge_execution_observation(
            authorization,
            canonical,
            pr_evidence,
            observed_merge_commit_sha=merge_commit,
            observed_actor_id=OWNER_ACTOR_ID,
            observed_at=evaluated_at,
            audit_location=f"github:{repository}#{pr_number}",
            observed_merge_method=trigger_method,
        )
    except (TypeError, ValueError) as exc:
        return _failed(
            "merge.consumption-failed",
            authorization_id=authorization.authorization_id, approval_id=approval.approval_id,
            detail=str(exc),
        )
    try:
        post_comment(
            repository=repository,
            pr_number=pr_number,
            body=serialize_merge_authorization_comment(consumed),
        )
    except Exception as exc:
        return _failed(
            "merge.consumed-post-failed",
            authorization_id=authorization.authorization_id, approval_id=approval.approval_id,
            detail=str(exc),
        )
    try:
        consumed_result = reacquire_merge_authorization_source(
            transport=authorization_transport,
            repository=repository,
            pr_number=pr_number,
            expected_authorization_id=authorization.authorization_id,
        )
    except Exception as exc:
        return _failed(
            "merge.consumed-readback-failed",
            authorization_id=authorization.authorization_id, approval_id=approval.approval_id,
            detail=str(exc),
        )
    # The authorization reader intentionally returns only AUTHORIZED
    # records: after a CONSUMED post it returns STALE
    # (consumed-or-not-current) with an EMPTY record list. STALE
    # alone proves replay is blocked (latest revision is not
    # AUTHORIZED) but does not prove the latest revision IS the
    # CONSUMED one this run posted — so the executor additionally
    # verifies the exact CONSUMED revision at snapshot level, using
    # the canonical reconstruct function. This is a readback, not a
    # parallel authorization decision: no allow/deny judgment is
    # made here beyond confirming the posted revision.
    if (
        consumed_result.status != MergeAuthorizationSourceStatus.STALE
        or "authorization.consumed-or-not-current" not in consumed_result.reason_codes
    ):
        return _failed(
            "merge.consumed-readback-failed",
            authorization_id=authorization.authorization_id, approval_id=approval.approval_id,
            detail=f"reader status {consumed_result.status.value}",
        )
    try:
        snapshot = authorization_transport.read_merge_authorization_source(
            repository, pr_number
        )
    except Exception as exc:
        return _failed(
            "merge.consumed-readback-failed",
            authorization_id=authorization.authorization_id, approval_id=approval.approval_id,
            detail=str(exc),
        )
    if (
        type(snapshot) is not MergeAuthorizationSourceSnapshot
        or snapshot.repository.casefold() != repository.casefold()
        or snapshot.pr_number != pr_number
        or snapshot.owner_type != "User"
        or not snapshot.comments_complete
    ):
        return _failed(
            "merge.consumed-readback-failed",
            authorization_id=authorization.authorization_id, approval_id=approval.approval_id,
        )
    try:
        found_consumed = False
        for item in sorted(snapshot.comments, key=lambda value: (value.created_at, value.comment_id)):
            if (
                item.author_login.casefold() != snapshot.owner_login.casefold()
                or not item.body.startswith(AUTHORIZATION_MARKER + "\n")
            ):
                continue
            payload = item.body[len(AUTHORIZATION_MARKER) + 1 :]
            if "\n" in payload:
                return _failed(
                    "merge.consumed-readback-failed",
                    authorization_id=authorization.authorization_id,
                    approval_id=approval.approval_id,
                )
            record = reconstruct_merge_authorization_record(payload)
            if record.authorization_id != authorization.authorization_id:
                continue
            if (
                record.state.value == "consumed"
                and record.authorization_revision == consumed.authorization_revision
                and record.revision_number == consumed.revision_number
            ):
                found_consumed = True
    except (TypeError, ValueError) as exc:
        return _failed(
            "merge.consumed-readback-failed",
            authorization_id=authorization.authorization_id, approval_id=approval.approval_id,
            detail=str(exc),
        )
    if not found_consumed:
        return _failed(
            "merge.consumed-readback-failed",
            authorization_id=authorization.authorization_id, approval_id=approval.approval_id,
        )
    return MergeExecutorResult(
        status="merged",
        reason_codes=(),
        authorization_id=authorization.authorization_id,
        approval_id=approval.approval_id,
        merge_commit_sha=merge_commit,
        consumed_authorization_revision=consumed.authorization_revision,
    )
