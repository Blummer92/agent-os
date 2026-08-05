"""Pure-local remote-validation evidence provenance verification.

Converts caller-normalized remote-validation evidence into a deterministic,
exact-identity verification result and a separate, non-authorizing
applicability projection. No network, credential, workflow-permission,
signature-generation, attestation-generation, filesystem, environment,
process, clock, or provider SDK access exists here; every value is supplied
by the caller and nothing is fabricated, inferred, retrieved, or persisted.

This module owns verification and evidence applicability only. It does not
retrieve provider evidence, dispatch or cancel builds, publish PR status,
estimate monetary cost, execute validation, or authorize execution or merge.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal

PROVENANCE_EVIDENCE_SCHEMA_NAME = "agent-os-remote-validation-evidence"
PROVENANCE_EVIDENCE_SCHEMA_VERSION = "1.0"
PROVENANCE_VERIFICATION_SCHEMA_NAME = "agent-os-remote-validation-provenance-verification"
PROVENANCE_VERIFICATION_SCHEMA_VERSION = "1.0"
PROVENANCE_APPLICABILITY_SCHEMA_NAME = "agent-os-remote-validation-evidence-applicability"
PROVENANCE_APPLICABILITY_SCHEMA_VERSION = "1.0"

MAX_PROVENANCE_STRING_LENGTH = 4096
MAX_PROVENANCE_EVIDENCE_ITEMS = 8
MAX_PROVENANCE_TRUST_ROOTS = 32
MAX_PROVENANCE_VERIFIERS = 32
MAX_PROVENANCE_SEEN_EVIDENCE_IDS = 64
MAX_PROVENANCE_REASON_CODES = 64
MAX_PROVENANCE_SERIALIZED_BYTES = 262_144

SourceType = Literal["provider-api", "signed-envelope", "attestation", "supplied-metadata"]
TerminalStatus = Literal["succeeded", "failed", "cancelled", "timed-out", "infrastructure-error"]
Disposition = Literal["NO-GO", "NEEDS-DECISION", "GO"]
TrustState = Literal["verified", "unverified", "stale", "identity-mismatch", "manual-review"]
ApplicabilityState = Literal[
    "fresh-and-applicable", "stale", "identity-mismatch", "expired", "incomplete", "manual-review"
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
_SOURCE_TYPES = frozenset({"provider-api", "signed-envelope", "attestation", "supplied-metadata"})
_TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed-out", "infrastructure-error"})
_NO_ENVELOPE_SOURCE_TYPES = frozenset({"supplied-metadata"})


class ProvenanceInputError(ValueError):
    """Raised when supplied provenance input cannot be represented safely."""


def _safe(value: object, limit: int = MAX_PROVENANCE_STRING_LENGTH) -> bool:
    return (
        type(value) is str and 0 < len(value) <= limit
        and not _CONTROL.search(value) and not _SECRET.search(value)
    )


def _match(pattern: re.Pattern[str], value: object) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _identifier(value: object) -> bool:
    return _safe(value, 256) and _match(_IDENTIFIER, value)


def _timestamp(value: object) -> datetime | None:
    if type(value) is not str or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def _require_identifier(name: str, value: object) -> None:
    if not _identifier(value):
        raise ProvenanceInputError(f"{name} must be a bounded, safe identifier")


def _require_timestamp(name: str, value: object) -> None:
    if _timestamp(value) is None:
        raise ProvenanceInputError(f"{name} must be an RFC3339 UTC timestamp ending in 'Z'")


@dataclass(frozen=True, slots=True, kw_only=True)
class NormalizedRemoteValidationEvidence:
    """Stage 1: one immutable, bounded, normalized remote-validation evidence record.

    Optional verified-envelope metadata (``verifier_id``, ``trust_root_id``,
    ``proof_verified``, ``proof_digest``) is present only when a separately
    approved adapter already established API, signature, or attestation
    verification; it must be entirely present or entirely absent, and is
    required whenever ``source_type`` is not ``supplied-metadata``.
    """

    schema_name: str
    schema_version: str
    evidence_id: str
    source_type: SourceType
    repository: str
    pull_request: int
    head_sha: str
    profile: str
    selector_version: str
    command_set_digest: str
    plan_id: str
    dispatch_decision_id: str
    build_id: str
    provider: str
    producer_identity: str
    trigger_identity: str
    terminal_status: TerminalStatus
    retrieved_at: str
    expires_at: str
    verifier_id: str | None = None
    trust_root_id: str | None = None
    proof_verified: bool | None = None
    proof_digest: str | None = None
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != PROVENANCE_EVIDENCE_SCHEMA_NAME:
            raise ProvenanceInputError("schema_name is unsupported")
        if self.schema_version != PROVENANCE_EVIDENCE_SCHEMA_VERSION:
            raise ProvenanceInputError("schema_version is unsupported")
        _require_identifier("evidence_id", self.evidence_id)
        if self.source_type not in _SOURCE_TYPES:
            raise ProvenanceInputError("source_type is unsupported")
        if not _match(_REPOSITORY, self.repository):
            raise ProvenanceInputError("repository must be owner/name")
        if (
            type(self.pull_request) is bool
            or type(self.pull_request) is not int
            or self.pull_request <= 0
        ):
            raise ProvenanceInputError("pull_request must be a positive int")
        if not _match(_SHA40, self.head_sha):
            raise ProvenanceInputError("head_sha must be a full 40-character lowercase SHA")
        _require_identifier("profile", self.profile)
        _require_identifier("selector_version", self.selector_version)
        if not _match(_SHA256, self.command_set_digest):
            raise ProvenanceInputError("command_set_digest must be a sha256 hex digest")
        if not _match(_PLAN_ID, self.plan_id):
            raise ProvenanceInputError("plan_id must match validation-plan:<sha256>")
        if not _match(_DECISION_ID, self.dispatch_decision_id):
            raise ProvenanceInputError(
                "dispatch_decision_id must match validation-dispatch-decision:<sha256>"
            )
        _require_identifier("build_id", self.build_id)
        _require_identifier("provider", self.provider)
        _require_identifier("producer_identity", self.producer_identity)
        _require_identifier("trigger_identity", self.trigger_identity)
        if self.terminal_status not in _TERMINAL:
            raise ProvenanceInputError("terminal_status is unsupported")
        _require_timestamp("retrieved_at", self.retrieved_at)
        _require_timestamp("expires_at", self.expires_at)
        retrieved, expires = _timestamp(self.retrieved_at), _timestamp(self.expires_at)
        if retrieved is not None and expires is not None and retrieved > expires:
            raise ProvenanceInputError("retrieved_at must not be after expires_at")

        envelope = (self.verifier_id, self.trust_root_id, self.proof_verified, self.proof_digest)
        envelope_present = tuple(item is not None for item in envelope)
        if any(envelope_present) and not all(envelope_present):
            raise ProvenanceInputError("verified-envelope metadata must be entirely present or absent")
        if self.source_type in _NO_ENVELOPE_SOURCE_TYPES and any(envelope_present):
            raise ProvenanceInputError("supplied-metadata evidence must not carry envelope proof")
        if self.source_type not in _NO_ENVELOPE_SOURCE_TYPES and not all(envelope_present):
            raise ProvenanceInputError(f"{self.source_type} evidence requires envelope proof")
        if all(envelope_present):
            _require_identifier("verifier_id", self.verifier_id)
            _require_identifier("trust_root_id", self.trust_root_id)
            if type(self.proof_verified) is not bool:
                raise ProvenanceInputError("proof_verified must be a bool")
            if not _match(_SHA256, self.proof_digest or ""):
                raise ProvenanceInputError("proof_digest must be a sha256 hex digest")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpectedEvidenceIdentity:
    """Caller-supplied exact identity the evaluated evidence must bind to."""

    repository: str
    pull_request: int
    head_sha: str
    plan_id: str
    dispatch_decision_id: str
    provider: str
    producer_identity: str
    trigger_identity: str
    build_id: str | None = None

    def __post_init__(self) -> None:
        if not _match(_REPOSITORY, self.repository):
            raise ProvenanceInputError("repository must be owner/name")
        if (
            type(self.pull_request) is bool
            or type(self.pull_request) is not int
            or self.pull_request <= 0
        ):
            raise ProvenanceInputError("pull_request must be a positive int")
        if not _match(_SHA40, self.head_sha):
            raise ProvenanceInputError("head_sha must be a full 40-character lowercase SHA")
        if not _match(_PLAN_ID, self.plan_id):
            raise ProvenanceInputError("plan_id must match validation-plan:<sha256>")
        if not _match(_DECISION_ID, self.dispatch_decision_id):
            raise ProvenanceInputError(
                "dispatch_decision_id must match validation-dispatch-decision:<sha256>"
            )
        _require_identifier("provider", self.provider)
        _require_identifier("producer_identity", self.producer_identity)
        _require_identifier("trigger_identity", self.trigger_identity)
        if self.build_id is not None:
            _require_identifier("build_id", self.build_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProvenanceVerificationResult:
    schema_name: str
    schema_version: str
    disposition: Disposition
    trust: TrustState
    verification_id: str
    evidence: NormalizedRemoteValidationEvidence | None
    reason_codes: tuple[str, ...]
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceApplicabilityProjection:
    """A non-authorizing evidence-freshness/completeness classification.

    This projection is an evidence classification only. It never authorizes
    skipping a required check, execution, merge, or required-check
    suppression; a separately governed consumer policy would have to grant
    that separately.
    """

    schema_name: str
    schema_version: str
    applicability: ApplicabilityState
    applicability_id: str
    reason_codes: tuple[str, ...]
    authorizes_check_skip: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def _identifier_set(value: object, limit: int, *, allow_empty: bool = False) -> frozenset[str] | None:
    if type(value) is not tuple or len(value) > limit or (not value and not allow_empty):
        return None
    if len(set(value)) != len(value) or any(not _identifier(item) for item in value):
        return None
    return frozenset(value)


def _evidence_items(value: object) -> tuple[NormalizedRemoteValidationEvidence, ...] | None:
    if type(value) is not tuple or len(value) > MAX_PROVENANCE_EVIDENCE_ITEMS:
        return None
    if any(type(item) is not NormalizedRemoteValidationEvidence for item in value):
        return None
    return value


def _resolve_batch(
    evidence: object,
    expected_identity: object,
    evaluation_time: object,
    seen_evidence_ids: object,
) -> tuple[
    NormalizedRemoteValidationEvidence | None,
    datetime | None,
    ExpectedEvidenceIdentity | None,
    frozenset[str] | None,
    set[str],
    set[str],
]:
    """Shared batch/identity/replay resolution used by both public entry points.

    Returns (single authoritative item or None, evaluated time, expected
    identity, seen-id set, no_go reason codes, needs_decision reason codes).
    Trust- or applicability-specific checks are layered on by the caller.
    """
    no_go: set[str] = set()
    needs_decision: set[str] = set()

    expected = expected_identity if type(expected_identity) is ExpectedEvidenceIdentity else None
    if expected is None:
        no_go.add("input-invalid")

    evaluated = _timestamp(evaluation_time)
    if evaluated is None:
        no_go.add("input-invalid")

    seen = _identifier_set(seen_evidence_ids, MAX_PROVENANCE_SEEN_EVIDENCE_IDS, allow_empty=True)
    if seen is None:
        no_go.add("input-invalid")
        seen = frozenset()

    items = _evidence_items(evidence)
    if items is None:
        no_go.add("input-invalid")
        return None, evaluated, expected, seen, no_go, needs_decision

    if not items:
        needs_decision.add("evidence-empty")
        return None, evaluated, expected, seen, no_go, needs_decision

    if len(items) > 1:
        ids = [item.evidence_id for item in items]
        if len(set(ids)) != len(ids):
            no_go.add("input-invalid")
            return None, evaluated, expected, seen, no_go, needs_decision
        keys = {(item.repository, item.pull_request, item.head_sha, item.provider) for item in items}
        if len(keys) > 1:
            no_go.add("evidence-contradictory")
        else:
            needs_decision.add("manual-review-required")
        return None, evaluated, expected, seen, no_go, needs_decision

    single = items[0]
    if single.evidence_id in seen:
        no_go.add("evidence-replayed")

    if expected is not None:
        checks = (
            ("repository", single.repository, expected.repository, "repository-mismatch"),
            ("pull_request", single.pull_request, expected.pull_request, "pull-request-mismatch"),
            ("plan_id", single.plan_id, expected.plan_id, "plan-mismatch"),
            (
                "dispatch_decision_id",
                single.dispatch_decision_id,
                expected.dispatch_decision_id,
                "dispatch-mismatch",
            ),
            ("provider", single.provider, expected.provider, "provider-mismatch"),
            (
                "producer_identity",
                single.producer_identity,
                expected.producer_identity,
                "signer-mismatch",
            ),
            ("trigger_identity", single.trigger_identity, expected.trigger_identity, "trigger-mismatch"),
        )
        for _, actual, wanted, code in checks:
            if actual != wanted:
                no_go.add(code)
        if expected.build_id is not None and single.build_id != expected.build_id:
            no_go.add("build-mismatch")

        # A head-SHA difference is only meaningful once every other identity
        # dimension binds correctly; otherwise it is subsumed by the mismatch
        # above rather than reported as a second, independent finding.
        if not no_go and single.head_sha != expected.head_sha:
            no_go.add("head-sha-mismatch")

    return single, evaluated, expected, seen, no_go, needs_decision


def verify_remote_validation_provenance(
    evidence: object,
    *,
    expected_identity: object,
    approved_trust_roots: object,
    approved_verifiers: object,
    evaluation_time: object,
    seen_evidence_ids: object = (),
    schema_version: object = PROVENANCE_VERIFICATION_SCHEMA_VERSION,
) -> ProvenanceVerificationResult:
    """Stage 2: verify one bounded batch of normalized remote-validation evidence.

    Consumes only normalized input and returns one immutable, deterministic
    result with a disposition (``NO-GO`` > ``NEEDS-DECISION`` > ``GO``, most
    severe first) and a public trust state. ``verified`` trust -- and
    therefore ``GO`` -- requires exact identity binding plus a supplied,
    approved trusted-producer verification result; ordinary metadata alone
    can never exceed ``unverified``.
    """
    no_go: set[str] = set()
    needs_decision: set[str] = set()
    trust: set[TrustState] = set()

    if schema_version != PROVENANCE_VERIFICATION_SCHEMA_VERSION:
        needs_decision.add("unsupported-version")
        trust.add("manual-review")

    single, evaluated, _expected, _seen, batch_no_go, batch_needs_decision = _resolve_batch(
        evidence, expected_identity, evaluation_time, seen_evidence_ids
    )
    no_go |= batch_no_go
    needs_decision |= batch_needs_decision
    if batch_no_go & {"evidence-contradictory", "evidence-replayed"} or "input-invalid" in batch_no_go:
        trust.add("manual-review")
    if batch_no_go - {"evidence-contradictory", "evidence-replayed", "input-invalid"}:
        trust.add("identity-mismatch")
    if batch_needs_decision:
        trust.add("unverified" if "evidence-empty" in batch_needs_decision else "manual-review")

    if single is not None and not no_go:
        roots = _identifier_set(approved_trust_roots, MAX_PROVENANCE_TRUST_ROOTS)
        verifiers = _identifier_set(approved_verifiers, MAX_PROVENANCE_VERIFIERS)
        if roots is None or verifiers is None:
            no_go.add("input-invalid")
            trust.add("manual-review")
        else:
            retrieved = _timestamp(single.retrieved_at)
            expires = _timestamp(single.expires_at)
            if evaluated is not None and retrieved is not None and evaluated < retrieved:
                no_go.add("evidence-stale")
                trust.add("stale")
            if evaluated is not None and expires is not None and evaluated > expires:
                no_go.add("evidence-expired")
                trust.add("stale")

            if single.source_type in _NO_ENVELOPE_SOURCE_TYPES:
                needs_decision.add("producer-unverified")
                trust.add("unverified")
            else:
                if single.proof_verified is not True:
                    needs_decision.add("signature-unverified")
                    trust.add("unverified")
                elif single.trust_root_id not in roots or single.verifier_id not in verifiers:
                    needs_decision.add("producer-unverified")
                    trust.add("unverified")
                elif not needs_decision and not no_go:
                    trust.add("verified")

    disposition: Disposition = "NO-GO" if no_go else "NEEDS-DECISION" if needs_decision else "GO"
    for candidate in ("manual-review", "identity-mismatch", "stale", "unverified", "verified"):
        if candidate in trust:
            resolved_trust: TrustState = candidate  # type: ignore[assignment]
            break
    else:
        resolved_trust = "verified"

    codes = no_go | needs_decision or {"evidence-verified"}
    reasons = tuple(sorted(codes))
    return _verification_result(single, disposition, resolved_trust, reasons)


def project_evidence_applicability(
    evidence: object,
    *,
    expected_identity: object,
    evaluation_time: object,
    seen_evidence_ids: object = (),
) -> EvidenceApplicabilityProjection:
    """Classify supplied evidence as fresh, stale, expired, or incomplete.

    This is an evidence classification only. It never authorizes skipping a
    required check, execution, merge, or required-check suppression --
    ``authorizes_check_skip`` is fixed ``False``. A separately governed
    consumer policy is the only thing that can turn applicability into reuse.
    """
    no_go: set[str] = set()
    needs_decision: set[str] = set()
    applicability: set[ApplicabilityState] = set()

    single, evaluated, _expected, _seen, batch_no_go, batch_needs_decision = _resolve_batch(
        evidence, expected_identity, evaluation_time, seen_evidence_ids
    )
    no_go |= batch_no_go
    needs_decision |= batch_needs_decision
    if batch_no_go & {"evidence-contradictory", "evidence-replayed"} or "input-invalid" in batch_no_go:
        applicability.add("manual-review")
    if batch_no_go - {"evidence-contradictory", "evidence-replayed", "input-invalid"}:
        applicability.add("identity-mismatch")
    if batch_needs_decision:
        applicability.add("incomplete" if "evidence-empty" in batch_needs_decision else "manual-review")

    if single is not None and not no_go:
        retrieved = _timestamp(single.retrieved_at)
        expires = _timestamp(single.expires_at)
        if evaluated is not None and retrieved is not None and evaluated < retrieved:
            no_go.add("evidence-stale")
            applicability.add("stale")
        if evaluated is not None and expires is not None and evaluated > expires:
            no_go.add("evidence-expired")
            applicability.add("expired")
        if single.source_type in _NO_ENVELOPE_SOURCE_TYPES:
            needs_decision.add("evidence-incomplete")
            applicability.add("incomplete")
        elif not needs_decision and not no_go:
            applicability.add("fresh-and-applicable")

    for candidate in ("manual-review", "identity-mismatch", "expired", "stale", "incomplete"):
        if candidate in applicability:
            resolved: ApplicabilityState = candidate  # type: ignore[assignment]
            break
    else:
        resolved = "fresh-and-applicable"

    codes = no_go | needs_decision or {"evidence-fresh-and-applicable"}
    reasons = tuple(sorted(codes))
    return _applicability_result(resolved, reasons)


def _verification_result(
    evidence: NormalizedRemoteValidationEvidence | None,
    disposition: Disposition,
    trust: TrustState,
    reasons: tuple[str, ...],
) -> ProvenanceVerificationResult:
    if not reasons or len(reasons) > MAX_PROVENANCE_REASON_CODES:
        raise ProvenanceInputError("reason codes outside bounded contract")
    payload = {
        "schema_name": PROVENANCE_VERIFICATION_SCHEMA_NAME,
        "schema_version": PROVENANCE_VERIFICATION_SCHEMA_VERSION,
        "disposition": disposition,
        "trust": trust,
        "evidence": None if evidence is None else asdict(evidence),
        "reason_codes": list(reasons),
        "authoritative": False,
        "execution_authorized": False,
        "merge_authorized": False,
        "side_effects_performed": False,
    }
    verification_id = "provenance-verification:" + _digest(
        "agent-os-remote-validation-provenance-verification:v1", payload
    )
    return ProvenanceVerificationResult(
        schema_name=PROVENANCE_VERIFICATION_SCHEMA_NAME,
        schema_version=PROVENANCE_VERIFICATION_SCHEMA_VERSION,
        disposition=disposition,
        trust=trust,
        verification_id=verification_id,
        evidence=evidence,
        reason_codes=reasons,
    )


def _applicability_result(
    applicability: ApplicabilityState, reasons: tuple[str, ...]
) -> EvidenceApplicabilityProjection:
    if not reasons or len(reasons) > MAX_PROVENANCE_REASON_CODES:
        raise ProvenanceInputError("reason codes outside bounded contract")
    payload = {
        "schema_name": PROVENANCE_APPLICABILITY_SCHEMA_NAME,
        "schema_version": PROVENANCE_APPLICABILITY_SCHEMA_VERSION,
        "applicability": applicability,
        "reason_codes": list(reasons),
        "authorizes_check_skip": False,
        "execution_authorized": False,
        "side_effects_performed": False,
    }
    applicability_id = "evidence-applicability:" + _digest(
        "agent-os-remote-validation-evidence-applicability:v1", payload
    )
    return EvidenceApplicabilityProjection(
        schema_name=PROVENANCE_APPLICABILITY_SCHEMA_NAME,
        schema_version=PROVENANCE_APPLICABILITY_SCHEMA_VERSION,
        applicability=applicability,
        applicability_id=applicability_id,
        reason_codes=reasons,
    )


def serialize_provenance_verification(result: ProvenanceVerificationResult) -> dict[str, object]:
    if type(result) is not ProvenanceVerificationResult:
        raise TypeError("result must be ProvenanceVerificationResult")
    payload = {
        "schema_name": result.schema_name,
        "schema_version": result.schema_version,
        "disposition": result.disposition,
        "trust": result.trust,
        "evidence": None if result.evidence is None else asdict(result.evidence),
        "reason_codes": list(result.reason_codes),
        "authoritative": result.authoritative,
        "execution_authorized": result.execution_authorized,
        "merge_authorized": result.merge_authorized,
        "side_effects_performed": result.side_effects_performed,
    }
    expected = "provenance-verification:" + _digest(
        "agent-os-remote-validation-provenance-verification:v1", payload
    )
    if result.verification_id != expected:
        raise ValueError("provenance verification ID mismatch")
    serialized = dict(payload, verification_id=result.verification_id)
    if len(_canonical(serialized)) > MAX_PROVENANCE_SERIALIZED_BYTES:
        raise ValueError("provenance verification exceeds canonical size limit")
    return serialized


def serialize_evidence_applicability(projection: EvidenceApplicabilityProjection) -> dict[str, object]:
    if type(projection) is not EvidenceApplicabilityProjection:
        raise TypeError("projection must be EvidenceApplicabilityProjection")
    payload = {
        "schema_name": projection.schema_name,
        "schema_version": projection.schema_version,
        "applicability": projection.applicability,
        "reason_codes": list(projection.reason_codes),
        "authorizes_check_skip": projection.authorizes_check_skip,
        "execution_authorized": projection.execution_authorized,
        "side_effects_performed": projection.side_effects_performed,
    }
    expected = "evidence-applicability:" + _digest(
        "agent-os-remote-validation-evidence-applicability:v1", payload
    )
    if projection.applicability_id != expected:
        raise ValueError("evidence applicability ID mismatch")
    serialized = dict(payload, applicability_id=projection.applicability_id)
    if len(_canonical(serialized)) > MAX_PROVENANCE_SERIALIZED_BYTES:
        raise ValueError("evidence applicability exceeds canonical size limit")
    return serialized


def provenance_verification_id(result: ProvenanceVerificationResult) -> str:
    return str(serialize_provenance_verification(result)["verification_id"])


def evidence_applicability_id(projection: EvidenceApplicabilityProjection) -> str:
    return str(serialize_evidence_applicability(projection)["applicability_id"])


def _digest(domain: str, payload: object) -> str:
    return hashlib.sha256(domain.encode() + b"\0" + _canonical(payload)).hexdigest()


def _canonical(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
