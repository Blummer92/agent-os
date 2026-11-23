"""Session-executed production caller for governed issue closure (#3489).

This module is the production caller between canonical admission and the
connected GitHub tools. It adds NO evaluation logic: admission is
``evaluate_issue_closure`` and the pre-write gate is
``verify_closure_admission_receipt`` from ``closure_admission_actions``; the
mutation order and payloads are the dispatcher's fixed contracts
(``HOST_DISPATCH_CONTRACT`` / ``POST_CLOSE_RECONCILIATION_CONTRACT``).

F1 — caller-controlled authority is removed, not gated by strings.
There is NO JSON/CLI path into this module: no caller-supplied field
(``decision_recorded``, ``authorizer_id``, ``evaluator_id``, ``verdict``,
``provenance``, ``qa_session_ref``, ``delivery_ref``) can produce admission,
because no code path reads such fields. Admission requires two host-held
registrations that only the host session can mint:

* An ``OwnerGrant``, minted by ``HostRegistry.grant_owner_closure`` when
  the host holds the owner's authorization for one finite closure. The
  grant carries an unguessable token; a fabricated token resolves to
  nothing and refuses.
* A ``QaRecord`` registered by ``HostRegistry.register_qa_delivery``
  when the host receives a genuine independent QA execution through a
  runtime-delivered handoff. The record used for admission is the
  REGISTERED record, never caller-supplied fields, and its bindings
  (issue, head, body digest) are re-verified against fresh state.

The remaining trust anchors are stated plainly: the host session's own
records (registrations it minted after genuine owner authorization and
genuine QA delivery) and the human runtime-approval tap on each native
write, exactly as for governed merges. What this repair removes is the
remote/caller-controlled path: JSON or field claims can no longer reach
admission at all. It does not (and in a Python library cannot) prevent
misuse by the host process itself — that process IS the trusted boundary.

F2 — the production path is the executor, not a manifest.
``execute_session_closure`` is the single named production entry point:
it resolves the grants, builds the plan through canonical admission,
verifies pre-write against a FRESH read, and then executes through the
transport protocol. The transport is implemented by the host with the
connected GitHub tools (see the host contract in the README); each write
is individually runtime-approved. ``mcp_manifest`` is a derived audit
record whose steps carry machine assertions mirroring the executor's
gates — it is never executed by interpretation, and its prose
checkpoints are gone. An admitted result controls mutation eligibility:
without a valid plan, the executor performs zero mutations.

F3 — closure and reconciliation boundaries.
An already-closed issue receives ZERO mutations by default: the outcome
is ``already-closed-no-action`` and the result only reports whether
``status:ready`` is still present. Label or comment mutations on an
already-closed issue require a separate, explicit recovery grant bound
to that issue and receipt, and even then the run never re-closes.
Label removal is surgical (``remove_issue_label``) when the host's
transport supports it; when it does not — the connected Muse catalog
has no label-delete tool — the label step STOPS with a flagged outcome
and no mutation. Full-labels replacement is NOT in the production path
at all: it is neither silently substituted nor claimed proven. A failed
reconciliation never reverses a verified closure (no reopen operation
exists in the transport), at most one deterministic evidence comment is
ever posted (presence-checked by receipt id), and uncertain writes are
never blind-retried: a fresh readback decides, and an unavailable
readback stops the run as unresolved.

No workflow change, no token, no scheduler, no queue, no database, no
new evaluator, no new dispatcher, and no QA identity are introduced.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
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
# Defense-in-depth only: the primary gate is registry membership (a
# record the host registered after a genuine QA delivery), not this list.
FORBIDDEN_EVALUATOR_IDS = frozenset(
    {
        "agent-os/authoritative-aggregate",
        "github-actions[bot]",
        "chatgpt-codex-connector[bot]",
    }
)


class TransportUncertain(Exception):
    """A write may or may not have landed. Never retry; readback decides."""


class TransportUnavailable(Exception):
    """A required readback could not be obtained. Stop as unresolved."""


class LabelRemovalUnsupported(Exception):
    """The host's transport has no surgical label removal. Stop, never substitute."""


