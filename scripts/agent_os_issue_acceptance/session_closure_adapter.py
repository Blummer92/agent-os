"""Session-executed production caller for governed issue closure (#3489).

This module is the missing production caller between canonical admission and
the connected GitHub tools. It adds NO evaluation logic: admission is
``evaluate_issue_closure`` and the pre-write gate is
``verify_closure_admission_receipt`` from ``closure_admission_actions``; the
mutation order and payloads are the dispatcher's fixed contracts
(``HOST_DISPATCH_CONTRACT`` / ``POST_CLOSE_RECONCILIATION_CONTRACT``).
What this module adds is the transfer discipline the session must follow:

* QA evidence is accepted only with runtime-handoff provenance. A
  caller-supplied string, a mutable report file, an artifact, a check run,
  a status, or a review is never QA evidence here, no matter what verdict
  it claims. The adapter enforces the provenance gate and the binding
  gates; it cannot cryptographically prove a handoff descriptor, and it
  says so -- the remaining trust anchors are runtime delivery of the QA
  result to the session and the human runtime-approval tap on each native
  write, exactly as for governed merges.
* QA records must be BOUND (issue, head when applicable, body digest).
  The canonical evaluator tolerates unbound records; this production
  caller does not. Unbound QA is refused.
* The plan is immutable once built. Any drift between plan time and
  pre-write time (body digest, revision, trigger hash, state) refuses
  with zero mutations. The pre-write receipt verification runs against a
  FRESH snapshot, never the plan-time snapshot.
* The executor performs the dispatcher's exact operation sequence
  against an injected transport and enforces no-blind-retry: an uncertain
  write is never retried in-run; a fresh readback decides, and an
  unavailable readback stops the run as unresolved.
* The production (MCP) mapping is emitted as data by ``mcp_manifest``.
  The connected catalog has NO label-delete tool, so the dedicated
  ``remove_label`` transport operation maps to a labels re-read +
  ``issue_write`` labels replacement + labels readback, with an
  abort-if-changed race check. Replacement semantics are a live canary
  gate (G2); until that gate passes, a label step that cannot be
  verified reports reconciliation-required, never success.

No workflow change, no token, no scheduler, no queue, no database, no new
evaluator, no new dispatcher, and no QA identity are introduced here.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from typing import Literal, Protocol

from .closure_admission_actions import (
    HOST_DISPATCH_CONTRACT,
    POST_CLOSE_RECONCILIATION_CONTRACT,
    PROTECTED_ISSUE_NUMBERS,
    ClosureAcceptanceEvidence,
    IssueClosureRequest,
    evaluate_issue_closure,
    verify_closure_admission_receipt,
)
from .lifecycle_mutation_authorization import (
    LifecycleMutationAuthorization,
    LifecycleOwnerDecision,
    produce_lifecycle_mutation_authorization,
)
from .lifecycle_mutation_guard import LifecycleStateSnapshot

REPO = "Blummer92/agent-os"
READY_LABEL = "status:ready"

# Identities that are never independent QA, even with a passing verdict.
# This denylist is defense-in-depth only: it cannot stop a novel fabricated
# string, which is why the runtime-handoff provenance gate below is the
# primary gate and why QA consumption also requires the session to have
# received the verdict through a runtime-delivered QA handoff.
FORBIDDEN_EVALUATOR_IDS = frozenset(
    {
        "agent-os/authoritative-aggregate",
        "github-actions[bot]",
        "chatgpt-codex-connector[bot]",
    }
)

# The only provenance this production caller accepts for QA evidence.
QA_PROVENANCE_RUNTIME_HANDOFF = "runtime_handoff"


class TransportUncertain(Exception):
    """A write may or may not have landed. Never retry; readback decides."""


class TransportUnavailable(Exception):
    """A required readback could not be obtained. Stop as unresolved."""


@dataclass(frozen=True, slots=True)
class QaEvidence:
    """One QA verdict as the production caller consumes it.

    ``provenance`` must be ``runtime_handoff``: the verdict arrived through
    a runtime-delivered QA/Test Agent handoff to this session lineage.
    ``qa_session_ref`` / ``delivery_ref`` name that handoff; they are
    session bookkeeping, not GitHub authentication, and the adapter treats
    them as required bookkeeping, never as a signature.
    """

    verdict: Literal["pass", "fail", "missing"]
    evidence_id: str
    evaluator_id: str
    issue_number: int
    validated_head_sha: str | None
    issue_body_digest: str
    provenance: str
    qa_session_ref: str
    delivery_ref: str

    def to_acceptance(self) -> ClosureAcceptanceEvidence:
        return ClosureAcceptanceEvidence(
            verdict=self.verdict,
            evidence_id=self.evidence_id,
            evaluator_id=self.evaluator_id,
            issue_number=self.issue_number,
            validated_head_sha=self.validated_head_sha,
        )


def verify_qa_evidence(
    qa: QaEvidence,
    *,
    authorizer_id: str,
    expected_issue_number: int,
    expected_body_digest: str,
    expected_head_sha: str | None,
    other_records: tuple[QaEvidence, ...] = (),
) -> tuple[bool, tuple[str, ...]]:
    """Verify one QA record before it may enter canonical admission."""
    if qa.provenance != QA_PROVENANCE_RUNTIME_HANDOFF:
        return False, ("session-closure.qa-provenance-untrusted",)
    if not qa.qa_session_ref or not qa.delivery_ref:
        return False, ("session-closure.qa-handoff-unreferenced",)
    if qa.verdict != "pass":
        return False, ("session-closure.qa-not-passed",)
    if not qa.evaluator_id or qa.evaluator_id == authorizer_id:
        return False, ("session-closure.qa-not-independent",)
    if qa.evaluator_id in FORBIDDEN_EVALUATOR_IDS:
        return False, ("session-closure.qa-evaluator-not-qa",)
    if qa.issue_number != expected_issue_number:
        return False, ("session-closure.qa-issue-mismatch",)
    if expected_head_sha is None:
        if qa.validated_head_sha is not None:
            return False, ("session-closure.qa-head-unexpected",)
    elif qa.validated_head_sha != expected_head_sha:
        return False, ("session-closure.qa-head-mismatch",)
    if qa.issue_body_digest != expected_body_digest:
        return False, ("session-closure.qa-body-stale",)
    for other in other_records:
        if other.issue_number != expected_issue_number:
            continue
        if expected_head_sha is not None and other.validated_head_sha not in (None, expected_head_sha):
            continue
        if other.verdict != "pass":
            return False, ("session-closure.qa-conflict",)
    return True, ()


def render_evidence_comment(
    *,
    repository: str,
    issue_number: int,
    evidence_id: str,
    evaluator_id: str,
    receipt_id: str | None,
) -> str:
    """Deterministic evidence comment body (dispatcher format, by contract).

    Verified facts only; no closing keyword, no other issue reference.
    Must stay byte-identical to the dispatcher's completion comment for
    the same inputs; the test suite asserts that equivalence.
    """
    return (
        "Governed closure verified.\n"
        f"Repository: {repository}\n"
        f"Issue: {issue_number}\n"
        "State: closed, reason completed.\n"
        f"Acceptance evidence: {evidence_id} (evaluator {evaluator_id}).\n"
        f"Admission receipt: {receipt_id or 'unavailable'}.\n"
        "Verified by canonical post-write readback."
    )


def _trigger_hash(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SessionClosurePlan:
    """An admitted, immutable closure plan. No mutation may be planned
    from a refused plan; ``build_plan`` returns None in that case."""

    repository: str
    issue_number: int
    receipt: dict
    authorization: LifecycleMutationAuthorization
    acceptance: ClosureAcceptanceEvidence
    satisfaction: object | None
    body_digest: str
    revision: str
    label_required: bool
    comment_body: str
    delivery_id: str
    trigger_id: str
    trigger_body_hash: str

    @property
    def receipt_id(self) -> str | None:
        value = self.receipt.get("receipt_id")
        return value if isinstance(value, str) else None


def build_plan(
    *,
    decision: LifecycleOwnerDecision,
    qa: QaEvidence,
    snapshot: LifecycleStateSnapshot,
    body_digest: str,
    satisfaction: object | None = None,
    delivery_id: str,
    trigger_id: str,
    trigger_body_hash: str,
    other_qa_records: tuple[QaEvidence, ...] = (),
) -> tuple[SessionClosurePlan | None, tuple[str, ...]]:
    """Verify QA, run canonical admission, and bind the result into a plan.

    Returns (None, reason_codes) on any refusal. A plan is emitted only
    when canonical admission passes AND the receipt verifies against the
    plan-time snapshot AND the plan's contracts are exactly the canonical
    contracts. The caller must still run ``verify_prewrite`` against a
    fresh snapshot before any mutation; this plan alone authorizes nothing.
    """
    if decision.repository != snapshot.repository or decision.issue_number != snapshot.issue_number:
        return None, ("session-closure.decision-identity-mismatch",)
    # QA round 1, defect 1: the manifest names this repository, so a plan
    # for any other repository must refuse here rather than produce a
    # manifest that would act on a different issue number in agent-os.
    if decision.repository != REPO:
        return None, ("session-closure.repository-not-pinned",)
    if snapshot.issue_number in PROTECTED_ISSUE_NUMBERS:
        return None, ("closure.protected-target",)
    qa_ok, qa_reasons = verify_qa_evidence(
        qa,
        authorizer_id=decision.authorizer_id,
        expected_issue_number=decision.issue_number,
        expected_body_digest=body_digest,
        expected_head_sha=snapshot.source_head,
        other_records=other_qa_records,
    )
    if not qa_ok:
        return None, qa_reasons
    acceptance = qa.to_acceptance()
    request = IssueClosureRequest(decision=decision, acceptance=acceptance, satisfaction=satisfaction)
    receipt = evaluate_issue_closure(request, snapshot, current_issue_body_digest=body_digest)
    if not receipt.get("admitted"):
        reasons = receipt.get("reason_codes")
        return None, tuple(reasons) if isinstance(reasons, (list, tuple)) else ("closure.not-admitted",)
    authorization = produce_lifecycle_mutation_authorization(decision, snapshot)
    # Canonical verify binds a supplied body digest ONLY to a trusted
    # satisfaction record (ADV-1): a digest without satisfaction fails
    # closed there. The adapter binds the digest to the issue itself
    # separately (plan digest vs fresh digest equality in verify_prewrite),
    # so it passes the digest to canonical verify only when satisfaction
    # is present; otherwise it passes None and relies on its own check.
    verify_digest = body_digest if satisfaction is not None else None
    if not verify_closure_admission_receipt(
        receipt,
        authorization=authorization,
        fresh_snapshot=snapshot,
        acceptance=acceptance,
        satisfaction=satisfaction,
        current_issue_body_digest=verify_digest,
    ):
        return None, ("session-closure.receipt-unverifiable",)
    if receipt.get("host_dispatch_contract") != HOST_DISPATCH_CONTRACT:
        return None, ("session-closure.contract-mismatch",)
    if receipt.get("post_close_reconciliation_contract") != POST_CLOSE_RECONCILIATION_CONTRACT:
        return None, ("session-closure.contract-mismatch",)
    if not trigger_id or not trigger_body_hash:
        return None, ("session-closure.trigger-missing",)
    plan = SessionClosurePlan(
        repository=decision.repository,
        issue_number=decision.issue_number,
        receipt=receipt,
        authorization=authorization,
        acceptance=acceptance,
        satisfaction=satisfaction,
        body_digest=body_digest,
        revision=snapshot.observed_revision,
        label_required=READY_LABEL in tuple(snapshot.lifecycle_labels),
        comment_body=render_evidence_comment(
            repository=decision.repository,
            issue_number=decision.issue_number,
            evidence_id=acceptance.evidence_id,
            evaluator_id=acceptance.evaluator_id,
            receipt_id=receipt.get("receipt_id") if isinstance(receipt.get("receipt_id"), str) else None,
        ),
        delivery_id=delivery_id,
        trigger_id=trigger_id,
        trigger_body_hash=trigger_body_hash,
    )
    return plan, ()


@dataclass(frozen=True, slots=True)
class FreshRead:
    """One fresh GitHub read, as the session obtained it via native tools."""

    snapshot: LifecycleStateSnapshot
    body_digest: str
    trigger_body: str | None
    labels: tuple[str, ...]
    comment_bodies: tuple[str, ...]
    state_reason: str | None


def verify_prewrite(
    plan: SessionClosurePlan, fresh: FreshRead
) -> tuple[str, tuple[str, ...]]:
    """Verify a plan against a fresh read. Returns a status and reasons.

    Statuses: "ready" (mutation may proceed), "already-closed" (duplicate
    delivery path; see the executor), "refused" (zero mutations).
    """
    snap = fresh.snapshot
    if snap.repository != plan.repository or snap.issue_number != plan.issue_number:
        return "refused", ("closure.issue-identity-mismatch",)
    if snap.issue_state == "closed":
        return "already-closed", ()
    if snap.issue_state != "open":
        return "refused", ("session-closure.unexpected-issue-state",)
    if fresh.body_digest != plan.body_digest:
        return "refused", ("session-closure.body-digest-drift",)
    if snap.observed_revision != plan.revision:
        return "refused", ("session-closure.revision-drift",)
    if fresh.trigger_body is None or _trigger_hash(fresh.trigger_body) != plan.trigger_body_hash:
        return "refused", ("session-closure.trigger-mismatch",)
    verify_digest = fresh.body_digest if plan.satisfaction is not None else None
    if not verify_closure_admission_receipt(
        plan.receipt,
        authorization=plan.authorization,
        fresh_snapshot=snap,
        acceptance=plan.acceptance,
        satisfaction=plan.satisfaction,
        current_issue_body_digest=verify_digest,
    ):
        return "refused", ("session-closure.receipt-unverifiable-fresh",)
    return "ready", ()


def mcp_manifest(plan: SessionClosurePlan) -> list[dict]:
    """Ordered native-tool steps for one plan, as data for the session.

    The session executes these steps verbatim via connected GitHub tools,
    each write under its own runtime approval, checking each checkpoint
    before proceeding. This manifest is the production transfer mechanism:
    admission results leave this module only as exact tool parameters.
    The label step has no DELETE tool in the connected catalog; it is
    expanded to re-read + labels-replacement + readback with an
    abort-if-changed checkpoint (canary gate G2).
    """
    owner, _, repo = plan.repository.partition("/")
    steps: list[dict] = [
        {
            "step": 1,
            "action": "fresh-issue-read",
            "tool": "issue_read",
            "method": "get",
            "params": {"owner": owner, "repo": repo, "issue_number": plan.issue_number},
            "checkpoint": "verify_prewrite must return ready; already-closed goes to the duplicate path; refused stops with zero writes",
        },
        {
            "step": 2,
            "action": "trigger-reread",
            "tool": "issue_read",
            "method": "get_comments",
            "params": {"owner": owner, "repo": repo, "issue_number": plan.issue_number},
            "checkpoint": f"find comment id for trigger {plan.trigger_id}; sha256(body) must equal plan trigger hash; mismatch refuses",
        },
        {
            "step": 3,
            "action": "close-issue",
            "tool": "issue_write",
            "method": "update",
            "params": {
                "owner": owner,
                "repo": repo,
                "issue_number": plan.issue_number,
                "state": "closed",
                "state_reason": "completed",
            },
            "checkpoint": "call carries ONLY state + state_reason; any extra field is a manifest violation",
        },
        {
            "step": 4,
            "action": "post-close-readback",
            "tool": "issue_read",
            "method": "get",
            "params": {"owner": owner, "repo": repo, "issue_number": plan.issue_number},
            "checkpoint": "state must be closed and state_reason completed; otherwise outcome is unverified, never reported as closed",
        },
    ]
    if plan.label_required:
        steps.extend(
            [
                {
                    "step": 5,
                    "action": "labels-reread-before-replacement",
                    "tool": "issue_read",
                    "method": "get_labels",
                    "params": {"owner": owner, "repo": repo, "issue_number": plan.issue_number},
                    "checkpoint": "labels must be unchanged since step 4; any change aborts the label step (never clobber a concurrent label change)",
                },
                {
                    "step": 6,
                    "action": "label-replacement",
                    "tool": "issue_write",
                    "method": "update",
                    "params": {
                        "owner": owner,
                        "repo": repo,
                        "issue_number": plan.issue_number,
                        "labels": "current labels minus status:ready (computed from step 5, never from plan time)",
                    },
                    "checkpoint": "no label-delete tool exists in the connected catalog; replacement is the mapped operation (canary gate G2)",
                },
                {
                    "step": 7,
                    "action": "labels-readback",
                    "tool": "issue_read",
                    "method": "get_labels",
                    "params": {"owner": owner, "repo": repo, "issue_number": plan.issue_number},
                    "checkpoint": "status:ready absent and every other step-5 label present; otherwise outcome is closed-verified-label-reconciliation-required",
                },
            ]
        )
    steps.extend(
        [
            {
                "step": 8,
                "action": "comment-presence-check",
                "tool": "issue_read",
                "method": "get_comments",
                "params": {"owner": owner, "repo": repo, "issue_number": plan.issue_number},
                "checkpoint": f"if any body already contains receipt id {plan.receipt_id}, skip step 9 (duplicate delivery); never post twice",
            },
            {
                "step": 9,
                "action": "post-evidence-comment",
                "tool": "add_issue_comment",
                "method": "add",
                "params": {
                    "owner": owner,
                    "repo": repo,
                    "issue_number": plan.issue_number,
                    "body": plan.comment_body,
                },
                "checkpoint": "body is the plan comment body verbatim; it carries no closing keyword and no other issue reference",
            },
            {
                "step": 10,
                "action": "final-readback",
                "tool": "issue_read",
                "method": "get",
                "params": {"owner": owner, "repo": repo, "issue_number": plan.issue_number},
                "checkpoint": "closed + completed + label disposition + comment present by receipt id; only this passing permits reporting verified closure",
            },
        ]
    )
    return steps


class SessionClosureTransport(Protocol):
    """Transport the offline executor drives. Production uses the manifest
    above (native MCP tools) instead of this protocol; the executor and
    the manifest implement the same operation order."""

    def fresh_read(self) -> FreshRead: ...
    def close(self) -> None: ...
    def remove_label(self, label: str) -> None: ...
    def list_comments(self) -> tuple[str, ...]: ...
    def post_comment(self, body: str) -> None: ...


def execute_plan(plan: SessionClosurePlan, transport: SessionClosureTransport) -> dict:
    """Execute one plan against a transport, enforcing the full contract.

    Returns an outcome dict with status and reason codes. Refusals and
    unresolved runs record zero writes for the refused/unresolved portion;
    the transport itself records the operation log the tests assert on.
    Uncertain writes are never retried: a fresh readback decides, and an
    unavailable readback stops the run as unresolved.
    """
    try:
        fresh = transport.fresh_read()
    except TransportUnavailable:
        return {"status": "unresolved", "reason_codes": ("session-closure.readback-unavailable",), "issue_number": plan.issue_number}
    status, reasons = verify_prewrite(plan, fresh)
    if status == "refused":
        return {"status": "refused", "reason_codes": reasons, "issue_number": plan.issue_number}
    if status == "already-closed":
        # Duplicate delivery: complete this plan's own label + comment
        # steps (in dispatcher order) or flag what cannot be completed.
        # A prior run that closed without label removal must never leave
        # the label in place silently (QA round 1, defect 3).
        latest = fresh
        label_flagged = False
        if plan.label_required and READY_LABEL in latest.labels:
            try:
                transport.remove_label(READY_LABEL)
            except TransportUncertain:
                try:
                    latest = transport.fresh_read()
                except TransportUnavailable:
                    return {"status": "closed-unverified", "reason_codes": ("session-closure.readback-unavailable",), "issue_number": plan.issue_number}
                label_flagged = READY_LABEL in latest.labels
            else:
                try:
                    latest = transport.fresh_read()
                except TransportUnavailable:
                    return {"status": "closed-unverified", "reason_codes": ("session-closure.readback-unavailable",), "issue_number": plan.issue_number}
                label_flagged = READY_LABEL in latest.labels
        comment_present = plan.receipt_id is not None and any(
            plan.receipt_id in body for body in latest.comment_bodies
        )
        comment_posted = False
        if not comment_present:
            # Prior run closed the issue but left no evidence comment.
            # Complete only the comment step, after fresh verification
            # above; this is a new-plan completion, not an in-run retry
            # of an uncertain write.
            try:
                transport.post_comment(plan.comment_body)
            except TransportUncertain:
                try:
                    bodies = transport.list_comments()
                except TransportUnavailable:
                    return {"status": "unresolved", "reason_codes": ("session-closure.readback-unavailable",), "issue_number": plan.issue_number}
                if plan.receipt_id and any(plan.receipt_id in body for body in bodies):
                    comment_present = True
                else:
                    return {"status": "unresolved", "reason_codes": ("session-closure.comment-uncertain",), "issue_number": plan.issue_number}
            else:
                comment_posted = True
        if comment_posted:
            try:
                latest = transport.fresh_read()
            except TransportUnavailable:
                return {"status": "closed-unverified", "reason_codes": ("session-closure.readback-unavailable",), "issue_number": plan.issue_number}
            comment_present = plan.receipt_id is not None and any(
                plan.receipt_id in body for body in latest.comment_bodies
            )
            # Final disposition wins over the intermediate flag: the label
            # is flagged only if it is still present at the final read.
            label_flagged = bool(plan.label_required and READY_LABEL in latest.labels)
        if (
            latest.snapshot.issue_state != "closed"
            or latest.state_reason != "completed"
            or not comment_present
        ):
            return {"status": "closed-unverified", "reason_codes": ("session-closure.final-readback-mismatch",), "issue_number": plan.issue_number}
        if label_flagged:
            base = "already-closed-comment-completed" if comment_posted else "already-closed-verified"
            return {"status": f"{base}-label-reconciliation-required", "reason_codes": (), "issue_number": plan.issue_number}
        return {
            "status": "already-closed-comment-completed" if comment_posted else "already-closed-verified",
            "reason_codes": (),
            "issue_number": plan.issue_number,
        }
    # status == ready: exact close step, payload fixed by contract.
    try:
        transport.close()
    except TransportUncertain:
        try:
            after = transport.fresh_read()
        except TransportUnavailable:
            return {"status": "unresolved", "reason_codes": ("session-closure.close-uncertain-readback-unavailable",), "issue_number": plan.issue_number}
        if after.snapshot.issue_state != "closed" or after.state_reason != "completed":
            return {"status": "unresolved", "reason_codes": ("session-closure.close-uncertain",), "issue_number": plan.issue_number}
        return _reconcile(plan, transport, after)
    try:
        after_close = transport.fresh_read()
    except TransportUnavailable:
        return {"status": "closed-unverified", "reason_codes": ("session-closure.readback-unavailable",), "issue_number": plan.issue_number}
    if after_close.snapshot.issue_state != "closed" or after_close.state_reason != "completed":
        return {"status": "closed-unverified", "reason_codes": ("session-closure.post-close-readback-mismatch",), "issue_number": plan.issue_number}
    return _reconcile(plan, transport, after_close)


def _reconcile(plan: SessionClosurePlan, transport: SessionClosureTransport, after_close: FreshRead) -> dict:
    """Label + comment + final readback for a freshly verified closure."""
    label_flagged = False
    if plan.label_required and READY_LABEL in after_close.labels:
        try:
            transport.remove_label(READY_LABEL)
        except TransportUncertain:
            try:
                labels_now = transport.fresh_read().labels
            except TransportUnavailable:
                return {"status": "closed-unverified", "reason_codes": ("session-closure.readback-unavailable",), "issue_number": plan.issue_number}
            if READY_LABEL in labels_now:
                label_flagged = True
            # If the label is gone, removal landed despite the uncertainty.
        else:
            # Dedicated-op transports verify via the final readback below.
            pass
    # Comment step: never duplicate by receipt id.
    try:
        bodies = transport.list_comments()
    except TransportUnavailable:
        return {"status": "closed-unverified", "reason_codes": ("session-closure.readback-unavailable",), "issue_number": plan.issue_number}
    comment_present = plan.receipt_id is not None and any(plan.receipt_id in body for body in bodies)
    if not comment_present:
        try:
            transport.post_comment(plan.comment_body)
        except TransportUncertain:
            try:
                bodies_after = transport.list_comments()
            except TransportUnavailable:
                return {"status": "closed-unverified", "reason_codes": ("session-closure.readback-unavailable",), "issue_number": plan.issue_number}
            if plan.receipt_id and any(plan.receipt_id in body for body in bodies_after):
                comment_present = True
            else:
                return {"status": "unresolved", "reason_codes": ("session-closure.comment-uncertain",), "issue_number": plan.issue_number}
    try:
        final = transport.fresh_read()
    except TransportUnavailable:
        return {"status": "closed-unverified", "reason_codes": ("session-closure.readback-unavailable",), "issue_number": plan.issue_number}
    if final.snapshot.issue_state != "closed" or final.state_reason != "completed":
        return {"status": "closed-unverified", "reason_codes": ("session-closure.final-readback-mismatch",), "issue_number": plan.issue_number}
    if plan.receipt_id and not any(plan.receipt_id in body for body in final.comment_bodies):
        return {"status": "closed-unverified", "reason_codes": ("session-closure.final-comment-missing",), "issue_number": plan.issue_number}
    if plan.label_required and READY_LABEL in final.labels:
        label_flagged = True
    if label_flagged:
        return {"status": "closed-verified-label-reconciliation-required", "reason_codes": (), "issue_number": plan.issue_number}
    return {"status": "closed-verified", "reason_codes": (), "issue_number": plan.issue_number}


def execute_batch(items: list[tuple[SessionClosurePlan, SessionClosureTransport]]) -> list[dict]:
    """Execute plans independently: a blocked item never stops the next."""
    outcomes: list[dict] = []
    for plan, transport in items:
        outcomes.append(execute_plan(plan, transport))
    return outcomes


def _plan_from_json(payload: dict) -> tuple[SessionClosurePlan | None, tuple[str, ...]]:
    decision_data = payload["decision"]
    qa_data = payload["qa"]
    snapshot_data = payload["snapshot"]
    decision = LifecycleOwnerDecision(
        repository=decision_data["repository"],
        issue_number=decision_data["issue_number"],
        pull_request_number=decision_data.get("pull_request_number"),
        requested_mutations=tuple(decision_data["requested_mutations"]),
        authorizer_id=decision_data["authorizer_id"],
        decision_id=decision_data["decision_id"],
        decision_recorded=bool(decision_data["decision_recorded"]),
    )
    qa = QaEvidence(
        verdict=qa_data["verdict"],
        evidence_id=qa_data["evidence_id"],
        evaluator_id=qa_data["evaluator_id"],
        issue_number=qa_data["issue_number"],
        validated_head_sha=qa_data.get("validated_head_sha"),
        issue_body_digest=qa_data["issue_body_digest"],
        provenance=qa_data["provenance"],
        qa_session_ref=qa_data["qa_session_ref"],
        delivery_ref=qa_data["delivery_ref"],
    )
    snapshot = LifecycleStateSnapshot(
        repository=snapshot_data["repository"],
        issue_number=snapshot_data["issue_number"],
        pull_request_number=snapshot_data.get("pull_request_number"),
        source_head=snapshot_data.get("source_head"),
        base_head=snapshot_data.get("base_head"),
        pr_state=snapshot_data.get("pr_state", "none"),
        merged=bool(snapshot_data.get("merged", False)),
        issue_state=snapshot_data["issue_state"],
        review_state=snapshot_data.get("review_state", "unknown"),
        unresolved_threads=int(snapshot_data.get("unresolved_threads", 0)),
        lifecycle_labels=tuple(snapshot_data.get("lifecycle_labels", ())),
        observed_revision=snapshot_data["observed_revision"],
    )
    others = tuple(
        QaEvidence(
            verdict=item["verdict"],
            evidence_id=item["evidence_id"],
            evaluator_id=item["evaluator_id"],
            issue_number=item["issue_number"],
            validated_head_sha=item.get("validated_head_sha"),
            issue_body_digest=item["issue_body_digest"],
            provenance=item["provenance"],
            qa_session_ref=item["qa_session_ref"],
            delivery_ref=item["delivery_ref"],
        )
        for item in payload.get("other_qa_records", [])
    )
    return build_plan(
        decision=decision,
        qa=qa,
        snapshot=snapshot,
        body_digest=payload["body_digest"],
        satisfaction=payload.get("satisfaction"),
        delivery_id=payload["delivery_id"],
        trigger_id=payload["trigger_id"],
        trigger_body_hash=payload["trigger_body_hash"],
        other_qa_records=others,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the session host.

    ``plan`` reads one JSON plan request on stdin and prints the admitted
    plan's MCP manifest, or a refusal with reason codes (exit 2) and no
    manifest. It never performs a GitHub mutation itself; the session
    executes the printed manifest via native tools under approval.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["plan"]:
        print("usage: session_closure_adapter plan < request.json", file=sys.stderr)
        return 1
    try:
        payload = json.load(sys.stdin)
        plan, reasons = _plan_from_json(payload)
    except (KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"admitted": False, "reason_codes": [f"session-closure.input-invalid:{type(exc).__name__}"]}))
        return 2
    if plan is None:
        print(json.dumps({"admitted": False, "reason_codes": list(reasons)}))
        return 2
    print(json.dumps({"admitted": True, "receipt_id": plan.receipt_id, "manifest": mcp_manifest(plan)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
