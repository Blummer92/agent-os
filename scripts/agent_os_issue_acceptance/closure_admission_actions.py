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


@dataclass(frozen=True, slots=True)
class ClosureAcceptanceEvidence:
    """Independent acceptance judgment for one issue, supplied by QA.

    The evaluator must be independent of the owner-decision authorizer;
    ``run_closure_batch``/``evaluate_issue_closure`` refuse self-acceptance.
    """

    verdict: Literal["pass", "fail", "missing"]
    evidence_id: str
    evaluator_id: str

    def __post_init__(self) -> None:
        if self.verdict not in ("pass", "fail", "missing"):
            raise ValueError("acceptance verdict is unsupported")
        if type(self.evidence_id) is not str or not self.evidence_id:
            raise TypeError("evidence_id must be a non-empty built-in string")
        if type(self.evaluator_id) is not str or not self.evaluator_id:
            raise TypeError("evaluator_id must be a non-empty built-in string")


# ---------------------------------------------------------------------------
# Satisfaction evidence snapshots (#3680, Option B).
#
# The satisfaction record is produced by the reporting domain
# (``criterion_satisfaction``), which this approval-domain module must not
# import (architecture dependency-direction contract). The producer
# therefore hands over a plain mapping with the block shape below, and
# this module strictly validates it at the request boundary and stores a
# defensive copy in immutable form, so later mutation of the caller's
# mapping cannot change the packet. A malformed, mistyped, or internally
# inconsistent snapshot is rejected with TypeError / ValueError here —
# it is never silently accepted and never interpreted as complete. The
# snapshot is cited evidence for the QA judgment only; it is never an
# input to the admission decision.
# ---------------------------------------------------------------------------

_SATISFACTION_STATUSES = frozenset({"complete", "incomplete", "manual-review"})
_SATISFACTION_DISPOSITIONS = frozenset({
    "satisfied", "unsatisfied", "stale", "missing", "contradicted",
    "manual-review",
})
_SATISFACTION_KEYS = frozenset({"issue_body_digest", "status", "criteria"})
_SATISFACTION_CRITERION_KEYS = frozenset({
    "index", "identity", "disposition", "reason_code", "evidence",
})
_HEX_DIGITS = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class _SatisfactionCriterionSnapshot:
    index: int
    identity: str
    disposition: str
    reason_code: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SatisfactionSnapshot:
    """One immutable, validated satisfaction evidence snapshot."""

    issue_body_digest: str
    status: str
    criteria: tuple[_SatisfactionCriterionSnapshot, ...]

    @property
    def complete(self) -> bool:
        return self.status == "complete"


