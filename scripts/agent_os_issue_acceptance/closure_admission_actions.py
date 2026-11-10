"""Governed issue-closure dispatch consumer for the GitHub Service Agent (#3489).

Repairs the disconnected production edge between an admitted ``close-issue``
lifecycle mutation and the GitHub mutation itself. The neighbouring edges
already existed: owner decisions are bound by
``lifecycle_mutation_authorization.produce_lifecycle_mutation_authorization``
and admission is evaluated by
``lifecycle_mutation_guard.evaluate_lifecycle_mutation``. (Post-PR lane
disposition remains owned by ``lane_post_pr_issue_reconciliation``; the batch
consumer below records the canonical post-dispatch issue readback directly.)
What was missing — unlike Ready-for-Review, whose host consumer contract names
``verify_ready_admission_receipt`` — was a closure analogue: a caller-bound
verification gate plus a fixed host dispatch contract naming the native writer.

This module performs no GitHub I/O. It defines:

* ``evaluate_issue_closure`` — builds one content-bound closure receipt from a
  recorded owner decision, a fresh lifecycle snapshot, and independent
  acceptance evidence, reusing the existing authorization producer and the
  existing admission evaluator unchanged.
* ``verify_closure_admission_receipt`` — the caller-bound gate the host
  (GitHub Service Agent) must call against a *fresh* snapshot immediately
  before dispatch. It recomputes the admission outside the receipt; any
  drift in issue identity, revision, labels, or state fails closed.
* ``run_closure_batch`` — the finite-batch consumer. It walks exactly the
  owner-authorized issue set, in order, through injected reader/writer
  protocols (the host supplies the native GitHub MCP ``issue_write`` writer
  and a canonical reader). Per-issue blockers never stop unrelated items;
  an uncertain write is reconciled by readback before any further action and
  is never retried blindly; an already-closed issue is never re-closed.

The receipt never claims a closure happened: ``closure_performed`` is fixed
``False`` here. Closure is proven only by the post-dispatch canonical
readback outcome recorded by ``run_closure_batch``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal, Protocol

from .lifecycle_mutation_authorization import (
    LifecycleOwnerDecision,
    produce_lifecycle_mutation_authorization,
)
from .lifecycle_mutation_guard import (
    LifecycleMutationAuthorization,
    LifecycleStateSnapshot,
    evaluate_lifecycle_mutation,
)
from .satisfaction_snapshot import (
    SatisfactionCriterionSnapshot,
    SatisfactionSnapshot,
    satisfaction_block,
    validate_satisfaction_snapshot,
)

RECEIPT_SCHEMA_VERSION = "1.0"
CLOSE_ISSUE_MUTATION = "close-issue"
PROTECTED_ISSUE_NUMBERS = frozenset({3292})
READY_LABEL = "status:ready"

# The fixed host dispatch contract. The host consumer (GitHub Service Agent)
# performs exactly this native GitHub MCP call, and only after
# ``verify_closure_admission_receipt`` accepts the receipt against a fresh
# snapshot readback. Mirrors the fixed contract style of
# ``merge_admission_actions`` / the Ready host gate.
HOST_DISPATCH_CONTRACT = {
    "writer": "native-github-mcp",
    "tool": "issue_write",
    "method": "update",
    "state": "closed",
    "state_reason": "completed",
    "gate": "verify_closure_admission_receipt",
    "readback": "canonical-issue-read",
}

# The fixed post-close reconciliation contract (#3489 requirement 3). The
# host consumer performs exactly these steps after the close step above,
# and only for an item this run freshly closed and read back as verified.
# It mirrors ``github_closure_dispatch._reconcile_closed_items`` step for
# step, so a host executing this contract and the dispatcher running with
# a GitHub transport perform the same mutations in the same order. The
# label is removed only when the batch flagged it stale; the comment body
# is deterministic verified facts only, carries no closing keyword and no
# other issue reference; a reconciliation failure never reverses a
# verified closure, never retries, and never stops the next item.
POST_CLOSE_RECONCILIATION_CONTRACT = {
    "scope": "freshly-closed-verified-only",
    "label": "status:ready",
    "label_removal_condition": "closure.stale-ready-label-present",
    "comment_fields": (
        "repository",
        "issue_number",
        "closed-completed-state",
        "acceptance_evidence_id",
        "acceptance_evaluator_id",
        "admission_receipt_id",
    ),
    "comment_forbidden_substrings": ("closes #", "fixes #", "resolves #"),
    "readback": "canonical-issue-read",
    "readback_requirements": (
        "closed",
        "completed",
        "label-absent",
        "comment-present-by-receipt-id",
    ),
    "failure": "closure-stays-verified-no-retry-next-item-continues",
}


@dataclass(frozen=True, slots=True)
class ClosureAcceptanceEvidence:
    """Independent acceptance judgment for one issue, supplied by QA.

    The evaluator must be independent of the owner-decision authorizer;
    ``run_closure_batch``/``evaluate_issue_closure`` refuse self-acceptance.
    """

    verdict: Literal["pass", "fail", "missing"]
    evidence_id: str
    evaluator_id: str
    # Lane B (#3489, QA E5 C3/C7): QA evidence may now be bound to the
    # issue it judged and the exact head it validated. When a caller
    # supplies either binding, admission and verification fail closed on
    # a mismatch -- evidence produced for another issue, or for a
    # different (stale / wrong) head, cannot satisfy closure. Both fields
    # are optional so existing callers keep working; an unbound record
    # carries no binding claim and is never upgraded to a bound one.
    issue_number: int | None = None
    validated_head_sha: str | None = None

    def __post_init__(self) -> None:
        if self.verdict not in ("pass", "fail", "missing"):
            raise ValueError("acceptance verdict is unsupported")
        if type(self.evidence_id) is not str or not self.evidence_id:
            raise TypeError("evidence_id must be a non-empty built-in string")
        if type(self.evaluator_id) is not str or not self.evaluator_id:
            raise TypeError("evaluator_id must be a non-empty built-in string")
        if self.issue_number is not None and (
            type(self.issue_number) is not int or self.issue_number < 1
        ):
            raise TypeError("acceptance issue_number must be None or a positive built-in int")
        if self.validated_head_sha is not None and (
            type(self.validated_head_sha) is not str or not self.validated_head_sha
        ):
            raise TypeError("acceptance validated_head_sha must be None or a non-empty string")


# ---------------------------------------------------------------------------
# Satisfaction evidence snapshots (#3680, Option B + follow-up N1/N2).
#
# The satisfaction record is produced by the reporting domain
# (``criterion_satisfaction``), which this approval-domain module must not
# import (architecture dependency-direction contract). The producer hands
# over a plain mapping; the single strict validator for it is the shared
# approval-domain core ``satisfaction_snapshot`` (#3690 CR-1), which this
# module applies at the request boundary and stores as an immutable
# defensive copy, so later mutation of the caller's mapping cannot change
# the packet. A malformed, mistyped, or internally inconsistent snapshot is
# rejected with TypeError / ValueError — never silently accepted and never
# interpreted as complete. The private names below are thin aliases kept
# for existing callers.
#
# Lane B (#3489, QA E5/D1): a *present* snapshot is also an admission input
# in one narrow way -- a present record that is not ``complete`` blocks
# admission (see ``evaluate_issue_closure``). An absent record still
# neither grants nor blocks; making satisfaction mandatory remains the open
# #3676 decision.
#
# N1: ``IssueClosureRequest`` — which holds the authoritative identity in
# its owner decision — rejects a snapshot naming any other issue. The
# shared serializer ``satisfaction_block`` excludes ``closure_ready`` for
# the hashed receipt core and the verifier's exact key-set check.
# ---------------------------------------------------------------------------

_SatisfactionCriterionSnapshot = SatisfactionCriterionSnapshot
_SatisfactionSnapshot = SatisfactionSnapshot
_satisfaction_snapshot = validate_satisfaction_snapshot



@dataclass(frozen=True, slots=True)
class IssueClosureRequest:
    """One item of the finite owner-authorized closure set."""

    decision: LifecycleOwnerDecision
    acceptance: ClosureAcceptanceEvidence
    satisfaction: _SatisfactionSnapshot | dict[str, object] | None = None

    def __post_init__(self) -> None:
        if type(self.decision) is not LifecycleOwnerDecision:
            raise TypeError("decision must be a LifecycleOwnerDecision")
        if type(self.acceptance) is not ClosureAcceptanceEvidence:
            raise TypeError("acceptance must be ClosureAcceptanceEvidence")
        if self.satisfaction is not None:
            # Strictly validate the caller-supplied snapshot mapping and
            # store the frozen defensive copy (#3680 Option B).
            object.__setattr__(
                self, "satisfaction", _satisfaction_snapshot(self.satisfaction)
            )
        if self.decision.issue_number is None:
            raise ValueError("closure request requires an issue target")
        if tuple(self.decision.requested_mutations) != (CLOSE_ISSUE_MUTATION,):
            raise ValueError("closure request may authorize only the close-issue mutation")
        if self.satisfaction is not None:
            # N1: the snapshot's envelope identity must name the
            # decision's issue — satisfaction evidence produced for
            # another issue is rejected at this authoritative boundary.
            if (
                self.satisfaction.repository != self.decision.repository
                or self.satisfaction.issue_number != self.decision.issue_number
            ):
                raise ValueError(
                    "satisfaction snapshot identity does not match the "
                    "closure request issue"
                )


CLOSURE_STATE_REASONS = frozenset({"completed", "not_planned", "duplicate"})


@dataclass(frozen=True, slots=True)
class ClosureIssueReadback:
    """Canonical issue readback carrying GitHub ``state_reason`` evidence.

    Wraps the shared ``LifecycleStateSnapshot`` (which has no
    ``state_reason`` field and is not modified) with the closure reason
    observed by the host's canonical read. ``state_reason`` must be
    ``None`` or one of ``"completed"`` / ``"not_planned"`` /
    ``"duplicate"``; anything else raises ``ValueError``.

    ``issue_body_digest`` (#3690 ADV-1) is the sha256 hex digest of the
    issue body observed by the same canonical read, when the reader can
    supply it. ``run_closure_batch`` passes it to ``evaluate_issue_closure``
    as the current digest, so a satisfaction record produced for a
    superseded body revision cannot authorize closure; dispatch is then
    bound to that exact evaluated revision by the verification gate.
    ``None`` means the reader supplied no body evidence; currentness is
    then neither proven nor fabricated.
    """

    snapshot: LifecycleStateSnapshot
    state_reason: str | None
    issue_body_digest: str | None = None

    def __post_init__(self) -> None:
        if type(self.snapshot) is not LifecycleStateSnapshot:
            raise TypeError("snapshot must be a LifecycleStateSnapshot")
        if self.state_reason is not None and self.state_reason not in CLOSURE_STATE_REASONS:
            raise ValueError("state_reason is unsupported")
        if self.issue_body_digest is not None and not _is_body_digest(
            self.issue_body_digest
        ):
            raise ValueError(
                "issue_body_digest must be None or a 64-char lowercase hex digest"
            )


def _is_body_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


class ClosureIssueReader(Protocol):
    """Canonical GitHub read surface supplied by the host.

    ``read_issue_readback`` should report ``issue_body_digest`` (#3690
    ADV-1) so satisfaction currentness is proven rather than unavailable.
    The pre-dispatch ``read_issue_snapshot`` carries no digest, so a body
    edit between the two reads is refused only through the exact snapshot
    binding: the reader's ``observed_revision`` must change whenever the
    issue body changes (a content-addressed revision such as
    ``github-issue-v1`` does).
    """

    def read_issue_snapshot(
        self, repository: str, issue_number: int
    ) -> LifecycleStateSnapshot: ...

    def read_issue_readback(
        self, repository: str, issue_number: int
    ) -> ClosureIssueReadback: ...


class ClosureIssueWriter(Protocol):
    """GitHub Service Agent writer supplied by the host (native issue_write)."""

    def close_issue(
        self, repository: str, issue_number: int, *, state_reason: str
    ) -> None: ...


class ClosureWriteUncertain(Exception):
    """The write may have been applied but its response was lost."""


_RECEIPT_CORE_KEYS = (
    "schema_version",
    "operation",
    "repository",
    "issue_number",
    "admitted",
    "reason_codes",
    "authorization_id",
    "admission_result_id",
    "snapshot_id",
    "acceptance_evidence_id",
    "host_dispatch_contract",
    "next_action",
)


def _canonical_block(block: object) -> str:
    return json.dumps(block, sort_keys=True, separators=(",", ":"))


def _receipt_id(core: dict[str, object]) -> str:
    digest = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"closure-admission-receipt:{digest}"


def _receipt(
    *,
    repository: str,
    issue_number: int | None,
    admitted: bool,
    reason_codes: tuple[str, ...],
    authorization_id: str | None,
    admission_result_id: str | None,
    snapshot_id: str | None,
    acceptance_evidence_id: str | None,
    next_action: str,
    satisfaction: dict[str, object] | None = None,
) -> dict[str, object]:
    core: dict[str, object] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "operation": CLOSE_ISSUE_MUTATION,
        "repository": repository,
        "issue_number": issue_number,
        "admitted": admitted,
        "reason_codes": sorted(set(reason_codes)),
        "authorization_id": authorization_id,
        "admission_result_id": admission_result_id,
        "snapshot_id": snapshot_id,
        "acceptance_evidence_id": acceptance_evidence_id,
        "host_dispatch_contract": dict(HOST_DISPATCH_CONTRACT),
        "next_action": next_action,
    }
    if satisfaction is not None:
        # Inside the hashed core (#3680): the cited satisfaction evidence
        # is integrity-bound by the receipt id exactly like every other
        # core field, and the verifier recomputes it under the same
        # conditional rule. Absent -> the core is byte-identical to the
        # pre-#3680 form. The hash binds the block against later
        # alteration of the receipt; it does not authenticate the
        # evidence itself — authenticity rests with the producing
        # verifier and the QA judgment, exactly as for the other
        # caller-bound core fields.
        core["satisfaction"] = satisfaction
    # The reconciliation contract is carried on the receipt but deliberately
    # kept OUTSIDE the hashed core: adding it to the core changed every
    # receipt id and broke the #3680 byte-identity goldens, while the
    # verify gate's direct equality check below already refuses a tampered
    # or missing contract even when the receipt id is recomputed. The
    # contract's ``admission_receipt_id`` field names the receipt id of
    # the admission this execution discharges: the host's verified receipt
    # id for a host execution, the batch receipt id for a dispatcher
    # execution. The two agree only when the host snapshot is the canonical
    # reader-constructed live snapshot; a host must verify comment presence
    # by its own verified receipt id, never by assuming the ids match.
    return {
        **core,
        "post_close_reconciliation_contract": dict(POST_CLOSE_RECONCILIATION_CONTRACT),
        "receipt_id": _receipt_id(core),
        "closure_performed": False,
        "merge_authorized": False,
        "side_effects_performed": False,
    }


def evaluate_issue_closure(
    request: IssueClosureRequest,
    snapshot: LifecycleStateSnapshot,
    *,
    current_issue_body_digest: str | None = None,
) -> dict[str, object]:
    """Build one fail-closed closure-admission receipt for one issue.

    Reuses the existing authorization producer and admission evaluator.
    Independent acceptance is checked first and must come from an evaluator
    other than the decision authorizer; admission is then bound to the exact
    issue and the snapshot's observed revision.
    """
    if type(request) is not IssueClosureRequest:
        raise TypeError("request must be an IssueClosureRequest")
    if type(snapshot) is not LifecycleStateSnapshot:
        raise TypeError("snapshot must be a LifecycleStateSnapshot")
    decision = request.decision
    repository = decision.repository
    issue_number = decision.issue_number
    satisfaction_payload = (
        satisfaction_block(request.satisfaction)
        if request.satisfaction is not None
        else None
    )
    if issue_number in PROTECTED_ISSUE_NUMBERS:
        return _receipt(
            repository=repository,
            issue_number=issue_number,
            admitted=False,
            reason_codes=("closure.protected-target",),
            authorization_id=None,
            admission_result_id=None,
            snapshot_id=snapshot.snapshot_id,
            acceptance_evidence_id=request.acceptance.evidence_id,
            satisfaction=satisfaction_payload,
            next_action="none-protected-target",
        )
    if snapshot.repository != repository or snapshot.issue_number != issue_number:
        return _receipt(
            repository=repository,
            issue_number=issue_number,
            admitted=False,
            reason_codes=("closure.issue-identity-mismatch",),
            authorization_id=None,
            admission_result_id=None,
            snapshot_id=snapshot.snapshot_id,
            acceptance_evidence_id=request.acceptance.evidence_id,
            satisfaction=satisfaction_payload,
            next_action="reacquire-issue-and-reevaluate",
        )
    # Lane B (#3489, QA E5 C1/C6 + D1): a present satisfaction record that
    # is not complete blocks admission. Reconciliation already blocks on
    # this exact condition; closure admission previously admitted over it
    # (locked in by a test that this repair inverts). An absent record is
    # unchanged: it neither grants nor blocks (mandatory satisfaction is
    # the still-open #3676 decision, not this repair).
    if request.satisfaction is not None and not request.satisfaction.complete:
        return _receipt(
            repository=repository,
            issue_number=issue_number,
            admitted=False,
            reason_codes=("closure.satisfaction-incomplete",),
            authorization_id=None,
            admission_result_id=None,
            snapshot_id=snapshot.snapshot_id,
            acceptance_evidence_id=request.acceptance.evidence_id,
            satisfaction=satisfaction_payload,
            next_action="obtain-complete-satisfaction-and-reevaluate",
        )
    # Lane B (QA E5 C2): when the caller supplies the digest of the issue
    # body as freshly read, a satisfaction record produced from any other
    # body revision is stale and fails closed.
    if (
        current_issue_body_digest is not None
        and request.satisfaction is not None
        and request.satisfaction.issue_body_digest != current_issue_body_digest
    ):
        return _receipt(
            repository=repository,
            issue_number=issue_number,
            admitted=False,
            reason_codes=("closure.satisfaction-stale",),
            authorization_id=None,
            admission_result_id=None,
            snapshot_id=snapshot.snapshot_id,
            acceptance_evidence_id=request.acceptance.evidence_id,
            satisfaction=satisfaction_payload,
            next_action="reacquire-issue-and-reevaluate",
        )
    # Lane B (QA E5 C3/C7): bound QA evidence, when it carries a binding,
    # must name this issue and the snapshot's exact head.
    if (
        request.acceptance.issue_number is not None
        and request.acceptance.issue_number != issue_number
    ):
        return _receipt(
            repository=repository,
            issue_number=issue_number,
            admitted=False,
            reason_codes=("closure.acceptance-issue-mismatch",),
            authorization_id=None,
            admission_result_id=None,
            snapshot_id=snapshot.snapshot_id,
            acceptance_evidence_id=request.acceptance.evidence_id,
            satisfaction=satisfaction_payload,
            next_action="obtain-acceptance-for-this-issue",
        )
    # #3690 ADV-2: a QA record that claims a validated head can only be
    # honoured against a snapshot that carries a comparable head. A
    # head-less snapshot neither confirms nor refutes the binding, so it
    # fails closed instead of silently skipping the comparison. Unbound QA
    # evidence (no validated_head_sha) is unaffected: legitimate issue-only
    # closure never needs a manufactured PR head.
    if (
        request.acceptance.validated_head_sha is not None
        and snapshot.source_head is None
    ):
        return _receipt(
            repository=repository,
            issue_number=issue_number,
            admitted=False,
            reason_codes=("closure.acceptance-head-unverifiable",),
            authorization_id=None,
            admission_result_id=None,
            snapshot_id=snapshot.snapshot_id,
            acceptance_evidence_id=request.acceptance.evidence_id,
            satisfaction=satisfaction_payload,
            next_action="reacquire-snapshot-with-validated-head",
        )
    if (
        request.acceptance.validated_head_sha is not None
        and request.acceptance.validated_head_sha != snapshot.source_head
    ):
        return _receipt(
            repository=repository,
            issue_number=issue_number,
            admitted=False,
            reason_codes=("closure.acceptance-head-mismatch",),
            authorization_id=None,
            admission_result_id=None,
            snapshot_id=snapshot.snapshot_id,
            acceptance_evidence_id=request.acceptance.evidence_id,
            satisfaction=satisfaction_payload,
            next_action="obtain-acceptance-for-exact-head",
        )
    if request.acceptance.evaluator_id == decision.authorizer_id:
        return _receipt(
            repository=repository,
            issue_number=issue_number,
            admitted=False,
            reason_codes=("closure.acceptance-not-independent",),
            authorization_id=None,
            admission_result_id=None,
            snapshot_id=snapshot.snapshot_id,
            acceptance_evidence_id=request.acceptance.evidence_id,
            satisfaction=satisfaction_payload,
            next_action="obtain-independent-acceptance",
        )
    if request.acceptance.verdict != "pass":
        return _receipt(
            repository=repository,
            issue_number=issue_number,
            admitted=False,
            reason_codes=("closure.acceptance-not-passed",),
            authorization_id=None,
            admission_result_id=None,
            snapshot_id=snapshot.snapshot_id,
            acceptance_evidence_id=request.acceptance.evidence_id,
            satisfaction=satisfaction_payload,
            next_action="obtain-independent-acceptance",
        )
    try:
        authorization = produce_lifecycle_mutation_authorization(decision, snapshot)
    except PermissionError:
        return _receipt(
            repository=repository,
            issue_number=issue_number,
            admitted=False,
            reason_codes=("closure.authorization-not-recorded",),
            authorization_id=None,
            admission_result_id=None,
            snapshot_id=snapshot.snapshot_id,
            acceptance_evidence_id=request.acceptance.evidence_id,
            satisfaction=satisfaction_payload,
            next_action="record-owner-decision",
        )
    except (TypeError, ValueError):
        return _receipt(
            repository=repository,
            issue_number=issue_number,
            admitted=False,
            reason_codes=("closure.authorization-invalid",),
            authorization_id=None,
            admission_result_id=None,
            snapshot_id=snapshot.snapshot_id,
            acceptance_evidence_id=request.acceptance.evidence_id,
            satisfaction=satisfaction_payload,
            next_action="reacquire-issue-and-reevaluate",
        )
    admission = evaluate_lifecycle_mutation(
        authorization, snapshot, CLOSE_ISSUE_MUTATION
    )
    return _receipt(
        repository=repository,
        issue_number=issue_number,
        admitted=admission.admitted,
        reason_codes=admission.reason_codes,
        authorization_id=authorization.authorization_id,
        admission_result_id=admission.result_id,
        snapshot_id=snapshot.snapshot_id,
        acceptance_evidence_id=request.acceptance.evidence_id,
        satisfaction=satisfaction_payload,
        next_action=(
            "host-close-issue-then-canonical-readback"
            if admission.admitted
            else "resolve-reasons-and-reevaluate"
        ),
    )


def verify_closure_admission_receipt(
    receipt: dict[str, object],
    *,
    authorization: LifecycleMutationAuthorization,
    fresh_snapshot: LifecycleStateSnapshot,
    acceptance: ClosureAcceptanceEvidence,
    satisfaction: _SatisfactionSnapshot | dict[str, object] | None = None,
    current_issue_body_digest: str | None = None,
) -> bool:
    """Caller-bound host gate: recompute everything outside the receipt.

    The host must call this with the authorization the receipt claims, the
    independent acceptance evidence it claims, and a freshly reacquired
    snapshot immediately before invoking the native writer. Returns True
    only when the receipt is the exact, still-current admitted closure for
    the same issue and revision: the receipt id is recomputed over the
    receipt core, every core field is checked against the recomputed
    admission and the caller-supplied acceptance, the acceptance must be a
    pass from an evaluator other than the authorizer, and the authorization
    must permit the close-issue mutation and nothing else. Any drift or
    forgery — stale revision, changed labels/state, wrong issue, tampered
    receipt fields, synthetic receipts that never passed evaluation —
    fails closed.

    Satisfaction (#3690 ADV-6/ADV-7). The receipt id is an unkeyed content
    hash, so a caller can recompute it after editing the receipt; it binds
    the receipt's own bytes and authenticates nothing. A satisfaction block
    carried inside the receipt is therefore never trusted on its own. The
    caller supplies ``satisfaction`` — the satisfaction record it reacquired
    independently of the receipt, exactly like ``acceptance`` — and the gate
    requires the receipt block and the trusted record to agree: a receipt
    that cites satisfaction verifies only when a matching, complete,
    same-issue trusted record is supplied, and a supplied trusted record
    verifies only a receipt that carries exactly its block. Stripping the
    block, swapping it, or adding one the verifier does not hold fails
    closed. When neither side carries satisfaction the gate behaves exactly
    as before: satisfaction stays optional (mandatory satisfaction is the
    separate #3676 decision).

    ``current_issue_body_digest`` (#3690 ADV-1) is the digest of the issue
    body as freshly read before dispatch. When supplied it must be a valid
    digest and must equal the trusted satisfaction record's digest; a digest
    without a trusted satisfaction record has nothing to bind and fails
    closed.
    """
    if type(receipt) is not dict:
        return False
    allowed_keys = set(_RECEIPT_CORE_KEYS) | {
        "receipt_id",
        "closure_performed",
        "merge_authorized",
        "side_effects_performed",
        # Carried on the receipt but outside the hashed core (see _receipt):
        # allowed here, and bound by the direct equality check below.
        "post_close_reconciliation_contract",
    }
    trusted: _SatisfactionSnapshot | None = None
    if satisfaction is not None:
        try:
            trusted = _satisfaction_snapshot(satisfaction)
        except (TypeError, ValueError):
            return False
    if ("satisfaction" in receipt) != (trusted is not None):
        # A self-attested block with no trusted record, or a trusted record
        # whose block was stripped from the receipt (ADV-6), never verifies.
        return False
    satisfaction_core: dict[str, object] | None = None
    if trusted is not None:
        satisfaction_core = satisfaction_block(trusted)
        # ADV-7: the receipt must cite exactly the trusted record. The block
        # is first strictly validated (exact built-in types, so ``True`` is
        # never an index and ``3432.0`` never an issue number), then compared
        # by canonical bytes rather than Python equality; a swapped,
        # substituted, re-typed, or re-ordered block fails closed.
        try:
            _satisfaction_snapshot(receipt.get("satisfaction"))
            if _canonical_block(receipt.get("satisfaction")) != _canonical_block(
                satisfaction_core
            ):
                return False
        except (TypeError, ValueError):
            return False
        allowed_keys.add("satisfaction")
    if current_issue_body_digest is not None and (
        trusted is None
        or not _is_body_digest(current_issue_body_digest)
        or trusted.issue_body_digest != current_issue_body_digest
    ):
        return False
    if set(receipt) != allowed_keys:
        return False
    if type(authorization) is not LifecycleMutationAuthorization:
        return False
    if type(fresh_snapshot) is not LifecycleStateSnapshot:
        return False
    if type(acceptance) is not ClosureAcceptanceEvidence:
        return False
    if authorization.issue_number in PROTECTED_ISSUE_NUMBERS:
        return False
    if tuple(authorization.authorized_mutations) != (CLOSE_ISSUE_MUTATION,):
        return False
    if acceptance.verdict != "pass":
        return False
    if acceptance.evaluator_id == authorization.authorizer_id:
        return False
    # Lane B (#3489): a present-but-incomplete satisfaction record can never
    # verify, and bound QA evidence must name the authorized issue and the
    # fresh snapshot's exact head. ADV-2: a head-less fresh snapshot cannot
    # confirm a head binding, so it fails closed.
    if trusted is not None and not trusted.complete:
        return False
    if trusted is not None and (
        trusted.repository != authorization.repository
        or trusted.issue_number != authorization.issue_number
    ):
        return False
    if acceptance.issue_number is not None and acceptance.issue_number != authorization.issue_number:
        return False
    if acceptance.validated_head_sha is not None and (
        fresh_snapshot.source_head is None
        or acceptance.validated_head_sha != fresh_snapshot.source_head
    ):
        return False
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        return False
    if receipt.get("closure_performed") is not False:
        return False
    if receipt.get("merge_authorized") is not False:
        return False
    if receipt.get("side_effects_performed") is not False:
        return False
    if receipt.get("next_action") != "host-close-issue-then-canonical-readback":
        return False
    if receipt.get("operation") != CLOSE_ISSUE_MUTATION:
        return False
    if receipt.get("repository") != authorization.repository:
        return False
    if receipt.get("issue_number") != authorization.issue_number:
        return False
    if trusted is not None and (
        trusted.repository != receipt.get("repository")
        or trusted.issue_number != receipt.get("issue_number")
    ):
        # #3680: the receipt-id recomputation binds the block's bytes, not
        # its identity. The cited evidence must belong to this receipt's
        # canonical repository and issue (the fields just bound to the
        # authorization above).
        return False
    if receipt.get("authorization_id") != authorization.authorization_id:
        return False
    if receipt.get("acceptance_evidence_id") != acceptance.evidence_id:
        return False
    if receipt.get("host_dispatch_contract") != HOST_DISPATCH_CONTRACT:
        return False
    if receipt.get("post_close_reconciliation_contract") != POST_CLOSE_RECONCILIATION_CONTRACT:
        return False
    admission = evaluate_lifecycle_mutation(
        authorization, fresh_snapshot, CLOSE_ISSUE_MUTATION
    )
    if not admission.admitted:
        return False
    if receipt.get("admission_result_id") != admission.result_id:
        return False
    if receipt.get("snapshot_id") != fresh_snapshot.snapshot_id:
        return False
    if receipt.get("admitted") is not True:
        return False
    if receipt.get("reason_codes") != []:
        return False
    core = {key: receipt.get(key) for key in _RECEIPT_CORE_KEYS}
    if satisfaction_core is not None:
        core["satisfaction"] = satisfaction_core
    try:
        expected_receipt_id = _receipt_id(core)
    except (TypeError, ValueError):
        return False
    return receipt.get("receipt_id") == expected_receipt_id


@dataclass(frozen=True, slots=True)
class ClosureBatchOutcome:
    issue_number: int
    status: str
    reason_codes: tuple[str, ...]
    receipt: dict[str, object] | None = field(default=None)
    readback_verified: bool = False


def _identity_mismatch(
    snapshot: LifecycleStateSnapshot, repository: str, issue_number: int
) -> bool:
    return snapshot.repository != repository or snapshot.issue_number != issue_number


def classify_closure_readback(
    *,
    issue_closed: bool,
    state_reason: str | None,
    lifecycle_labels: tuple[str, ...],
    wrote: bool,
) -> tuple[str, tuple[str, ...], bool]:
    """Classify one canonical issue readback (state, ``state_reason``, labels).

    The single closure-readback rule, shared by ``run_closure_batch`` and
    the lane post-PR readback proof (#3690 ADV-5). A closed issue is
    verified only when ``state_reason`` is ``"completed"``;
    ``"not_planned"``/``"duplicate"`` is a reason mismatch and a missing
    reason is unverified. A verified closure that still carries the Ready
    label is flagged for separately admitted label reconciliation. An open
    issue carrying a terminal reason is inconsistent. Returns
    ``(status, reason_codes, verified)``.
    """
    if type(issue_closed) is not bool or type(wrote) is not bool:
        raise TypeError("issue_closed and wrote must be built-in bools")
    if state_reason is not None and state_reason not in CLOSURE_STATE_REASONS:
        raise ValueError("state_reason is unsupported")
    if issue_closed:
        if state_reason == "completed":
            if READY_LABEL in lifecycle_labels:
                # Closure is proven; the stale Ready label is a separate,
                # separately-admitted reconciliation — never edited here.
                return (
                    "closed-verified-label-reconciliation-required",
                    ("closure.readback-closed", "closure.stale-ready-label-present"),
                    True,
                )
            return "closed-verified", ("closure.readback-closed",), True
        if state_reason in ("not_planned", "duplicate"):
            return (
                "closed-reason-mismatch",
                ("closure.readback-reason-mismatch",),
                False,
            )
        return (
            "closed-reason-unverified",
            ("closure.readback-reason-unverified",),
            False,
        )
    if state_reason is not None:
        return "readback-inconsistent", ("closure.readback-inconsistent",), False
    if wrote:
        return "write-unverified", ("closure.readback-still-open",), False
    return "still-open", ("closure.readback-still-open",), False


def _readback_status(
    readback: ClosureIssueReadback, *, wrote: bool
) -> tuple[str, tuple[str, ...], bool]:
    """Classify a canonical readback (snapshot + ``state_reason``)."""
    snapshot = readback.snapshot
    return classify_closure_readback(
        issue_closed=snapshot.issue_state == "closed",
        state_reason=readback.state_reason,
        lifecycle_labels=snapshot.lifecycle_labels,
        wrote=wrote,
    )


def run_closure_batch(
    requests: tuple[IssueClosureRequest, ...],
    *,
    reader: ClosureIssueReader,
    writer: ClosureIssueWriter,
) -> tuple[ClosureBatchOutcome, ...]:
    """Execute one finite owner-authorized closure set, in order.

    The set is exactly ``requests`` — nothing outside it is touched, and a
    duplicate issue in the set is refused rather than broadened. Each issue
    is independently gated (acceptance → authorization → admission →
    verify-against-fresh-read → writer → canonical readback); a blocker on
    one issue is recorded and the batch continues with the next.
    """
    if type(requests) is not tuple or not requests:
        raise ValueError("requests must be a non-empty exact tuple")
    if any(type(item) is not IssueClosureRequest for item in requests):
        raise TypeError("requests must contain only IssueClosureRequest items")
    numbers = [item.decision.issue_number for item in requests]
    if len(set(numbers)) != len(numbers):
        raise ValueError("closure set contains a duplicate issue")

    outcomes: list[ClosureBatchOutcome] = []
    for request in requests:
        decision = request.decision
        issue_number = decision.issue_number
        assert issue_number is not None  # enforced by IssueClosureRequest
        repository = decision.repository
        try:
            initial_readback = reader.read_issue_readback(repository, issue_number)
            if type(initial_readback) is not ClosureIssueReadback:
                raise TypeError("reader must return a ClosureIssueReadback")
            snapshot = initial_readback.snapshot
        except Exception:
            outcomes.append(
                ClosureBatchOutcome(
                    issue_number, "blocked", ("closure.evidence-unavailable",)
                )
            )
            continue
        # D1: validate identity for every canonical readback, before any
        # short-circuit — a substituted snapshot never proves closure.
        if _identity_mismatch(snapshot, repository, issue_number):
            outcomes.append(
                ClosureBatchOutcome(
                    issue_number,
                    "blocked",
                    ("closure.readback-identity-mismatch",),
                )
            )
            continue
        if snapshot.issue_state == "closed":
            status, reasons, verified = _readback_status(
                initial_readback, wrote=False
            )
            if verified:
                outcomes.append(
                    ClosureBatchOutcome(
                        issue_number,
                        "already-closed",
                        ("closure.already-closed",) + reasons[1:],
                        readback_verified=True,
                    )
                )
            else:
                outcomes.append(
                    ClosureBatchOutcome(
                        issue_number, status, reasons, readback_verified=False
                    )
                )
            continue
        if initial_readback.state_reason is not None:
            outcomes.append(
                ClosureBatchOutcome(
                    issue_number,
                    "readback-inconsistent",
                    ("closure.readback-inconsistent",),
                )
            )
            continue
        # ADV-1: the canonical readback's own body digest (when the reader
        # supplies one) is the currentness evidence for the satisfaction
        # record; a record bound to any other body revision is stale.
        receipt = evaluate_issue_closure(
            request,
            snapshot,
            current_issue_body_digest=initial_readback.issue_body_digest,
        )
        if receipt["admitted"] is not True:
            outcomes.append(
                ClosureBatchOutcome(
                    issue_number,
                    "blocked",
                    tuple(receipt["reason_codes"]),  # type: ignore[arg-type]
                    receipt=receipt,
                )
            )
            continue
        # Reacquire immediately before dispatch and re-verify outside the
        # receipt: a revision that moved since evaluation fails closed here.
        try:
            authorization = produce_lifecycle_mutation_authorization(
                decision, snapshot
            )
            fresh = reader.read_issue_snapshot(repository, issue_number)
        except Exception:
            outcomes.append(
                ClosureBatchOutcome(
                    issue_number,
                    "blocked",
                    ("closure.reacquire-failed",),
                    receipt=receipt,
                )
            )
            continue
        # D1: explicit identity check on the fresh pre-dispatch snapshot,
        # in addition to the verification gate below.
        if _identity_mismatch(fresh, repository, issue_number):
            outcomes.append(
                ClosureBatchOutcome(
                    issue_number,
                    "blocked",
                    ("closure.readback-identity-mismatch",),
                    receipt=receipt,
                )
            )
            continue
        # The request's own satisfaction record is the trusted evidence the
        # gate binds the receipt block to (ADV-6/ADV-7). Body currentness was
        # proven at evaluation against this iteration's canonical readback;
        # the gate's exact snapshot binding then refuses any revision that
        # moved before dispatch.
        if not verify_closure_admission_receipt(
            receipt,
            authorization=authorization,
            fresh_snapshot=fresh,
            acceptance=request.acceptance,
            satisfaction=request.satisfaction,
        ):
            outcomes.append(
                ClosureBatchOutcome(
                    issue_number,
                    "blocked",
                    ("closure.verification-failed-stale-or-drifted",),
                    receipt=receipt,
                )
            )
            continue
        uncertain = False
        try:
            writer.close_issue(
                repository, issue_number, state_reason="completed"
            )
        except ClosureWriteUncertain:
            uncertain = True
        except Exception as exc:  # exact failure, never a false success
            outcomes.append(
                ClosureBatchOutcome(
                    issue_number,
                    "write-failed",
                    (f"closure.write-failed:{type(exc).__name__}",),
                    receipt=receipt,
                )
            )
            continue
        # Canonical readback. After an uncertain write this readback is the
        # reconciliation: its result decides the outcome and no retry is
        # attempted in this run.
        try:
            after_readback = reader.read_issue_readback(repository, issue_number)
            if type(after_readback) is not ClosureIssueReadback:
                raise TypeError("reader must return a ClosureIssueReadback")
        except Exception:
            outcomes.append(
                ClosureBatchOutcome(
                    issue_number,
                    "readback-unavailable",
                    ("closure.readback-unavailable",),
                    receipt=receipt,
                )
            )
            continue
        # D1: post-write (and post-uncertain-write) identity check — a
        # readback for any other repository/issue never verifies closure.
        if _identity_mismatch(after_readback.snapshot, repository, issue_number):
            outcomes.append(
                ClosureBatchOutcome(
                    issue_number,
                    "readback-identity-mismatch",
                    ("closure.readback-identity-mismatch",),
                    receipt=receipt,
                    readback_verified=False,
                )
            )
            continue
        status, reasons, verified = _readback_status(after_readback, wrote=True)
        if uncertain:
            # D2: a canonical readback confirming closure preserves the
            # verified outcome; only a non-closed readback is
            # "uncertain-write-not-closed". Reason-mismatch / unverified /
            # inconsistent classifications keep their own (non-verified)
            # status so the state_reason evidence is not hidden.
            if status == "closed-verified":
                status = "closed-verified-after-uncertain-write"
            elif status == "closed-verified-label-reconciliation-required":
                status = (
                    "closed-verified-after-uncertain-write"
                    "-label-reconciliation-required"
                )
            elif status == "write-unverified":
                status = "uncertain-write-not-closed"
        outcomes.append(
            ClosureBatchOutcome(
                issue_number, status, reasons, receipt=receipt,
                readback_verified=verified,
            )
        )
    return tuple(outcomes)