@dataclass(frozen=True, slots=True)
class QaRecord:
    """One QA verdict as the host registered it from a genuine delivery.

    There is NO provenance field: provenance is registry membership, not
    a string. ``delivery_ref`` names the runtime delivery (for example a
    QA subagent completion reference) as session bookkeeping; it is
    never, by itself, evidence — only the host's registration of this
    record under a minted token admits it.
    """

    verdict: Literal["pass", "fail", "missing"]
    evidence_id: str
    evaluator_id: str
    issue_number: int
    validated_head_sha: str | None
    issue_body_digest: str
    delivery_ref: str

    def to_acceptance(self) -> ClosureAcceptanceEvidence:
        return ClosureAcceptanceEvidence(
            verdict=self.verdict,
            evidence_id=self.evidence_id,
            evaluator_id=self.evaluator_id,
            issue_number=self.issue_number,
            validated_head_sha=self.validated_head_sha,
        )


@dataclass(frozen=True, slots=True)
class OwnerGrant:
    """Owner authorization for one finite closure, minted by the host.

    The token is minted at grant time and is unguessable; possession of
    a grant object alone proves nothing — admission resolves the token
    against the host registry that minted it.
    """

    token: str
    repository: str
    issue_number: int
    authorizer_id: str


@dataclass(frozen=True, slots=True)
class RecoveryGrant:
    """Separate explicit recovery authorization for one closed issue.

    Bound to an issue and an admission receipt. Recovery grants are
    reusable only for that same (issue, receipt) recovery, which is
    safe because every recovery operation is presence-checked and
    idempotent (label removed at most once, comment posted at most once).
    """

    token: str
    issue_number: int
    receipt_id: str


class HostRegistry:
    """Host-held registrations. Only the host session mints tokens.

    A fresh registry is created per host session. Nothing in this module
    accepts authority from data: every grant, delivery, and recovery
    token presented to the entry point must resolve to a record THIS
    registry minted. Forged tokens, forged fields, and unregistered
    records all refuse with zero mutations.
    """

    def __init__(self) -> None:
        self._owner_grants: dict[str, OwnerGrant] = {}
        self._qa_deliveries: dict[str, QaRecord] = {}
        self._recovery_grants: dict[str, RecoveryGrant] = {}

    def grant_owner_closure(self, *, repository: str, issue_number: int, authorizer_id: str) -> OwnerGrant:
        """Mint an owner grant. Call only when the host holds the owner's authorization."""
        grant = OwnerGrant(
            token=uuid.uuid4().hex,
            repository=repository,
            issue_number=issue_number,
            authorizer_id=authorizer_id,
        )
        self._owner_grants[grant.token] = grant
        return grant

    def resolve_owner_grant(self, token: str | None) -> OwnerGrant | None:
        if not isinstance(token, str):
            return None
        return self._owner_grants.get(token)

    def register_qa_delivery(self, record: QaRecord) -> str:
        """Register a QA record received through a genuine runtime handoff. Returns its delivery token."""
        token = uuid.uuid4().hex
        self._qa_deliveries[token] = record
        return token

    def resolve_qa_delivery(self, token: str | None) -> QaRecord | None:
        if not isinstance(token, str):
            return None
        return self._qa_deliveries.get(token)

    def grant_recovery(self, *, issue_number: int, receipt_id: str) -> RecoveryGrant:
        """Mint a recovery grant. Call only on a separate explicit recovery authorization."""
        grant = RecoveryGrant(token=uuid.uuid4().hex, issue_number=issue_number, receipt_id=receipt_id)
        self._recovery_grants[grant.token] = grant
        return grant

    def resolve_recovery(self, token: str | None) -> RecoveryGrant | None:
        if not isinstance(token, str):
            return None
        return self._recovery_grants.get(token)