def _satisfaction_snapshot(value: object) -> _SatisfactionSnapshot:
    """Validate one caller-supplied snapshot mapping; return the frozen copy.

    Key sets are exact (missing or extra keys are rejected), types are
    exact built-ins (a bool is not an index; criteria and evidence must
    be exact lists), and the declared status must agree with the
    criteria under the same derivation the #3678 projector applies:
    ``complete`` iff at least one criterion exists and every criterion
    is satisfied; ``manual-review`` iff any criterion is manual-review
    (an empty criterion list only ever carries ``manual-review``);
    otherwise ``incomplete``. A status that disagrees — in particular a
    ``complete`` claim over unsatisfied, stale, missing, contradicted,
    or absent criteria — is forged or inconsistent and is rejected.
    """
    if type(value) is _SatisfactionSnapshot:
        return value
    if type(value) is not dict:
        raise TypeError("satisfaction must be an exact dict snapshot")
    if set(value) != _SATISFACTION_KEYS:
        raise ValueError(
            "satisfaction snapshot keys must be exactly "
            "issue_body_digest, status, criteria"
        )
    digest = value["issue_body_digest"]
    if (
        type(digest) is not str
        or len(digest) != 64
        or any(ch not in _HEX_DIGITS for ch in digest)
    ):
        raise ValueError(
            "satisfaction issue_body_digest must be a 64-char lowercase hex digest"
        )
    status = value["status"]
    if type(status) is not str or status not in _SATISFACTION_STATUSES:
        raise ValueError("satisfaction status is unsupported")
    raw_criteria = value["criteria"]
    if type(raw_criteria) is not list:
        raise TypeError("satisfaction criteria must be an exact list")
    criteria: list[_SatisfactionCriterionSnapshot] = []
    for position, raw in enumerate(raw_criteria, start=1):
        if type(raw) is not dict:
            raise TypeError("satisfaction criterion must be an exact dict")
        if set(raw) != _SATISFACTION_CRITERION_KEYS:
            raise ValueError(
                "satisfaction criterion keys must be exactly index, "
                "identity, disposition, reason_code, evidence"
            )
        index = raw["index"]
        if type(index) is not int:
            raise TypeError("satisfaction criterion index must be a built-in int")
        if index != position:
            raise ValueError(
                "satisfaction criterion indexes must be 1..N contiguous, "
                "unique, and in order"
            )
        identity = raw["identity"]
        if type(identity) is not str or not identity:
            raise TypeError(
                "satisfaction criterion identity must be a non-empty string"
            )
        disposition = raw["disposition"]
        if type(disposition) is not str or disposition not in _SATISFACTION_DISPOSITIONS:
            raise ValueError("satisfaction criterion disposition is unsupported")
        reason_code = raw["reason_code"]
        if type(reason_code) is not str or not reason_code:
            raise TypeError(
                "satisfaction criterion reason_code must be a non-empty string"
            )
        evidence = raw["evidence"]
        if (
            type(evidence) is not list
            or not evidence
            or any(type(pointer) is not str or not pointer for pointer in evidence)
        ):
            raise TypeError(
                "satisfaction criterion evidence must be a non-empty list "
                "of non-empty string pointers"
            )
        criteria.append(
            _SatisfactionCriterionSnapshot(
                index, identity, disposition, reason_code, tuple(evidence)
            )
        )
    if not criteria:
        derived = "manual-review"
    elif all(item.disposition == "satisfied" for item in criteria):
        derived = "complete"
    elif any(item.disposition == "manual-review" for item in criteria):
        derived = "manual-review"
    else:
        derived = "incomplete"
    if status != derived:
        raise ValueError("satisfaction status disagrees with its criteria")
    return _SatisfactionSnapshot(digest, status, tuple(criteria))


def _satisfaction_block(
    snapshot: _SatisfactionSnapshot,
) -> dict[str, object]:
    """Serialize one validated satisfaction snapshot for the packet (#3680).

    Carries the snapshot's issue-body digest, overall status, and
    per-criterion identities, dispositions, reason codes, and evidence
    pointers exactly as validated. The block is cited evidence for the QA
    judgment only; it is never an input to the admission decision.
    """
    return {
        "issue_body_digest": snapshot.issue_body_digest,
        "status": snapshot.status,
        "criteria": [
            {
                "index": item.index,
                "identity": item.identity,
                "disposition": item.disposition,
                "reason_code": item.reason_code,
                "evidence": list(item.evidence),
            }
            for item in snapshot.criteria
        ],
    }


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


CLOSURE_STATE_REASONS = frozenset({"completed", "not_planned", "duplicate"})


@dataclass(frozen=True, slots=True)
class ClosureIssueReadback:
    """Canonical issue readback carrying GitHub ``state_reason`` evidence.

    Wraps the shared ``LifecycleStateSnapshot`` (which has no
    ``state_reason`` field and is not modified) with the closure reason
    observed by the host's canonical read. ``state_reason`` must be
    ``None`` or one of ``"completed"`` / ``"not_planned"`` /
    ``"duplicate"``; anything else raises ``ValueError``.
    """

    snapshot: LifecycleStateSnapshot
    state_reason: str | None

    def __post_init__(self) -> None:
        if type(self.snapshot) is not LifecycleStateSnapshot:
            raise TypeError("snapshot must be a LifecycleStateSnapshot")
        if self.state_reason is not None and self.state_reason not in CLOSURE_STATE_REASONS:
            raise ValueError("state_reason is unsupported")


