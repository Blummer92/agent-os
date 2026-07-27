from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Literal

from .cost_evidence import SuppliedComputeRecord
from .dispatch_guard import DispatchDecision, serialize_dispatch_decision
from .models import ValidationPlan
from .selector import validate_validation_plan, validation_plan_id

PROVENANCE_RECEIPT_SCHEMA_NAME = "agent-os-validation-provenance-receipt"
PROVENANCE_RECEIPT_SCHEMA_VERSION = "1.0"
PROVENANCE_VERIFICATION_SCHEMA_NAME = "agent-os-validation-provenance-verification"
PROVENANCE_VERIFICATION_SCHEMA_VERSION = "1.0"
MAX_PROVENANCE_RECEIPTS = 8
MAX_PROVENANCE_TRUST_ROOTS = 32
MAX_PROVENANCE_VERIFIERS = 32
MAX_PROVENANCE_SEEN_REPLAYS = 64
MAX_PROVENANCE_STRING_LENGTH = 4096
MAX_PROVENANCE_REASON_CODES = 64
MAX_PROVENANCE_SERIALIZED_BYTES = 524_288

ProofType = Literal["provider-api", "signed-envelope", "attestation"]
TrustState = Literal[
    "verified", "unverified", "stale", "identity-mismatch", "unsupported", "manual-review"
]
TerminalStatus = Literal[
    "succeeded", "failed", "cancelled", "timed-out", "infrastructure-error"
]

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_PLAN_ID = re.compile(r"^validation-plan:[0-9a-f]{64}$")
_DECISION_ID = re.compile(r"^validation-dispatch-decision:[0-9a-f]{64}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SECRET = re.compile(
    r"(?i)(authorization\s*:|bearer\s+[A-Za-z0-9._-]{8,}|"
    r"(?:token|password|secret|api[_-]?key|private[_-]?key)\s*[:=])"
)
_PROOF_TYPES = frozenset({"provider-api", "signed-envelope", "attestation"})
_TERMINAL = frozenset(
    {"succeeded", "failed", "cancelled", "timed-out", "infrastructure-error"}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpectedProvenanceIdentity:
    evidence_source: str
    producer_identity: str
    provider: str
    provider_account: str
    provider_location: str
    trigger_identity: str


@dataclass(frozen=True, slots=True, kw_only=True)
class NormalizedVerificationReceipt:
    schema_name: str
    schema_version: str
    receipt_id: str
    proof_type: ProofType
    proof_verified: bool
    proof_digest: str
    trust_root_id: str
    verifier_id: str
    evidence_source: str
    producer_identity: str
    provider: str
    provider_account: str
    provider_location: str
    repository: str
    pull_request: int
    tested_sha: str
    profile: str
    selector_version: str
    command_set_digest: str
    plan_id: str
    dispatch_decision_id: str
    build_id: str
    trigger_identity: str
    terminal_status: TerminalStatus
    evidence_created_at: str
    retrieved_at: str
    expires_at: str
    replay_id: str
    machine_type: str = "unavailable"
    elapsed_seconds: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProvenanceVerificationResult:
    schema_name: str
    schema_version: str
    state: TrustState
    verification_id: str
    receipt: NormalizedVerificationReceipt | None
    reason_codes: tuple[str, ...]
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def verify_remote_validation_provenance(
    validation_plan: object,
    dispatch_decision: object,
    supplied_receipts: object,
    *,
    current_head_sha: object,
    expected_provenance_identity: object,
    approved_trust_roots: object,
    approved_verifiers: object,
    evaluation_time: object,
    seen_replay_ids: object = (),
    schema_version: object = PROVENANCE_VERIFICATION_SCHEMA_VERSION,
) -> ProvenanceVerificationResult:
    """Verify one normalized receipt without discovery, credentials, or external I/O."""
    reasons: dict[TrustState, set[str]] = {
        "manual-review": set(),
        "identity-mismatch": set(),
        "stale": set(),
        "unsupported": set(),
        "unverified": set(),
        "verified": set(),
    }
    manual = reasons["manual-review"]

    plan = validation_plan if type(validation_plan) is ValidationPlan else None
    plan_errors = _plan_errors(validation_plan)
    if plan_errors:
        manual.add("plan.invalid")
        manual.update(f"plan-detail.{item}" for item in plan_errors)

    decision = dispatch_decision if type(dispatch_decision) is DispatchDecision else None
    if decision is None:
        manual.add("decision.invalid-type")
    else:
        try:
            serialize_dispatch_decision(decision)
        except (TypeError, ValueError):
            manual.add("decision.invalid")

    if schema_version != PROVENANCE_VERIFICATION_SCHEMA_VERSION:
        manual.add("verification.schema-version")
    if not _match(_SHA40, current_head_sha):
        manual.add("verification.current-head")
    evaluated = _timestamp(evaluation_time)
    if evaluated is None:
        manual.add("verification.evaluation-time")

    expected = (
        expected_provenance_identity
        if type(expected_provenance_identity) is ExpectedProvenanceIdentity
        else None
    )
    if expected is None or any(not _identifier(value) for value in asdict(expected).values()):
        manual.add("verification.expected-provenance")

    roots = _identifier_set(approved_trust_roots, MAX_PROVENANCE_TRUST_ROOTS)
    verifiers = _identifier_set(approved_verifiers, MAX_PROVENANCE_VERIFIERS)
    replays = _identifier_set(seen_replay_ids, MAX_PROVENANCE_SEEN_REPLAYS, allow_empty=True)
    if roots is None:
        manual.add("verification.trust-roots")
        roots = frozenset()
    if verifiers is None:
        manual.add("verification.verifiers")
        verifiers = frozenset()
    if replays is None:
        manual.add("verification.seen-replays")
        replays = frozenset()

    receipts: tuple[NormalizedVerificationReceipt, ...] = ()
    if type(supplied_receipts) is not tuple:
        manual.add("receipts.invalid-collection")
    elif len(supplied_receipts) > MAX_PROVENANCE_RECEIPTS:
        manual.add("receipts.collection-limit")
    elif any(type(item) is not NormalizedVerificationReceipt for item in supplied_receipts):
        manual.add("receipts.invalid-record-type")
    else:
        receipts = supplied_receipts

    if not receipts and not manual:
        reasons["unverified"].add("receipt.missing")
    if len(receipts) > 1:
        manual.add("receipts.multiple")
        if len({item.receipt_id for item in receipts}) != len(receipts):
            manual.add("receipts.duplicate-receipt-id")
        if len({item.replay_id for item in receipts}) != len(receipts):
            manual.add("receipts.duplicate-replay-id")

    receipt = receipts[0] if len(receipts) == 1 else None
    if receipt is not None:
        manual.update(_receipt_errors(receipt))

    if plan is not None and decision is not None and not plan_errors:
        _compare(
            {
                "repository": plan.repository,
                "pull-request": plan.pull_request,
                "head-sha": plan.head_sha,
                "profile": plan.profile,
                "selector-version": plan.selector_version,
                "command-set-digest": plan.command_set_digest,
                "plan-id": validation_plan_id(plan),
            },
            {
                "repository": decision.repository,
                "pull-request": decision.pull_request,
                "head-sha": decision.head_sha,
                "profile": decision.profile,
                "selector-version": decision.selector_version,
                "command-set-digest": decision.command_set_digest,
                "plan-id": decision.plan_id,
            },
            manual,
            "decision",
        )
        if decision.status not in {"launch-eligible", "reused"}:
            manual.add("decision.status-unsupported")

    if receipt is not None and not _receipt_errors(receipt):
        if plan is not None and decision is not None and not plan_errors:
            _compare(
                {
                    "repository": plan.repository,
                    "pull-request": plan.pull_request,
                    "tested-sha": plan.head_sha,
                    "profile": plan.profile,
                    "selector-version": plan.selector_version,
                    "command-set-digest": plan.command_set_digest,
                    "plan-id": validation_plan_id(plan),
                    "dispatch-decision-id": decision.decision_id,
                },
                {
                    "repository": receipt.repository,
                    "pull-request": receipt.pull_request,
                    "tested-sha": receipt.tested_sha,
                    "profile": receipt.profile,
                    "selector-version": receipt.selector_version,
                    "command-set-digest": receipt.command_set_digest,
                    "plan-id": receipt.plan_id,
                    "dispatch-decision-id": receipt.dispatch_decision_id,
                },
                reasons["identity-mismatch"],
                "identity",
            )
        if expected is not None:
            _compare(
                asdict(expected),
                {key: getattr(receipt, key) for key in asdict(expected)},
                reasons["identity-mismatch"],
                "identity",
            )

        created, retrieved, expires = map(
            _timestamp, (receipt.evidence_created_at, receipt.retrieved_at, receipt.expires_at)
        )
        if None in {created, retrieved, expires}:
            manual.add("receipt.timestamp")
        elif not (created <= retrieved <= expires):
            manual.add("receipt.timestamp-order")
        elif evaluated is not None:
            if retrieved > evaluated:
                manual.add("receipt.retrieval-in-future")
            elif evaluated > expires:
                reasons["stale"].add("receipt.expired")
        if plan is not None and current_head_sha != plan.head_sha:
            reasons["stale"].add("head.stale")
        if receipt.proof_type not in _PROOF_TYPES:
            reasons["unsupported"].add("proof.type")
        if receipt.trust_root_id not in roots:
            reasons["unsupported"].add("proof.trust-root")
        if receipt.verifier_id not in verifiers:
            reasons["unsupported"].add("proof.verifier")
        if receipt.replay_id in replays:
            manual.add("receipt.replay-detected")
        if receipt.proof_verified is not True:
            reasons["unverified"].add("proof.not-verified")

    for state in ("manual-review", "identity-mismatch", "stale", "unsupported", "unverified"):
        if reasons[state]:
            return _result(receipt, state, reasons[state])
    return _result(receipt, "verified", {"proof.verified"})


def to_supplied_compute_record(
    result: ProvenanceVerificationResult, dispatch_decision: DispatchDecision
) -> SuppliedComputeRecord:
    """Project verified provenance into the unchanged #370 record contract."""
    serialize_provenance_verification(result)
    serialize_dispatch_decision(dispatch_decision)
    receipt = result.receipt
    if result.state != "verified" or receipt is None:
        raise ValueError("only verified provenance may project to compute evidence")
    if receipt.dispatch_decision_id != dispatch_decision.decision_id:
        raise ValueError("dispatch decision ID mismatch")
    return SuppliedComputeRecord(
        record_id=result.verification_id,
        dispatch_decision=dispatch_decision,
        remote_build_triggered=True,
        build_id=receipt.build_id,
        terminal_status=receipt.terminal_status,
        machine_type=receipt.machine_type,
        elapsed_seconds=receipt.elapsed_seconds,
    )


def serialize_provenance_verification(
    result: ProvenanceVerificationResult,
) -> dict[str, object]:
    if type(result) is not ProvenanceVerificationResult:
        raise TypeError("result must be ProvenanceVerificationResult")
    payload = _payload(result)
    expected = "provenance-verification:" + _digest(
        "agent-os-validation-provenance-verification:v1", payload
    )
    if result.verification_id != expected:
        raise ValueError("provenance verification ID mismatch")
    serialized = dict(payload, verification_id=result.verification_id)
    if len(_canonical(serialized)) > MAX_PROVENANCE_SERIALIZED_BYTES:
        raise ValueError("provenance verification exceeds canonical size limit")
    return serialized


def provenance_verification_id(result: ProvenanceVerificationResult) -> str:
    return str(serialize_provenance_verification(result)["verification_id"])


def _result(
    receipt: NormalizedVerificationReceipt | None,
    state: TrustState,
    reasons: set[str],
) -> ProvenanceVerificationResult:
    codes = tuple(sorted(reasons))
    if not codes or len(codes) > MAX_PROVENANCE_REASON_CODES:
        raise ValueError("reason codes outside bounded contract")
    preliminary = ProvenanceVerificationResult(
        schema_name=PROVENANCE_VERIFICATION_SCHEMA_NAME,
        schema_version=PROVENANCE_VERIFICATION_SCHEMA_VERSION,
        state=state,
        verification_id="",
        receipt=receipt,
        reason_codes=codes,
    )
    return replace(
        preliminary,
        verification_id="provenance-verification:"
        + _digest(
            "agent-os-validation-provenance-verification:v1", _payload(preliminary)
        ),
    )


def _plan_errors(plan: object) -> tuple[str, ...]:
    if type(plan) is not ValidationPlan:
        return ("plan.invalid-type",)
    errors = set(validate_validation_plan(plan))
    if not _match(_REPOSITORY, plan.repository):
        errors.add("plan.repository-boundary")
    return tuple(sorted(errors))


def _receipt_errors(receipt: NormalizedVerificationReceipt) -> set[str]:
    errors: set[str] = set()
    if receipt.schema_name != PROVENANCE_RECEIPT_SCHEMA_NAME:
        errors.add("receipt.schema-name")
    if receipt.schema_version != PROVENANCE_RECEIPT_SCHEMA_VERSION:
        errors.add("receipt.schema-version")
    identifiers = (
        "receipt_id",
        "trust_root_id",
        "verifier_id",
        "evidence_source",
        "producer_identity",
        "provider",
        "provider_account",
        "provider_location",
        "build_id",
        "trigger_identity",
        "replay_id",
        "profile",
        "selector_version",
    )
    for name in identifiers:
        if not _identifier(getattr(receipt, name)):
            errors.add(f"receipt.{name.replace('_', '-')}")
    checks = {
        "repository": _match(_REPOSITORY, receipt.repository),
        "pull-request": type(receipt.pull_request) is int and receipt.pull_request > 0,
        "tested-sha": _match(_SHA40, receipt.tested_sha),
        "command-set-digest": _match(_SHA256, receipt.command_set_digest),
        "plan-id": _match(_PLAN_ID, receipt.plan_id),
        "dispatch-decision-id": _match(_DECISION_ID, receipt.dispatch_decision_id),
        "proof-verified": type(receipt.proof_verified) is bool,
        "proof-digest": _match(_SHA256, receipt.proof_digest),
        "proof-type": type(receipt.proof_type) is str,
        "terminal-status": receipt.terminal_status in _TERMINAL,
        "machine-type": receipt.machine_type == "unavailable"
        or _safe(receipt.machine_type),
        "elapsed-seconds": receipt.elapsed_seconds is None
        or (type(receipt.elapsed_seconds) is int and receipt.elapsed_seconds >= 0),
    }
    for label, valid in checks.items():
        if not valid:
            errors.add(f"receipt.{label}")
    for name in ("evidence_created_at", "retrieved_at", "expires_at"):
        if _timestamp(getattr(receipt, name)) is None:
            errors.add(f"receipt.{name.replace('_', '-')}")
    return errors


def _compare(
    expected: dict[str, object],
    actual: dict[str, object],
    reasons: set[str],
    prefix: str,
) -> None:
    for key, value in expected.items():
        normalized = key.replace("_", "-")
        if actual.get(key) != value:
            reasons.add(f"{prefix}.{normalized}")


def _identifier_set(
    value: object,
    limit: int,
    *,
    allow_empty: bool = False,
) -> frozenset[str] | None:
    if type(value) is not tuple or len(value) > limit or (not value and not allow_empty):
        return None
    if len(set(value)) != len(value) or any(not _identifier(item) for item in value):
        return None
    return frozenset(value)


def _identifier(value: object) -> bool:
    return _safe(value, 256) and _match(_IDENTIFIER, value)


def _safe(value: object, limit: int = MAX_PROVENANCE_STRING_LENGTH) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= limit
        and not _CONTROL.search(value)
        and not _SECRET.search(value)
    )


def _match(pattern: re.Pattern[str], value: object) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _timestamp(value: object) -> datetime | None:
    if type(value) is not str or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def _receipt_payload(receipt: NormalizedVerificationReceipt | None) -> object:
    return None if receipt is None else asdict(receipt)


def _payload(result: ProvenanceVerificationResult) -> dict[str, object]:
    return {
        "schema_name": result.schema_name,
        "schema_version": result.schema_version,
        "state": result.state,
        "receipt": _receipt_payload(result.receipt),
        "reason_codes": list(result.reason_codes),
        "authoritative": result.authoritative,
        "execution_authorized": result.execution_authorized,
        "merge_authorized": result.merge_authorized,
        "side_effects_performed": result.side_effects_performed,
    }


def _digest(domain: str, payload: object) -> str:
    return hashlib.sha256(domain.encode() + b"\0" + _canonical(payload)).hexdigest()


def _canonical(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