def decision_from_grant(grant: OwnerGrant, *, pull_request_number: int | None) -> LifecycleOwnerDecision:
    """Build the canonical decision object from a host grant.

    ``decision_recorded`` is True because the host constructed this
    object from a grant it minted after owner authorization — it is
    never read from caller input. ``decision_id`` carries only a token
    prefix, never the full token.
    """
    return LifecycleOwnerDecision(
        repository=grant.repository,
        issue_number=grant.issue_number,
        requested_mutations=("close-issue",),
        authorizer_id=grant.authorizer_id,
        decision_id=f"owner-grant-{grant.token[:12]}",
        decision_recorded=True,
        pull_request_number=pull_request_number,
    )


def verify_qa_record(
    record: QaRecord,
    *,
    authorizer_id: str,
    expected_issue_number: int,
    expected_body_digest: str,
    expected_head_sha: str | None,
    other_records: tuple[QaRecord, ...] = (),
) -> tuple[bool, tuple[str, ...]]:
    """Verify one REGISTERED QA record before it may enter admission.

    Registry membership is checked by the caller (only registered
    records reach this function). These checks bind the record and
    refuse conflicts, staleness, and self-acceptance.
    """
    if not record.delivery_ref:
        return False, ("session-closure.qa-handoff-unreferenced",)
    if record.verdict != "pass":
        return False, ("session-closure.qa-not-passed",)
    if not record.evaluator_id or record.evaluator_id == authorizer_id:
        return False, ("session-closure.qa-not-independent",)
    if record.evaluator_id in FORBIDDEN_EVALUATOR_IDS:
        return False, ("session-closure.qa-evaluator-not-qa",)
    if record.issue_number != expected_issue_number:
        return False, ("session-closure.qa-issue-mismatch",)
    if expected_head_sha is None:
        if record.validated_head_sha is not None:
            return False, ("session-closure.qa-head-unexpected",)
    elif record.validated_head_sha != expected_head_sha:
        return False, ("session-closure.qa-head-mismatch",)
    if record.issue_body_digest != expected_body_digest:
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
    trigger_id: str
    trigger_body_hash: str

    @property
    def receipt_id(self) -> str | None:
        value = self.receipt.get("receipt_id")
        return value if isinstance(value, str) else None


