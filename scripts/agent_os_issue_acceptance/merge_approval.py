"""Merge-specific approval construction (issue #3463, Option A / design A1).

This module is the one missing link in the governed merge pipeline:
it builds a canonical approval triple (approval record, applicability
result, approved execution projection) for a merge from a genuine
owner merge decision plus live pull-request evidence, without
fabricating planning evidence.

What it does NOT do, by design:

- It never constructs a ``DraftTaskProposal``, an
  ``IssuePlanCurrentStateEvidence``, or a ``RepositoryStateEvidence``.
  The planning constructors (``build_approval_candidate``,
  ``evaluate_approval_applicability``,
  ``build_approved_execution_projection``) are planning-only and are
  left untouched; this module builds the three records with the
  dataclasses directly and validates them against merge inputs.
- It never bypasses the trusted approval-triple reader. The records
  it produces are verified at dispatch by the unchanged
  ``reacquire_approval_source`` (linkage, states, reconstruction)
  and by ``build_merge_proposal`` / ``_merge_proposal_binding``
  (triple consistency plus live PR evidence). What it bypasses is
  only the planning constructors, which are a planning boundary,
  not a merge trust boundary.
- It never posts anything and never merges. Posting is the E2
  producer's job (``merge_producer``); merging is the A2 executor's
  job (``merge_executor``). By convention this constructor is invoked
  only from the producer; no import restriction enforces that, so
  the convention is documented here and in the merge-admission docs
  as a process control (Phase 4 QA finding N-4).

Field-name honesty (Phase 4 QA Q12): the ``ApprovalBinding`` container
reuses planning-named fields. For merge approvals those fields carry
merge-derived hashes, documented here field by field; no consumer
verifies any of them against a planning store (they are equality
tokens, or ignored by the merge branch), so the reuse is a naming
debt, not invented planning evidence:

- ``proposal_id``: ``merge-approval:<sha256>`` (design A1 additive
  prefix; the ``draft-task-proposal:`` prefix is never used here, so
  a merge record cannot be mistaken for planning provenance by its
  primary identifier).
- ``proposal_version``: ``"merge-approval/1"`` (distinguishing mark).
- ``handoff_digest``: SHA-256 of the canonical decision artifact
  JSON. No handoff exists; the field carries the decision digest.
- ``graph_digest``: SHA-256 of the canonical scope (allowed files,
  forbidden paths, scope fingerprint). No graph exists.
- ``planning_result_digest``: SHA-256 of canonical PR evidence
  (head, base, checks, reviews, metadata). No planning result
  exists.
- ``issueplan_current_state_evidence_id``:
  ``issueplan-current-state:<sha256>`` of the canonical merge
  current state (decision + PR evidence + expiry). The legacy
  planning name is kept deliberately (A1b rejected as unnecessary:
  the field is a secondary equality token, never looked up, never
  compared by the merge branch).
- ``scanner_result_fingerprint``: SHA-256 of canonical required-check
  evidence. No scanner ran.
- ``supplied_node_ids`` / ``cohort_summaries``: a single node naming
  the merge operation (``merge:<repository>:<pr_number>``) in a single
  cohort classified ``"merge"``. This is an operation identifier,
  not planning nodes; it would fail ``_verified_proposal``'s
  ``parallel-candidate`` requirement, which is the fail-closed
  cross-use property, not a defect.
- ``evaluated_repository_sha`` / ``evaluator_commit_sha``: the base
  SHA at decision time (the evaluation anchor for a merge).
- ``repository_evidence_type``: ``"branch-head"`` — the tested
  repository genuinely is the PR branch head.
- ``approval_kind``: ``SOURCE_MUTATION`` — a merge mutates the
  target branch's source. No production code branches on kind.

Trust notes the implementation must not overstate (Phase 4 QA
N-4, Q3, Q4):

- The record's ``authorizer_id`` field is NOT verified by any reader
  or evaluator; the operative authorship check is comment author ==
  snapshot owner login (+ ``User`` type) at readback.
- ``decision_id`` is a content hash (integrity), not a signature
  (authenticity). The adapter verifies ``decision_id`` against the
  decision + PR evidence (integrity), but D's authorship rests on
  D's provenance channel, an owner-process control.
- Revocation (Phase 4 QA B-1): posting a revocation revision
  alongside the approved revision makes the approval reader return
  ``NEEDS_DECISION`` (``source.trusted-record-malformed``), NOT
  ``STALE``. Dispatch still blocks (non-``current`` status), but
  the diagnostic reads as corruption. Do not "fix" this by changing
  the approval reader inside this slice; that needs separate
  authorization.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .approval_records import (
    APPROVAL_RECORD_SCHEMA_VERSION,
    ApprovalApplicabilityResult,
    ApprovalBinding,
    ApprovalKind,
    ApprovalRecord,
    ApprovalState,
    reconstruct_approval_applicability_result,
    reconstruct_approval_record,
    record_approval_decision,
    serialize_approval_applicability_result,
    serialize_approval_record,
)
from .approved_execution_projection import (
    APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION,
    ApprovedExecutionProjection,
    reconstruct_approved_execution_projection,
    serialize_approved_execution_projection,
)
from .merge_authorization import (
    PullRequestMergeEvidence,
    build_merge_proposal,
)
from .scheduler_handoff import HandoffCohort

# Verified owner actor (GitHub user Blummer92, type User). The merge
# admission workflow enforces the same actor id (user.id == 32861845).
OWNER_ACTOR_ID = "32861845"
OWNER_LOGIN = "Blummer92"

MERGE_METHODS = frozenset({"merge", "squash", "rebase"})
PROPOSAL_VERSION = "merge-approval/1"

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _sha256_hex(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or _TIMESTAMP_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must use UTC ...Z timestamp form")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"{name} is not a valid timestamp") from exc


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class MergeApprovalDecision:
    """An exact owner merge decision, held outside the posting session.

    ``decision_id`` is the SHA-256 of the canonical decision tuple
    (see :func:`merge_decision_id`); the adapter recomputes it from
    the decision fields plus live PR evidence and refuses any
    decision whose id does not match. That check proves integrity
    (the fields were not altered after the id was computed), not
    authorship (anyone holding the tuple can recompute it).
    """

    repository: str
    pr_number: int
    head_sha: str
    base_branch: str
    base_sha_or_evidence_id: str
    merge_method: str
    authorizer_id: str
    decision_id: str
    decision_at: str
    expires_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.repository, str) or self.repository.count("/") != 1:
            raise ValueError("repository must use owner/name form")
        if not isinstance(self.pr_number, int) or isinstance(self.pr_number, bool):
            raise ValueError("pr_number must be an integer")
        if self.pr_number < 1:
            raise ValueError("pr_number must be positive")
        if not isinstance(self.head_sha, str) or _SHA40_RE.fullmatch(self.head_sha) is None:
            raise ValueError("head_sha must be SHA-40 hex")
        _text(self.base_branch, "base_branch")
        # N-2: binding SHA fields require SHA-40. PR evidence also
        # allows a canonical evidence id, but a merge approval
        # refuses that form rather than coercing it.
        if (
            not isinstance(self.base_sha_or_evidence_id, str)
            or _SHA40_RE.fullmatch(self.base_sha_or_evidence_id) is None
        ):
            raise ValueError(
                "base_sha_or_evidence_id must be SHA-40 hex for a merge approval"
            )
        if self.merge_method not in MERGE_METHODS:
            raise ValueError("unsupported merge_method")
        _text(self.authorizer_id, "authorizer_id")
        if not isinstance(self.decision_id, str) or _SHA256_RE.fullmatch(self.decision_id) is None:
            raise ValueError("decision_id must be SHA-256 hex")
        decision_time = _parse_timestamp(self.decision_at, "decision_at")
        expiry_time = _parse_timestamp(self.expires_at, "expires_at")
        if expiry_time <= decision_time:
            raise ValueError("expires_at must be after decision_at")


def merge_decision_id(
    *,
    repository: str,
    pr_number: int,
    head_sha: str,
    base_branch: str,
    base_sha_or_evidence_id: str,
    merge_method: str,
    changed_scope_fingerprint: str,
    pr_metadata_sha256: str,
    expires_at: str,
) -> str:
    """Compute the canonical decision id for a merge decision tuple."""
    return _sha256_hex(
        {
            "base_branch": base_branch,
            "base_sha_or_evidence_id": base_sha_or_evidence_id,
            "changed_scope_fingerprint": changed_scope_fingerprint,
            "expires_at": expires_at,
            "head_sha": head_sha,
            "merge_method": merge_method,
            "pr_metadata_sha256": pr_metadata_sha256,
            "pr_number": pr_number,
            "repository": repository,
        }
    )


def _decision_payload(decision: MergeApprovalDecision) -> dict[str, Any]:
    return {
        "authorizer_id": decision.authorizer_id,
        "base_branch": decision.base_branch,
        "base_sha_or_evidence_id": decision.base_sha_or_evidence_id,
        "decision_at": decision.decision_at,
        "decision_id": decision.decision_id,
        "expires_at": decision.expires_at,
        "head_sha": decision.head_sha,
        "merge_method": decision.merge_method,
        "pr_number": decision.pr_number,
        "repository": decision.repository,
    }


def _check_payload(check: Any) -> list[Any]:
    return [
        getattr(check, "context"),
        getattr(check, "app_identity"),
        getattr(check, "tested_sha"),
        getattr(check, "evidence_id"),
        getattr(check, "state"),
    ]


def build_merge_approval_triple(
    decision: MergeApprovalDecision,
    pr_evidence: PullRequestMergeEvidence,
    *,
    evaluated_at: str,
) -> tuple[ApprovalRecord, ApprovalApplicabilityResult, ApprovedExecutionProjection]:
    """Build a canonical approval triple for one exact merge.

    Validates the decision against live PR evidence, derives the
    binding from decision + PR facts (see module docstring), builds
    the approval through the existing generic state machine, and
    self-verifies the triple (serialize/reconstruct round-trip plus
    ``build_merge_proposal``) before returning it. Raises
    ``TypeError``/``ValueError`` on any forged, stale, expired,
    revoked-prerequisite, or mismatched input; it never returns a
    triple it has not verified.
    """
    if not isinstance(decision, MergeApprovalDecision):
        raise TypeError("decision must be a MergeApprovalDecision")
    if not isinstance(pr_evidence, PullRequestMergeEvidence):
        raise TypeError("pr_evidence must be a PullRequestMergeEvidence")
    evaluated_time = _parse_timestamp(evaluated_at, "evaluated_at")
    decision_time = _parse_timestamp(decision.decision_at, "decision_at")
    expiry_time = _parse_timestamp(decision.expires_at, "expires_at")
    if evaluated_time < decision_time:
        raise ValueError("merge approval cannot be evaluated before its decision")
    if evaluated_time >= expiry_time:
        raise ValueError("merge approval decision is expired")

    # Section 3 validation: decision vs live PR evidence, every field.
    if decision.authorizer_id != OWNER_ACTOR_ID:
        raise ValueError("merge approval decision authorizer is not the verified owner actor")
    if decision.repository != pr_evidence.repository:
        raise ValueError("decision repository does not match PR evidence")
    if decision.pr_number != pr_evidence.pull_request_number:
        raise ValueError("decision PR number does not match PR evidence")
    if decision.head_sha != pr_evidence.head_sha:
        raise ValueError("decision head does not match PR evidence")
    if decision.base_branch != pr_evidence.base_branch:
        raise ValueError("decision base branch does not match PR evidence")
    if decision.base_sha_or_evidence_id != pr_evidence.base_sha_or_evidence_id:
        raise ValueError("decision base identity does not match PR evidence")
    if decision.merge_method != pr_evidence.proposed_merge_method:
        raise ValueError("decision merge method does not match PR evidence")
    expected_decision_id = merge_decision_id(
        repository=decision.repository,
        pr_number=decision.pr_number,
        head_sha=decision.head_sha,
        base_branch=decision.base_branch,
        base_sha_or_evidence_id=decision.base_sha_or_evidence_id,
        merge_method=decision.merge_method,
        changed_scope_fingerprint=pr_evidence.changed_scope_fingerprint,
        pr_metadata_sha256=pr_evidence.pr_metadata_sha256,
        expires_at=decision.expires_at,
    )
    if decision.decision_id != expected_decision_id:
        raise ValueError("decision_id does not match decision content")
    if pr_evidence.draft:
        raise ValueError("merge approval refuses a draft PR")
    if not pr_evidence.ready_for_review:
        raise ValueError("merge approval requires a ready PR")

    allowed = tuple(pr_evidence.allowed_files)
    forbidden = tuple(pr_evidence.forbidden_paths)
    required_tests = tuple(pr_evidence.required_tests)
    checks = sorted(
        (_check_payload(check) for check in pr_evidence.required_checks),
        key=lambda item: (str(item[0]), str(item[1]), str(item[2]), str(item[3]), str(item[4])),
    )
    review = pr_evidence.review_evidence

    merge_identity = _sha256_hex(
        {
            "base_branch": decision.base_branch,
            "base_sha_or_evidence_id": decision.base_sha_or_evidence_id,
            "changed_scope_fingerprint": pr_evidence.changed_scope_fingerprint,
            "head_sha": decision.head_sha,
            "merge_method": decision.merge_method,
            "pr_metadata_sha256": pr_evidence.pr_metadata_sha256,
            "pr_number": decision.pr_number,
            "repository": decision.repository,
        }
    )
    proposal_id = f"merge-approval:{merge_identity}"
    node_id = f"merge:{decision.repository}:{decision.pr_number}"

    binding = ApprovalBinding(
        proposal_version=PROPOSAL_VERSION,
        proposal_id=proposal_id,
        handoff_digest=_sha256_hex(_decision_payload(decision)),
        graph_digest=_sha256_hex(
            {
                "allowed_files": list(allowed),
                "changed_scope_fingerprint": pr_evidence.changed_scope_fingerprint,
                "forbidden_paths": list(forbidden),
            }
        ),
        planning_result_digest=_sha256_hex(
            {
                "base_branch": decision.base_branch,
                "base_sha_or_evidence_id": decision.base_sha_or_evidence_id,
                "head_sha": decision.head_sha,
                "pr_metadata_sha256": pr_evidence.pr_metadata_sha256,
                "required_checks": checks,
                "review": {
                    "blocking_review_present": review.blocking_review_present,
                    "exact_head_reviewed": review.exact_head_reviewed,
                    "unresolved_conversation_count": review.unresolved_conversation_count,
                },
            }
        ),
        repository=decision.repository,
        base_branch=decision.base_branch,
        evaluated_repository_sha=decision.base_sha_or_evidence_id,
        evaluator_commit_sha=decision.base_sha_or_evidence_id,
        supplied_node_ids=(node_id,),
        cohort_summaries=(
            HandoffCohort(node_ids=(node_id,), classification="merge", reason_codes=()),
        ),
        issueplan_current_state_evidence_id=(
            "issueplan-current-state:"
            + _sha256_hex(
                {
                    "changed_scope_fingerprint": pr_evidence.changed_scope_fingerprint,
                    "decision": _decision_payload(decision),
                    "expires_at": decision.expires_at,
                    "pr_metadata_sha256": pr_evidence.pr_metadata_sha256,
                }
            )
        ),
        repository_state_evidence_id=_sha256_hex(
            {
                "base_sha_or_evidence_id": decision.base_sha_or_evidence_id,
                "head_sha": decision.head_sha,
                "repository": decision.repository,
            }
        ),
        repository_evidence_type="branch-head",
        tested_repository_sha=decision.head_sha,
        source_snapshot_fingerprint=_sha256_hex(
            {
                "allowed_files": list(allowed),
                "changed_scope_fingerprint": pr_evidence.changed_scope_fingerprint,
                "forbidden_paths": list(forbidden),
                "head_sha": decision.head_sha,
            }
        ),
        scanner_result_fingerprint=_sha256_hex({"required_checks": checks}),
        implementation_contract_fingerprint=_sha256_hex(
            {
                "allowed_files": list(allowed),
                "base_branch": decision.base_branch,
                "base_sha_or_evidence_id": decision.base_sha_or_evidence_id,
                "expires_at": decision.expires_at,
                "forbidden_paths": list(forbidden),
                "head_sha": decision.head_sha,
                "merge_method": decision.merge_method,
                "pr_number": decision.pr_number,
                "repository": decision.repository,
                "required_tests": list(required_tests),
            }
        ),
        allowed_files=allowed,
        forbidden_paths=forbidden,
        required_tests=required_tests,
    )

    pending = ApprovalRecord(
        schema_version=APPROVAL_RECORD_SCHEMA_VERSION,
        approval_id="",
        approval_revision="",
        revision_number=1,
        previous_revision=None,
        approval_kind=ApprovalKind.SOURCE_MUTATION,
        state=ApprovalState.PENDING,
        binding=binding,
        authorizer_id=decision.authorizer_id,
        decision_id=decision.decision_id,
        decision_at=decision.decision_at,
        expires_at=decision.expires_at,
        supersedes_approval_id=None,
        reason_codes=(),
        details=(),
    )
    approved = record_approval_decision(
        pending,
        state=ApprovalState.APPROVED,
        decision_id=decision.decision_id,
        authorizer_id=decision.authorizer_id,
        decision_at=decision.decision_at,
        details=("merge-approval:approved",),
    )
    applicability = ApprovalApplicabilityResult(
        status="applicable",
        approval_id=approved.approval_id,
        approval_revision=approved.approval_revision,
        current_proposal_id=binding.proposal_id,
        reason_codes=(),
        changed_bindings=(),
        approval_applicable=True,
        details=("merge-approval:applicable",),
    )
    projection = ApprovedExecutionProjection(
        schema_version=APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION,
        projection_id="",
        proposal_version=binding.proposal_version,
        proposal_id=binding.proposal_id,
        approval_id=approved.approval_id,
        approval_revision=approved.approval_revision,
        approval_revision_number=approved.revision_number,
        approval_kind=ApprovalKind.SOURCE_MUTATION.value,
        approval_state="approved",
        approval_authorizer_id=approved.authorizer_id,
        approval_decision_id=approved.decision_id,
        approval_decision_at=approved.decision_at,
        approval_expires_at=approved.expires_at,
        approval_supersedes_id=None,
        handoff_digest=binding.handoff_digest,
        graph_digest=binding.graph_digest,
        planning_result_digest=binding.planning_result_digest,
        repository=binding.repository,
        base_branch=binding.base_branch,
        evaluated_repository_sha=binding.evaluated_repository_sha,
        evaluator_commit_sha=binding.evaluator_commit_sha,
        tested_repository_sha=binding.tested_repository_sha,
        repository_evidence_type=binding.repository_evidence_type,
        supplied_node_ids=binding.supplied_node_ids,
        cohort_summaries=binding.cohort_summaries,
        issueplan_current_state_evidence_id=binding.issueplan_current_state_evidence_id,
        repository_state_evidence_id=binding.repository_state_evidence_id,
        source_snapshot_fingerprint=binding.source_snapshot_fingerprint,
        scanner_result_fingerprint=binding.scanner_result_fingerprint,
        implementation_contract_fingerprint=binding.implementation_contract_fingerprint,
        allowed_files=binding.allowed_files,
        forbidden_paths=binding.forbidden_paths,
        required_tests=binding.required_tests,
        # N-6: projected_at is set to evaluated_at, and the
        # evaluated_at >= decision_at check above enforces the
        # projected_at >= decision_at ordering (the dataclass
        # checks timestamp format only).
        projected_at=evaluated_at,
    )

    # Self-verification (design section 2, step 6 + QA N-1): the
    # exact checks the reader and build_merge_proposal will run,
    # including a serialize -> reconstruct round-trip for every
    # record (applicability format is enforced only at
    # reconstruction). Any failure raises; no unverified triple
    # is ever returned.
    if approved.state is not ApprovalState.APPROVED:
        raise ValueError("merge approval triple is not approved")
    if (
        applicability.status != "applicable"
        or not applicability.approval_applicable
        or applicability.approval_id != approved.approval_id
        or applicability.approval_revision != approved.approval_revision
    ):
        raise ValueError("merge approval applicability does not match approval")
    if (
        projection.approval_state != "approved"
        or projection.approval_id != approved.approval_id
        or projection.approval_revision != approved.approval_revision
        or projection.repository != pr_evidence.repository
        or projection.base_branch != pr_evidence.base_branch
        or projection.tested_repository_sha != pr_evidence.head_sha
        or projection.allowed_files != pr_evidence.allowed_files
        or projection.forbidden_paths != pr_evidence.forbidden_paths
        or projection.required_tests != pr_evidence.required_tests
    ):
        raise ValueError("merge approval projection does not match approval or PR evidence")
    if reconstruct_approval_record(serialize_approval_record(approved)) != approved:
        raise ValueError("merge approval record failed serialize/reconstruct round-trip")
    if (
        reconstruct_approval_applicability_result(
            serialize_approval_applicability_result(applicability)
        )
        != applicability
    ):
        raise ValueError("merge approval applicability failed serialize/reconstruct round-trip")
    if (
        reconstruct_approved_execution_projection(
            serialize_approved_execution_projection(projection)
        )
        != projection
    ):
        raise ValueError("merge approval projection failed serialize/reconstruct round-trip")
    # Dispatch-time construction must succeed against the same PR
    # evidence; this is a canonical-function check, not a parallel
    # evaluator.
    build_merge_proposal(approved, applicability, projection, pr_evidence)
    return approved, applicability, projection
