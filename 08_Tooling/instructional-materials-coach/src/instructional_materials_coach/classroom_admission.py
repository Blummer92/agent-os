"""Classroom-ready admission predicate for canonical IMC build receipts (#3259 D8, #3556).

D8 (approved in principle): a classroom-ready claim requires a positive
admission decision computed from COMPLETE canonical build evidence. Direct
ChatGPT/DOCX/PDF output is non-authoritative: it bypasses the governed
Notion -> Agent OS -> Drive production path and carries no canonical build
receipt, so it can never be admitted by the repository.

This module is a pure decision function in the established seam pattern
(#2761 ``MainHealthAdmission``). It consumes:

- one build receipt mapping as produced by
  ``build_receipt.build_receipt_record`` (contract
  ``imc-build-receipt-v1``) — treated as UNTRUSTED input, never as proof;
- one :class:`ClassroomAdmissionEvidence` bundle the caller assembles from
  canonical sources (governed requirement identity, template revisions,
  terminal-QA reports, the verified placement-receipt store) — the trusted
  reference every receipt claim is re-derived against.

It never performs network or filesystem I/O, never trusts the receipt's
``authority`` block or any caller-provided authority claim (including a
forged ``classroom_ready: true``), never grants execution / production /
publication / classroom authority, and never mutates its inputs. A
``NOT_ADMITTED`` verdict is terminal for the admission question.

The predicate cannot prove artifact bytes: it evaluates the canonical QA
and placement evidence referenced by the record, not the bytes themselves.
Admission is therefore evidence evaluation, never standalone authenticity
proof — enforcement on the native ChatGPT/DOCX/PDF route stays host-side
(#3385).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Any, Iterable, Literal, Mapping

from .build_receipt import BUILD_RECEIPT_CONTRACT

CLASSROOM_ADMISSION_SCHEMA_NAME = "agent-os-classroom-admission"
CLASSROOM_ADMISSION_SCHEMA_VERSION = "2.0"

TERMINAL_QA_VERIFIED = "verified"
PLACEMENT_RECEIPT_CONTRACT = "visual-placement-receipt-v1"
PLACEMENT_STATE_VERIFIED = "verified"

_REQUIREMENT_FIELDS = ("requirement_id", "contract_version", "record_revision", "source_fingerprint")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class ClassroomAdmission(str, Enum):
    """Whether the complete canonical evidence admits classroom-ready."""

    #: Every evidence condition re-derived from canonical sources holds.
    #: The evidence admits classroom-ready; no authority is granted by this
    #: verdict — downstream governors still own authorization.
    ADMITTED = "admitted"
    #: One or more evidence conditions failed, or the receipt/evidence was
    #: malformed. Fail-closed: the caller must not treat the artifact as
    #: classroom-ready.
    NOT_ADMITTED = "not-admitted"


class ClassroomAdmissionReason(str, Enum):
    """Finite reason codes explaining one deterministic classification."""

    #: All complete-evidence conditions hold.
    EVIDENCE_COMPLETE = "classroom.evidence-complete"
    #: The receipt is not a mapping, or a required evidence field has an
    #: unexpected type. Fail-closed on malformed input.
    RECEIPT_MALFORMED = "classroom.receipt-malformed"
    #: No canonical evidence bundle was supplied (or it has the wrong type).
    #: Without canonical evidence nothing can be re-derived: fail closed.
    EVIDENCE_MISSING = "classroom.evidence-missing"
    #: ``contract_version`` is missing or is not ``imc-build-receipt-v1``.
    CONTRACT_VERSION_MISMATCH = "classroom.contract-version-mismatch"
    #: The receipt idempotency key is missing, empty, or differs from the
    #: canonical evidence: stale or cross-build evidence. Fail closed.
    IDEMPOTENCY_KEY_MISMATCH = "classroom.idempotency-key-mismatch"
    #: A requirement-identity field (requirement_id, contract_version,
    #: record_revision, source_fingerprint) is missing or empty.
    REQUIREMENT_IDENTITY_INCOMPLETE = "classroom.requirement-identity-incomplete"
    #: The receipt's requirement identity differs from the canonical
    #: requirement identity (wrong task/requirement or tampered record).
    REQUIREMENT_IDENTITY_MISMATCH = "classroom.requirement-identity-mismatch"
    #: A template file ID or revision is missing, empty, stale, or differs
    #: from the canonical template identity.
    TEMPLATE_IDENTITY_MISMATCH = "classroom.template-identity-mismatch"
    #: An artifact file ID or revision is missing, empty, stale, or differs
    #: from the canonical artifact identity.
    ARTIFACT_IDENTITY_MISMATCH = "classroom.artifact-identity-mismatch"
    #: The canonical build did not succeed, or the receipt's ``succeeded``
    #: flag disagrees with the canonical outcome (tampered record).
    BUILD_NOT_SUCCEEDED = "classroom.build-not-succeeded"
    #: A requested artifact's ``requested_format.complete`` is missing or is
    #: not exactly ``True``.
    REQUESTED_FORMAT_INCOMPLETE = "classroom.requested-format-incomplete"
    #: Terminal QA is not ``verified`` for a requested artifact — missing,
    #: stale, failed, preview, or disagreeing with the canonical QA state.
    TERMINAL_QA_NOT_VERIFIED = "classroom.terminal-qa-not-verified"
    #: A required visual has no verified placement receipt at all.
    PLACEMENT_RECEIPT_MISSING = "classroom.placement-receipt-missing"
    #: Placement records exist for the slot but none carries the required
    #: visual's role: roles are instructional-semantic identities, and a
    #: record placed for a different role never satisfies the requirement.
    SEMANTIC_ROLE_MISMATCH = "classroom.semantic-role-mismatch"
    #: A role-matching placement record disagrees on asset, content
    #: identity, artifact binding, or the receipt's placement references
    #: (stale revision or tampered evidence).
    PLACEMENT_EVIDENCE_MISMATCH = "classroom.placement-evidence-mismatch"
    #: Multiple verified placement records for one required visual carry
    #: conflicting content identities: conflicting evidence. Fail closed.
    PLACEMENT_EVIDENCE_CONFLICT = "classroom.placement-evidence-conflict"


@dataclass(frozen=True, slots=True)
class RequiredVisual:
    """One required visual role the canonical evidence declares."""

    role_id: str
    slot_id: str
    asset_id: str
    #: Canonical JSON of the exact content identity the placement must carry.
    content_identity_json: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class TemplateIdentity:
    key: str
    file_id: str
    revision_id: str


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    role: str
    file_id: str
    revision_id: str


@dataclass(frozen=True, slots=True)
class ArtifactQAState:
    role: str
    qa_state: str


@dataclass(frozen=True, slots=True)
class ClassroomAdmissionEvidence:
    """Canonical evidence the caller assembles; the receipt is checked against it.

    Every field is the caller's canonical value (governed inputs, terminal-QA
    reports, verified placement-receipt store) — never copied from the
    receipt under evaluation. Content checks (non-empty, agreement) belong
    to the predicate; this bundle only enforces exact types.
    """

    idempotency_key: str
    requirement_id: str
    requirement_contract_version: str
    requirement_record_revision: str
    requirement_source_fingerprint: str
    template_identities: tuple[TemplateIdentity, ...]
    artifact_identities: tuple[ArtifactIdentity, ...]
    requested_artifact_roles: tuple[str, ...]
    terminal_qa_states: tuple[ArtifactQAState, ...]
    build_succeeded: bool
    placement_records: tuple[Mapping[str, Any], ...]
    required_visuals: tuple[RequiredVisual, ...]

    def __post_init__(self) -> None:
        if type(self.idempotency_key) is not str:
            raise TypeError("idempotency_key must be str")
        for name in (
            "requirement_id",
            "requirement_contract_version",
            "requirement_record_revision",
            "requirement_source_fingerprint",
        ):
            if type(getattr(self, name)) is not str:
                raise TypeError(f"{name} must be str")
        if type(self.template_identities) is not tuple or not all(
            type(item) is TemplateIdentity for item in self.template_identities
        ):
            raise TypeError("template_identities must be a tuple of TemplateIdentity")
        if type(self.artifact_identities) is not tuple or not all(
            type(item) is ArtifactIdentity for item in self.artifact_identities
        ):
            raise TypeError("artifact_identities must be a tuple of ArtifactIdentity")
        if type(self.requested_artifact_roles) is not tuple or not all(
            type(role) is str for role in self.requested_artifact_roles
        ):
            raise TypeError("requested_artifact_roles must be a tuple of str")
        if type(self.terminal_qa_states) is not tuple or not all(
            type(item) is ArtifactQAState for item in self.terminal_qa_states
        ):
            raise TypeError("terminal_qa_states must be a tuple of ArtifactQAState")
        if type(self.build_succeeded) is not bool:
            raise TypeError("build_succeeded must be bool")
        if type(self.placement_records) is not tuple or not all(
            isinstance(item, Mapping) for item in self.placement_records
        ):
            raise TypeError("placement_records must be a tuple of mappings")
        if type(self.required_visuals) is not tuple or not all(
            type(item) is RequiredVisual for item in self.required_visuals
        ):
            raise TypeError("required_visuals must be a tuple of RequiredVisual")


def assemble_admission_evidence(
    *,
    idempotency_key: str,
    requirement_identity: Mapping[str, Any],
    template_identities: Iterable[tuple[str, Any, Any]],
    artifact_identities: Iterable[tuple[str, Any, Any]],
    requested_artifact_roles: Iterable[str],
    terminal_qa_states: Iterable[tuple[str, Any]],
    build_succeeded: bool,
    placement_records: Iterable[Mapping[str, Any]],
    required_visuals: Iterable[RequiredVisual | Mapping[str, Any]],
) -> ClassroomAdmissionEvidence:
    """Assemble the canonical evidence bundle from caller-owned values.

    Pure: no I/O. The caller extracts these values from canonical sources
    (governed requirement snapshot, template revisions, terminal-QA reports,
    the verified placement-receipt store); this helper only normalizes them
    into the frozen bundle. Raises ``TypeError``/``ValueError`` on malformed
    input — callers that cannot assemble evidence must classify with
    ``evidence=None`` (fail-closed) instead of inventing values.
    """
    if not isinstance(requirement_identity, Mapping):
        raise TypeError("requirement_identity must be a mapping")

    def _req_field(name: str) -> str:
        value = requirement_identity.get(name)
        if type(value) is not str:
            raise TypeError(f"requirement_identity[{name!r}] must be str")
        return value

    templates = tuple(
        TemplateIdentity(key=str(key), file_id=str(file_id), revision_id=str(revision_id))
        for key, file_id, revision_id in template_identities
    )
    artifacts = tuple(
        ArtifactIdentity(role=str(role), file_id=str(file_id), revision_id=str(revision_id))
        for role, file_id, revision_id in artifact_identities
    )
    visuals: list[RequiredVisual] = []
    for visual in required_visuals:
        if isinstance(visual, RequiredVisual):
            visuals.append(visual)
            continue
        if not isinstance(visual, Mapping):
            raise TypeError("required_visuals entries must be RequiredVisual or mappings")
        content_identity = visual.get("content_identity")
        visuals.append(
            RequiredVisual(
                role_id=str(visual.get("role_id")),
                slot_id=str(visual.get("slot_id")),
                asset_id=str(visual.get("asset_id")),
                content_identity_json=_canonical_json(content_identity),
                required=bool(visual.get("required", True)),
            )
        )
    return ClassroomAdmissionEvidence(
        idempotency_key=str(idempotency_key),
        requirement_id=_req_field("requirement_id"),
        requirement_contract_version=_req_field("contract_version"),
        requirement_record_revision=_req_field("record_revision"),
        requirement_source_fingerprint=_req_field("source_fingerprint"),
        template_identities=templates,
        artifact_identities=artifacts,
        requested_artifact_roles=tuple(str(role) for role in requested_artifact_roles),
        terminal_qa_states=tuple(
            ArtifactQAState(role=str(role), qa_state=str(qa_state))
            for role, qa_state in terminal_qa_states
        ),
        build_succeeded=bool(build_succeeded),
        placement_records=tuple(dict(record) for record in placement_records),
        required_visuals=tuple(visuals),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ClassroomAdmissionResult:
    schema_name: str = CLASSROOM_ADMISSION_SCHEMA_NAME
    schema_version: str = CLASSROOM_ADMISSION_SCHEMA_VERSION
    status: ClassroomAdmission = ClassroomAdmission.NOT_ADMITTED
    result_id: str = ""
    reason_codes: tuple[ClassroomAdmissionReason, ...] = ()
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    production_authorized: Literal[False] = field(default=False, init=False)
    classroom_ready_granted: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != CLASSROOM_ADMISSION_SCHEMA_NAME:
            raise ValueError("unsupported classroom admission schema name")
        if self.schema_version != CLASSROOM_ADMISSION_SCHEMA_VERSION:
            raise ValueError("unsupported classroom admission schema version")
        if type(self.status) is not ClassroomAdmission:
            raise TypeError("status must be an exact ClassroomAdmission")
        if type(self.result_id) is not str or not self.result_id.startswith(
            "classroom-admission:"
        ):
            raise ValueError("result_id must carry the classroom-admission prefix")
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise ValueError("reason_codes must be a non-empty exact tuple")
        if any(type(item) is not ClassroomAdmissionReason for item in self.reason_codes):
            raise TypeError("reason_codes contain an invalid value")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes must be unique")
        if tuple(sorted(item.value for item in self.reason_codes)) != tuple(
            item.value for item in self.reason_codes
        ):
            raise ValueError("reason_codes must be sorted")


def _result(
    status: ClassroomAdmission,
    reason_codes: tuple[ClassroomAdmissionReason, ...],
) -> ClassroomAdmissionResult:
    digest = sha256(
        (
            "agent-os-classroom-admission:v2\0"
            f"{status.value}\0" + ",".join(sorted(reason.value for reason in reason_codes))
        ).encode("utf-8")
    ).hexdigest()
    return ClassroomAdmissionResult(
        status=status,
        result_id=f"classroom-admission:{digest}",
        reason_codes=tuple(sorted(reason_codes, key=lambda reason: reason.value)),
    )


def _validate_placement_evidence(
    receipt: Mapping[str, Any],
    evidence: ClassroomAdmissionEvidence,
) -> list[ClassroomAdmissionReason]:
    """Check every required visual against verified placement receipts."""
    failures: list[ClassroomAdmissionReason] = []
    references = receipt.get("placement_receipt_references")
    reference_list = references if isinstance(references, list) else []
    artifact_file_ids = {
        identity.file_id for identity in evidence.artifact_identities if identity.file_id
    }
    for required in evidence.required_visuals:
        if not required.required:
            continue
        slot = str(required.slot_id)
        slot_records = [
            record
            for record in evidence.placement_records
            if record.get("state") == PLACEMENT_STATE_VERIFIED
            and record.get("contract_version") == PLACEMENT_RECEIPT_CONTRACT
            and str(record.get("slot_id")) == slot
            and record.get("idempotency_key") == evidence.idempotency_key
        ]
        if not slot_records:
            failures.append(ClassroomAdmissionReason.PLACEMENT_RECEIPT_MISSING)
            continue
        # Semantic-role compatibility: the record's role must be the
        # required role. A record placed for a different role never
        # satisfies the requirement, even for the same slot and asset.
        role_records = [
            record for record in slot_records if record.get("role_id") == required.role_id
        ]
        if not role_records:
            failures.append(ClassroomAdmissionReason.SEMANTIC_ROLE_MISMATCH)
            continue
        identities = {
            (_canonical_json(record.get("content_identity")), record.get("asset_id"))
            for record in role_records
        }
        if len(identities) > 1:
            failures.append(ClassroomAdmissionReason.PLACEMENT_EVIDENCE_CONFLICT)
            continue
        record = role_records[0]
        if (
            record.get("asset_id") != required.asset_id
            or _canonical_json(record.get("content_identity"))
            != required.content_identity_json
            or not record.get("artifact_id")
            or record.get("artifact_id") not in artifact_file_ids
        ):
            failures.append(ClassroomAdmissionReason.PLACEMENT_EVIDENCE_MISMATCH)
            continue
        if not any(
            isinstance(reference, Mapping)
            and reference.get("role_id") == required.role_id
            and str(reference.get("slot_id")) == slot
            and reference.get("asset_id") == required.asset_id
            for reference in reference_list
        ):
            failures.append(ClassroomAdmissionReason.PLACEMENT_EVIDENCE_MISMATCH)
    return failures


def classify_classroom_admission(
    receipt: Mapping[str, Any],
    evidence: ClassroomAdmissionEvidence | None = None,
) -> ClassroomAdmissionResult:
    """Decide classroom-ready admission from a receipt plus canonical evidence.

    The receipt is untrusted input: every claim it makes is re-derived
    against the canonical ``evidence`` bundle. The receipt's ``authority``
    block is deliberately never read — caller authority claims (including a
    forged ``classroom_ready: true``) cannot influence admission.

    Admission requires ALL of the following, re-derived from canonical
    evidence:

    - ``contract_version == "imc-build-receipt-v1"``;
    - the receipt idempotency key equals the canonical key;
    - complete requirement identity (requirement_id, contract_version,
      record_revision, source_fingerprint), equal to the canonical identity;
    - template file IDs and revisions equal to the canonical identities;
    - artifact file IDs and revisions equal to the canonical identities;
    - the canonical build succeeded and the receipt agrees;
    - ``requested_format.complete is True`` for every requested artifact;
    - canonical terminal QA is ``verified`` for every requested artifact
      and the receipt agrees, including the top-level QA state;
    - every required visual has a verified placement receipt with matching
      role_id (semantic-role compatibility), slot_id, asset_id, content
      identity, artifact binding, and receipt reference;
    - no stale or conflicting evidence.

    Fail-closed: malformed receipts, missing evidence, missing fields, wrong
    types, or any single failed condition yields ``NOT_ADMITTED`` with the
    specific reason codes. Inputs are never mutated. The verdict grants no
    authority of any kind.
    """
    if not isinstance(receipt, Mapping):
        return _result(
            ClassroomAdmission.NOT_ADMITTED,
            (ClassroomAdmissionReason.RECEIPT_MALFORMED,),
        )
    if not isinstance(evidence, ClassroomAdmissionEvidence):
        return _result(
            ClassroomAdmission.NOT_ADMITTED,
            (ClassroomAdmissionReason.EVIDENCE_MISSING,),
        )

    failures: list[ClassroomAdmissionReason] = []

    contract_version = receipt.get("contract_version")
    if type(contract_version) is not str or contract_version != BUILD_RECEIPT_CONTRACT:
        failures.append(ClassroomAdmissionReason.CONTRACT_VERSION_MISMATCH)

    idempotency_key = receipt.get("idempotency_key")
    if (
        type(idempotency_key) is not str
        or not idempotency_key
        or idempotency_key != evidence.idempotency_key
    ):
        failures.append(ClassroomAdmissionReason.IDEMPOTENCY_KEY_MISMATCH)

    requirement = receipt.get("requirement_identity")
    if not isinstance(requirement, Mapping):
        failures.append(ClassroomAdmissionReason.REQUIREMENT_IDENTITY_INCOMPLETE)
    else:
        values = [requirement.get(name) for name in _REQUIREMENT_FIELDS]
        if any(type(value) is not str or not value for value in values):
            failures.append(ClassroomAdmissionReason.REQUIREMENT_IDENTITY_INCOMPLETE)
        elif tuple(values) != (
            evidence.requirement_id,
            evidence.requirement_contract_version,
            evidence.requirement_record_revision,
            evidence.requirement_source_fingerprint,
        ):
            failures.append(ClassroomAdmissionReason.REQUIREMENT_IDENTITY_MISMATCH)

    templates = receipt.get("templates")
    if not isinstance(templates, Mapping):
        failures.append(ClassroomAdmissionReason.TEMPLATE_IDENTITY_MISMATCH)
    else:
        for identity in evidence.template_identities:
            entry = templates.get(identity.key)
            if (
                not isinstance(entry, Mapping)
                or type(entry.get("file_id")) is not str
                or not entry.get("file_id")
                or entry.get("file_id") != identity.file_id
                or type(entry.get("revision_id")) is not str
                or not entry.get("revision_id")
                or entry.get("revision_id") != identity.revision_id
            ):
                failures.append(ClassroomAdmissionReason.TEMPLATE_IDENTITY_MISMATCH)
                break

    if evidence.build_succeeded is not True or receipt.get("succeeded") is not True:
        failures.append(ClassroomAdmissionReason.BUILD_NOT_SUCCEEDED)

    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, Mapping):
        failures.append(ClassroomAdmissionReason.ARTIFACT_IDENTITY_MISMATCH)
    else:
        for identity in evidence.artifact_identities:
            entry = artifacts.get(identity.role)
            if (
                not isinstance(entry, Mapping)
                or not identity.file_id
                or entry.get("file_id") != identity.file_id
                or not identity.revision_id
                or entry.get("revision_id") != identity.revision_id
            ):
                failures.append(ClassroomAdmissionReason.ARTIFACT_IDENTITY_MISMATCH)
                break
        for role in evidence.requested_artifact_roles:
            entry = artifacts.get(role)
            requested_format = (
                entry.get("requested_format") if isinstance(entry, Mapping) else None
            )
            if (
                not isinstance(requested_format, Mapping)
                or requested_format.get("complete") is not True
            ):
                failures.append(ClassroomAdmissionReason.REQUESTED_FORMAT_INCOMPLETE)
                break
        canonical_qa = {state.role: state.qa_state for state in evidence.terminal_qa_states}
        for role in evidence.requested_artifact_roles:
            entry = artifacts.get(role)
            canonical_state = canonical_qa.get(role)
            if canonical_state != TERMINAL_QA_VERIFIED:
                failures.append(ClassroomAdmissionReason.TERMINAL_QA_NOT_VERIFIED)
                break
            if not isinstance(entry, Mapping) or entry.get("terminal_qa_state") != canonical_state:
                failures.append(ClassroomAdmissionReason.TERMINAL_QA_NOT_VERIFIED)
                break
        if receipt.get("terminal_qa_state") != TERMINAL_QA_VERIFIED:
            failures.append(ClassroomAdmissionReason.TERMINAL_QA_NOT_VERIFIED)

    failures.extend(_validate_placement_evidence(receipt, evidence))

    # Dedupe while preserving deterministic first-seen order: independent
    # checks may name the same failure (e.g. per-artifact and top-level
    # terminal-QA checks); the result contract requires unique codes.
    unique_failures: list[ClassroomAdmissionReason] = []
    for failure in failures:
        if failure not in unique_failures:
            unique_failures.append(failure)
    failures = unique_failures

    if failures:
        return _result(ClassroomAdmission.NOT_ADMITTED, tuple(failures))
    return _result(
        ClassroomAdmission.ADMITTED,
        (ClassroomAdmissionReason.EVIDENCE_COMPLETE,),
    )


def serialize_classroom_admission(
    result: ClassroomAdmissionResult,
) -> dict[str, object]:
    """Serialize one admission result with integrity binding."""
    if type(result) is not ClassroomAdmissionResult:
        raise TypeError("result must be an exact ClassroomAdmissionResult")
    payload = {
        "schema_name": result.schema_name,
        "schema_version": result.schema_version,
        "status": result.status.value,
        "reason_codes": [reason.value for reason in result.reason_codes],
        "authoritative": False,
        "execution_authorized": False,
        "production_authorized": False,
        "classroom_ready_granted": False,
        "side_effects_performed": False,
    }
    expected = _result(result.status, result.reason_codes).result_id
    if result.result_id != expected:
        raise ValueError("classroom admission result ID mismatch")
    serialized = dict(payload)
    serialized["result_id"] = result.result_id
    return serialized


def classroom_admission_result_id(result: ClassroomAdmissionResult) -> str:
    return str(serialize_classroom_admission(result)["result_id"])


__all__ = [
    "CLASSROOM_ADMISSION_SCHEMA_NAME",
    "CLASSROOM_ADMISSION_SCHEMA_VERSION",
    "TERMINAL_QA_VERIFIED",
    "ClassroomAdmission",
    "ClassroomAdmissionReason",
    "ClassroomAdmissionEvidence",
    "ClassroomAdmissionResult",
    "RequiredVisual",
    "TemplateIdentity",
    "ArtifactIdentity",
    "ArtifactQAState",
    "assemble_admission_evidence",
    "classify_classroom_admission",
    "classroom_admission_result_id",
    "serialize_classroom_admission",
]