def build_plan(
    *,
    registry: HostRegistry,
    owner_grant_token: str | None,
    qa_delivery_token: str | None,
    snapshot: LifecycleStateSnapshot,
    body_digest: str,
    trigger_id: str,
    trigger_body: str,
    satisfaction: object | None = None,
    other_qa_delivery_tokens: tuple[str, ...] = (),
) -> tuple[SessionClosurePlan | None, tuple[str, ...]]:
    """Verify host registrations, run canonical admission, bind a plan.

    Returns (None, reason_codes) on any refusal. A plan is emitted only
    when the owner grant and the QA delivery resolve in THIS registry,
    canonical admission passes, AND the receipt verifies against the
    plan-time snapshot with exactly the canonical contracts. The caller
    must still run ``verify_prewrite`` against a fresh snapshot before
    any mutation; this plan alone authorizes nothing. The trigger hash
    is computed here from the trigger body the host read — no
    caller-supplied hash is ever accepted.
    """
    grant = registry.resolve_owner_grant(owner_grant_token)
    if grant is None:
        return None, ("session-closure.owner-grant-unknown",)
    if grant.repository != snapshot.repository or grant.issue_number != snapshot.issue_number:
        return None, ("session-closure.decision-identity-mismatch",)
    # The manifest names this repository, so a plan for any other
    # repository must refuse here rather than produce a manifest that
    # would act on a different issue number in agent-os.
    if grant.repository != REPO:
        return None, ("session-closure.repository-not-pinned",)
    if snapshot.issue_number in PROTECTED_ISSUE_NUMBERS:
        return None, ("closure.protected-target",)
    record = registry.resolve_qa_delivery(qa_delivery_token)
    if record is None:
        return None, ("session-closure.qa-delivery-unknown",)
    other_records: list[QaRecord] = []
    for token in other_qa_delivery_tokens:
        other = registry.resolve_qa_delivery(token)
        if other is None:
            return None, ("session-closure.qa-delivery-unknown",)
        other_records.append(other)
    qa_ok, qa_reasons = verify_qa_record(
        record,
        authorizer_id=grant.authorizer_id,
        expected_issue_number=grant.issue_number,
        expected_body_digest=body_digest,
        expected_head_sha=snapshot.source_head,
        other_records=tuple(other_records),
    )
    if not qa_ok:
        return None, qa_reasons
    decision = decision_from_grant(grant, pull_request_number=snapshot.pull_request_number)
    acceptance = record.to_acceptance()
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
    if not trigger_id or not trigger_body:
        return None, ("session-closure.trigger-missing",)
    plan = SessionClosurePlan(
        repository=grant.repository,
        issue_number=grant.issue_number,
        receipt=receipt,
        authorization=authorization,
        acceptance=acceptance,
        satisfaction=satisfaction,
        body_digest=body_digest,
        revision=snapshot.observed_revision,
        label_required=READY_LABEL in tuple(snapshot.lifecycle_labels),
        comment_body=render_evidence_comment(
            repository=grant.repository,
            issue_number=grant.issue_number,
            evidence_id=acceptance.evidence_id,
            evaluator_id=acceptance.evaluator_id,
            receipt_id=receipt.get("receipt_id") if isinstance(receipt.get("receipt_id"), str) else None,
        ),
        trigger_id=trigger_id,
        trigger_body_hash=_trigger_hash(trigger_body),
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
    """Ordered native-tool steps for one plan, as a derived audit record.

    This manifest is NOT executed by interpretation: the executor below
    is the production path, and these steps mirror its gates. Each step
    carries machine assertions (the executor function or transport
    capability that enforces it) and a machine on_failure outcome — no
    prose checkpoints instructing an agent. The label step names the
    surgical tool only; when the host transport does not support it,
    the executor stops that step with a flagged outcome. There is no
    labels-replacement step anywhere in this manifest.
    """
    owner, _, repo = plan.repository.partition("/")
    steps: list[dict] = [
        {
            "step": 1,
            "action": "fresh-issue-read",
            "tool": "issue_read",
            "method": "get",
            "params": {"owner": owner, "repo": repo, "issue_number": plan.issue_number},
            "assertions": ["verify_prewrite returns ready, already-closed, or refused"],
            "on_failure": "refused stops with zero writes; already-closed goes to the no-action/recovery path",
        },
        {
            "step": 2,
            "action": "trigger-reread",
            "tool": "issue_read",
            "method": "get_comments",
            "params": {"owner": owner, "repo": repo, "issue_number": plan.issue_number},
            "assertions": ["sha256(trigger comment body) equals plan trigger_body_hash"],
            "on_failure": "refused with zero writes",
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
            "assertions": ["params contain ONLY state and state_reason", "verify_prewrite returned ready"],
            "on_failure": "uncertain write is never retried; fresh readback decides",
        },
        {
            "step": 4,
            "action": "post-close-readback",
            "tool": "issue_read",
            "method": "get",
            "params": {"owner": owner, "repo": repo, "issue_number": plan.issue_number},
            "assertions": ["state is closed and state_reason is completed"],
            "on_failure": "closed-unverified, never reported as closed",
        },
    ]
    if plan.label_required:
        steps.append(
            {
                "step": 5,
                "action": "label-removal-surgical",
                "tool": "remove_issue_label",
                "method": "remove",
                "params": {
                    "owner": owner,
                    "repo": repo,
                    "issue_number": plan.issue_number,
                    "name": READY_LABEL,
                },
                "assertions": ["transport supports_surgical_label_removal", "only the named label is removed"],
                "on_failure": "stop with no label mutation; outcome flagged label-reconciliation-required",
            }
        )
    steps.extend(
        [
            {
                "step": 6,
                "action": "comment-presence-check",
                "tool": "issue_read",
                "method": "get_comments",
                "params": {"owner": owner, "repo": repo, "issue_number": plan.issue_number},
                "assertions": ["if any body already contains the receipt id, the comment step is skipped"],
                "on_failure": "unavailable readback stops as closed-unverified",
            },
            {
                "step": 7,
                "action": "post-evidence-comment",
                "tool": "add_issue_comment",
                "method": "add",
                "params": {
                    "owner": owner,
                    "repo": repo,
                    "issue_number": plan.issue_number,
                    "body": plan.comment_body,
                },
                "assertions": ["body is the plan comment body verbatim", "at most one comment per receipt id"],
                "on_failure": "uncertain write is never retried; comment list readback decides",
            },
            {
                "step": 8,
                "action": "final-readback",
                "tool": "issue_read",
                "method": "get",
                "params": {"owner": owner, "repo": repo, "issue_number": plan.issue_number},
                "assertions": ["closed and completed and comment present by receipt id"],
                "on_failure": "closed-unverified, never reported as verified",
            },
        ]
    )
    return steps


class SessionClosureTransport(Protocol):
    """Production transport, implemented by the host with connected tools.

    Method names are the MCP operations: ``fresh_read`` composes
    ``issue_read`` get + get_comments + get_labels; ``close`` is
    ``issue_write`` update with ONLY state + state_reason; ``close``'s
    label counterpart is surgical ``remove_issue_label``; ``list_comments``
    is ``issue_read`` get_comments; ``post_comment`` is ``add_issue_comment``.
    A transport whose host catalog lacks surgical removal sets
    ``supports_surgical_label_removal`` False and raises
    ``LabelRemovalUnsupported`` from ``remove_issue_label``; the executor
    then stops the label step instead of substituting anything.
    """

    supports_surgical_label_removal: bool

    def fresh_read(self) -> FreshRead: ...
    def close(self) -> None: ...
    def remove_issue_label(self, label: str) -> None: ...
    def list_comments(self) -> tuple[str, ...]: ...
    def post_comment(self, body: str) -> None: ...


def _comment_present(plan: SessionClosurePlan, bodies: tuple[str, ...]) -> bool:
    return plan.receipt_id is not None and any(plan.receipt_id in body for body in bodies)


def _attempt_label_removal(
    plan: SessionClosurePlan, transport: SessionClosureTransport
) -> tuple[bool, tuple[str, ...]]:
    """Surgical label removal or a flagged stop. Never a substitution.

    Returns (flagged, reasons). ``flagged`` True means status:ready may
    still be present and the outcome must carry reconciliation-required.
    No labels-replacement call exists on any path.
    """
    if not plan.label_required:
        return False, ()
    try:
        labels_now = transport.fresh_read().labels
    except TransportUnavailable:
        return True, ("session-closure.readback-unavailable",)
    if READY_LABEL not in labels_now:
        return False, ()
    if not transport.supports_surgical_label_removal:
        # Host lacks the surgical tool: stop, do not substitute.
        return True, ()
    try:
        transport.remove_issue_label(READY_LABEL)
    except LabelRemovalUnsupported:
        return True, ()
    except TransportUncertain:
        try:
            labels_after = transport.fresh_read().labels
        except TransportUnavailable:
            return True, ("session-closure.readback-unavailable",)
        return (READY_LABEL in labels_after), ()
    return False, ()


def _post_comment_once(
    plan: SessionClosurePlan, transport: SessionClosureTransport
) -> tuple[bool, tuple[str, ...]]:
    """Post the deterministic comment iff absent. Returns (present, reasons).

    ``present`` True means the receipt comment is confirmed present.
    An uncertain post is never retried; the comment list readback decides.
    """
    try:
        bodies = transport.list_comments()
    except TransportUnavailable:
        return False, ("session-closure.readback-unavailable",)
    if _comment_present(plan, bodies):
        return True, ()
    try:
        transport.post_comment(plan.comment_body)
    except TransportUncertain:
        try:
            bodies_after = transport.list_comments()
        except TransportUnavailable:
            return False, ("session-closure.readback-unavailable",)
        if _comment_present(plan, bodies_after):
            return True, ()
        return False, ("session-closure.comment-uncertain",)
    return True, ()


def _final_verify_closed(plan: SessionClosurePlan, transport: SessionClosureTransport) -> tuple[str, tuple[str, ...]]:
    """Final readback for a closed issue. Returns (status, reasons) where
    status is 'verified', 'label-flagged', or 'unverified'."""
    try:
        final = transport.fresh_read()
    except TransportUnavailable:
        return "unverified", ("session-closure.readback-unavailable",)
    if final.snapshot.issue_state != "closed" or final.state_reason != "completed":
        return "unverified", ("session-closure.final-readback-mismatch",)
    if not _comment_present(plan, final.comment_bodies):
        return "unverified", ("session-closure.final-comment-missing",)
    if plan.label_required and READY_LABEL in final.labels:
        return "label-flagged", ()
    return "verified", ()


def _recover_closed(plan: SessionClosurePlan, transport: SessionClosureTransport, fresh: FreshRead) -> dict:
    """Recovery path for an already-closed issue. Never re-closes.

    Requires a separately validated recovery authorization (checked by
    the entry point; this function receives only the boolean). Label
    removal is surgical-or-stop; the comment is posted at most once;
    the final readback must verify closed + completed + comment present.
    """
    label_flagged, label_reasons = _attempt_label_removal(plan, transport)
    if label_reasons and "session-closure.readback-unavailable" in label_reasons:
        return {"status": "closed-unverified", "reason_codes": label_reasons, "issue_number": plan.issue_number}
    comment_present, comment_reasons = _post_comment_once(plan, transport)
    if not comment_present:
        if "session-closure.readback-unavailable" in comment_reasons:
            return {"status": "closed-unverified", "reason_codes": comment_reasons, "issue_number": plan.issue_number}
        return {"status": "unresolved", "reason_codes": comment_reasons, "issue_number": plan.issue_number}
    status, reasons = _final_verify_closed(plan, transport)
    if status == "unverified":
        return {"status": "closed-unverified", "reason_codes": reasons, "issue_number": plan.issue_number}
    if status == "label-flagged" or label_flagged:
        return {"status": "already-closed-recovered-label-reconciliation-required", "reason_codes": (), "issue_number": plan.issue_number}
    return {"status": "already-closed-recovered", "reason_codes": (), "issue_number": plan.issue_number}


def _reconcile(plan: SessionClosurePlan, transport: SessionClosureTransport, after_close: FreshRead) -> dict:
    """Label + comment + final readback for a freshly verified closure.

    The label step is surgical-or-stop: without surgical support the
    outcome is flagged, the closure stays verified, and no label
    mutation of any kind is attempted.
    """
    label_flagged, label_reasons = _attempt_label_removal(plan, transport)
    if label_reasons and "session-closure.readback-unavailable" in label_reasons:
        return {"status": "closed-unverified", "reason_codes": label_reasons, "issue_number": plan.issue_number}
    comment_present, comment_reasons = _post_comment_once(plan, transport)
    if not comment_present:
        if "session-closure.readback-unavailable" in comment_reasons:
            return {"status": "closed-unverified", "reason_codes": comment_reasons, "issue_number": plan.issue_number}
        return {"status": "unresolved", "reason_codes": comment_reasons, "issue_number": plan.issue_number}
    status, reasons = _final_verify_closed(plan, transport)
    if status == "unverified":
        return {"status": "closed-unverified", "reason_codes": reasons, "issue_number": plan.issue_number}
    if status == "label-flagged" or label_flagged:
        return {"status": "closed-verified-label-reconciliation-required", "reason_codes": (), "issue_number": plan.issue_number}
    return {"status": "closed-verified", "reason_codes": (), "issue_number": plan.issue_number}


def execute_plan(plan: SessionClosurePlan, transport: SessionClosureTransport, *, recovery_authorized: bool = False) -> dict:
    """Execute one admitted plan against a transport, enforcing the contract.

    Returns an outcome dict with status and reason codes. Refusals and
    unresolved runs record zero writes for the refused/unresolved portion;
    the transport itself records the operation log the tests assert on.
    Uncertain writes are never retried: a fresh readback decides, and an
    unavailable readback stops the run as unresolved. Already-closed
    issues receive zero mutations unless ``recovery_authorized`` is True,
    in which case the recovery path runs and never re-closes.
    """
    try:
        fresh = transport.fresh_read()
    except TransportUnavailable:
        return {"status": "unresolved", "reason_codes": ("session-closure.readback-unavailable",), "issue_number": plan.issue_number}
    status, reasons = verify_prewrite(plan, fresh)
    if status == "refused":
        return {"status": "refused", "reason_codes": reasons, "issue_number": plan.issue_number}
    if status == "already-closed":
        if not recovery_authorized:
            # F3 default: zero mutations, report-only label disposition.
            return {
                "status": "already-closed-no-action",
                "reason_codes": ("session-closure.recovery-authorization-required",),
                "issue_number": plan.issue_number,
                "label_present": bool(plan.label_required and READY_LABEL in fresh.labels),
            }
        return _recover_closed(plan, transport, fresh)
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


def execute_session_closure(
    *,
    registry: HostRegistry,
    owner_grant_token: str | None,
    qa_delivery_token: str | None,
    snapshot: LifecycleStateSnapshot,
    body_digest: str,
    trigger_id: str,
    trigger_body: str,
    transport: SessionClosureTransport,
    satisfaction: object | None = None,
    other_qa_delivery_tokens: tuple[str, ...] = (),
    recovery_grant_token: str | None = None,
) -> dict:
    """THE production entry point. The host calls this; nothing else admits.

    Resolves the owner grant and QA delivery in the host registry,
    builds the plan through canonical admission, verifies pre-write
    against a fresh transport read, and executes through the transport.
    Any refusal happens before any mutation. A recovery grant, when
    supplied, is validated against the built plan's issue and receipt
    before the executor runs; an invalid recovery grant refuses the
    whole run with zero mutations.
    """
    plan, reasons = build_plan(
        registry=registry,
        owner_grant_token=owner_grant_token,
        qa_delivery_token=qa_delivery_token,
        snapshot=snapshot,
        body_digest=body_digest,
        trigger_id=trigger_id,
        trigger_body=trigger_body,
        satisfaction=satisfaction,
        other_qa_delivery_tokens=other_qa_delivery_tokens,
    )
    if plan is None:
        return {"status": "refused", "reason_codes": reasons, "issue_number": snapshot.issue_number}
    recovery_authorized = False
    if recovery_grant_token is not None:
        recovery = registry.resolve_recovery(recovery_grant_token)
        if (
            recovery is None
            or recovery.issue_number != plan.issue_number
            or recovery.receipt_id != plan.receipt_id
        ):
            return {"status": "refused", "reason_codes": ("session-closure.recovery-grant-invalid",), "issue_number": plan.issue_number}
        recovery_authorized = True
    return execute_plan(plan, transport, recovery_authorized=recovery_authorized)


def execute_batch(items: list[tuple]) -> list[dict]:
    """Execute plans independently: a blocked item never stops the next.

    Each item is (plan, transport) or (plan, transport, recovery_authorized).
    """
    outcomes: list[dict] = []
    for item in items:
        plan, transport = item[0], item[1]
        recovery_authorized = bool(item[2]) if len(item) > 2 else False
        outcomes.append(execute_plan(plan, transport, recovery_authorized=recovery_authorized))
    return outcomes