class ClosureIssueReader(Protocol):
    """Canonical GitHub read surface supplied by the host."""

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
    return {
        **core,
        "receipt_id": _receipt_id(core),
        "closure_performed": False,
        "merge_authorized": False,
        "side_effects_performed": False,
    }


def evaluate_issue_closure(
    request: IssueClosureRequest,
    snapshot: LifecycleStateSnapshot,
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
    satisfaction_block = (
        _satisfaction_block(request.satisfaction)
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
            satisfaction=satisfaction_block,
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
            satisfaction=satisfaction_block,
            next_action="reacquire-issue-and-reevaluate",
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
            satisfaction=satisfaction_block,
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
            satisfaction=satisfaction_block,
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
            satisfaction=satisfaction_block,
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
            satisfaction=satisfaction_block,
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
            satisfaction=satisfaction_block,
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
    """
    if type(receipt) is not dict:
        return False
    allowed_keys = set(_RECEIPT_CORE_KEYS) | {
        "receipt_id",
        "closure_performed",
        "merge_authorized",
        "side_effects_performed",
    }
    satisfaction_core: dict[str, object] | None = None
    if "satisfaction" in receipt:
        # #3680: a satisfaction block is admitted to the key set only as
        # an additional core field. It must pass the same strict snapshot
        # validation the request boundary applies (shape, types, and
        # status/criteria consistency — a forged or inconsistent block
        # fails closed here), and its normalized form is integrity-checked
        # below by the same conditional receipt-id recomputation that
        # produced it. The recomputation binds the block to this receipt;
        # it does not authenticate the underlying evidence.
        try:
            satisfaction_core = _satisfaction_block(
                _satisfaction_snapshot(receipt.get("satisfaction"))
            )
        except (TypeError, ValueError):
            return False
        allowed_keys.add("satisfaction")
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
    if receipt.get("authorization_id") != authorization.authorization_id:
        return False
    if receipt.get("acceptance_evidence_id") != acceptance.evidence_id:
        return False
    if receipt.get("host_dispatch_contract") != HOST_DISPATCH_CONTRACT:
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


def _readback_status(
    readback: ClosureIssueReadback, *, wrote: bool
) -> tuple[str, tuple[str, ...], bool]:
    """Classify a canonical readback (snapshot + ``state_reason``).

    A closed snapshot is verified only when ``state_reason`` is
    ``"completed"``; ``"not_planned"``/``"duplicate"`` is a reason
    mismatch and a missing reason is unverified. An open snapshot
    carrying a terminal reason is inconsistent.
    """
    snapshot = readback.snapshot
    if snapshot.issue_state == "closed":
        if readback.state_reason == "completed":
            if READY_LABEL in snapshot.lifecycle_labels:
                # Closure is proven; the stale Ready label is a separate,
                # separately-admitted reconciliation — never edited here.
                return (
                    "closed-verified-label-reconciliation-required",
                    ("closure.readback-closed", "closure.stale-ready-label-present"),
                    True,
                )
            return "closed-verified", ("closure.readback-closed",), True
        if readback.state_reason in ("not_planned", "duplicate"):
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
    if readback.state_reason is not None:
        return "readback-inconsistent", ("closure.readback-inconsistent",), False
    if wrote:
        return "write-unverified", ("closure.readback-still-open",), False
    return "still-open", ("closure.readback-still-open",), False


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
        receipt = evaluate_issue_closure(request, snapshot)
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
        if not verify_closure_admission_receipt(
            receipt,
            authorization=authorization,
            fresh_snapshot=fresh,
            acceptance=request.acceptance,
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

