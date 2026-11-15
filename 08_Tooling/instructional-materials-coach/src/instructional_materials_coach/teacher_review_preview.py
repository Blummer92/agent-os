"""Teacher Review Preview projection for #3570 (Q2, child of #3259).

A pure, deterministic, non-authorizing projection over one canonical
``imc-build-receipt-v1`` record (#3454) plus caller-supplied canonical
evidence. It is the Q2 preview lane only:

- The exact visible label is ``Teacher Review Preview — Not Classroom Ready``.
- ``classroom_ready`` is always ``False`` and every authority flag is
  always ``False``. A preview never implies classroom-ready, production,
  publication, Drive/Notion write, or D8 admission, even when the build
  succeeded, terminal QA is verified, or every visual verifies *within
  preview*. Classroom-ready admission remains solely owned by
  ``classroom_admission.py`` (#3556 / #3259 D8), which this module never
  calls and never duplicates.
- Required visuals come from the caller's canonical governed requirement
  evidence, never from the receipt's ``placement_receipt_references``.
  That list records planned/existing bindings only; it cannot enumerate
  missing obligations. An empty reference list therefore never clears a
  requirement — the slot stays explicitly incomplete with a reason code.
- Verified placement evidence is checked the same way D8 checks it
  (verified state, ``visual-placement-receipt-v1`` contract, matching
  idempotency key, semantic role, slot, asset, content identity, artifact
  binding, and receipt reference), but the result is a preview status,
  not an admission verdict. Build-succeeded and terminal-QA facts from
  the receipt are reported as provenance facts only; they are not gates
  here, because an incomplete or failed build can still be previewed as
  incomplete. Canonical artifact identity is *not* re-derived here: a
  placement record's artifact must merely be one of the receipt's own
  artifact file ids. That internal-consistency check is not canonical
  proof, and the output never claims otherwise.
- Missing, malformed, mismatched, or unverified provenance fails closed:
  the result is ``provenance_status: "unavailable"`` with an explicit
  reason and no per-visual statuses, rather than a fabricated linked
  preview. No identity, revision, asset, or placement is ever invented.

Pure: no I/O, no network, no mutation of any input. The only consumer
is the offline ``preview-teacher-review`` CLI subcommand, which reads
JSON files the caller supplies and writes nothing except an optional
local preview JSON file. No guessed assets, no placeholder success, no
silent omission, no image generation.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Iterable, Mapping

from .build_receipt import BUILD_RECEIPT_CONTRACT

TEACHER_REVIEW_PREVIEW_LABEL = "Teacher Review Preview — Not Classroom Ready"
TEACHER_REVIEW_PREVIEW_SCHEMA = "teacher-review-preview-v1"
PLACEMENT_RECEIPT_CONTRACT = "visual-placement-receipt-v1"
PLACEMENT_STATE_VERIFIED = "verified"

_REQUIREMENT_FIELDS = ("requirement_id", "contract_version", "record_revision", "source_fingerprint")

REASON_PROVENANCE_UNAVAILABLE = "preview.provenance-unavailable"
REASON_EVIDENCE_MALFORMED = "preview.evidence-malformed"
REASON_PLACEMENT_MISSING = "preview.placement-receipt-missing"
REASON_ROLE_MISMATCH = "preview.semantic-role-mismatch"
REASON_PLACEMENT_MISMATCH = "preview.placement-evidence-mismatch"
REASON_PLACEMENT_CONFLICT = "preview.placement-evidence-conflict"
REASON_VERIFIED = "preview.verified-within-preview"
REASON_NOT_REQUIRED = "preview.not-required"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True, slots=True)
class PreviewRequiredVisual:
    """One required visual role/slot from canonical governed evidence."""

    role_id: str
    slot_id: str
    asset_id: str
    content_identity_json: str
    required: bool = True


def _normalize_required_visuals(required_visuals: Any) -> tuple[PreviewRequiredVisual, ...] | None:
    """Normalize caller visuals, or return None when evidence is malformed."""
    if not isinstance(required_visuals, Iterable) or isinstance(required_visuals, (str, bytes, Mapping)):
        return None
    visuals: list[PreviewRequiredVisual] = []
    seen: set[tuple[str, str]] = set()
    for entry in required_visuals:
        if isinstance(entry, PreviewRequiredVisual):
            visual = entry
        elif isinstance(entry, Mapping):
            role_id = entry.get("role_id")
            slot_id = entry.get("slot_id")
            asset_id = entry.get("asset_id")
            if type(role_id) is not str or not role_id:
                return None
            if type(slot_id) not in (str, int) or str(slot_id) == "":
                return None
            if type(asset_id) is not str or not asset_id:
                return None
            if "content_identity" not in entry:
                return None
            visual = PreviewRequiredVisual(
                role_id=role_id,
                slot_id=str(slot_id),
                asset_id=asset_id,
                content_identity_json=_canonical_json(entry.get("content_identity")),
                required=bool(entry.get("required", True)),
            )
        else:
            return None
        if type(visual.role_id) is not str or not visual.role_id:
            return None
        if type(visual.slot_id) is not str or not visual.slot_id:
            return None
        if type(visual.asset_id) is not str or not visual.asset_id:
            return None
        if type(visual.content_identity_json) is not str:
            return None
        key = (visual.role_id, visual.slot_id)
        if key in seen:
            return None
        seen.add(key)
        visuals.append(visual)
    visuals.sort(key=lambda item: (item.role_id, item.slot_id))
    return tuple(visuals)


def _normalize_placement_records(placement_records: Any) -> tuple[Mapping[str, Any], ...] | None:
    if not isinstance(placement_records, Iterable) or isinstance(placement_records, (str, bytes, Mapping)):
        return None
    records: list[Mapping[str, Any]] = []
    for entry in placement_records:
        if not isinstance(entry, Mapping):
            return None
        records.append(entry)
    return tuple(records)


def _unavailable(reason: str, *, requirement_identity: Mapping[str, Any] | None,
                 idempotency_key: str | None, required_count: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": TEACHER_REVIEW_PREVIEW_SCHEMA,
        "label": TEACHER_REVIEW_PREVIEW_LABEL,
        "provenance_status": "unavailable",
        "reason_codes": [reason],
        "contract_version": None,
        "idempotency_key": idempotency_key if type(idempotency_key) is str else None,
        "requirement_identity": dict(requirement_identity) if isinstance(requirement_identity, Mapping) else None,
        "build_succeeded": None,
        "terminal_qa_state": None,
        "visuals": [],
        "incomplete_visuals": [],
        "required_visual_count": required_count,
        "classroom_ready": False,
        "authority": {"execution_authorized": False, "production_authorized": False,
                      "classroom_ready": False},
        "visual_completeness": "unavailable",
    }
    payload["preview_id"] = (
        "teacher-review-preview:"
        + sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    )
    return payload


def _classify_visual(required: PreviewRequiredVisual,
                     placement_records: tuple[Mapping[str, Any], ...],
                     receipt_references: list[Any],
                     receipt_artifact_file_ids: set[str],
                     idempotency_key: str) -> dict[str, Any]:
    if not required.required:
        return {"role_id": required.role_id, "slot_id": required.slot_id,
                "asset_id": required.asset_id, "status": "not-required",
                "reason_code": REASON_NOT_REQUIRED}
    slot = required.slot_id
    slot_records = [
        record for record in placement_records
        if record.get("state") == PLACEMENT_STATE_VERIFIED
        and record.get("contract_version") == PLACEMENT_RECEIPT_CONTRACT
        and str(record.get("slot_id")) == slot
        and record.get("idempotency_key") == idempotency_key
    ]
    if not slot_records:
        return {"role_id": required.role_id, "slot_id": slot,
                "asset_id": required.asset_id, "status": "incomplete",
                "reason_code": REASON_PLACEMENT_MISSING}
    role_records = [record for record in slot_records if record.get("role_id") == required.role_id]
    if not role_records:
        return {"role_id": required.role_id, "slot_id": slot,
                "asset_id": required.asset_id, "status": "incomplete",
                "reason_code": REASON_ROLE_MISMATCH}
    identities = {
        (_canonical_json(record.get("content_identity")), record.get("asset_id"))
        for record in role_records
    }
    if len(identities) > 1:
        return {"role_id": required.role_id, "slot_id": slot,
                "asset_id": required.asset_id, "status": "incomplete",
                "reason_code": REASON_PLACEMENT_CONFLICT}
    record = role_records[0]
    if (
        record.get("asset_id") != required.asset_id
        or _canonical_json(record.get("content_identity")) != required.content_identity_json
        or not record.get("artifact_id")
        or record.get("artifact_id") not in receipt_artifact_file_ids
        or not any(
            isinstance(reference, Mapping)
            and reference.get("role_id") == required.role_id
            and str(reference.get("slot_id")) == slot
            and reference.get("asset_id") == required.asset_id
            for reference in receipt_references
        )
    ):
        return {"role_id": required.role_id, "slot_id": slot,
                "asset_id": required.asset_id, "status": "incomplete",
                "reason_code": REASON_PLACEMENT_MISMATCH}
    return {"role_id": required.role_id, "slot_id": slot,
            "asset_id": required.asset_id, "status": "verified-within-preview",
            "reason_code": REASON_VERIFIED}


def build_teacher_review_preview(
    receipt: Any,
    *,
    idempotency_key: str,
    requirement_identity: Mapping[str, Any],
    required_visuals: Iterable[Any],
    placement_records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the Q2 teacher-review preview projection. Never raises on
    malformed evidence: every failure mode is an explicit unavailable or
    incomplete result. Inputs are never mutated."""
    receipt_snapshot = copy.deepcopy(receipt) if isinstance(receipt, Mapping) else receipt
    visuals = _normalize_required_visuals(required_visuals)
    records = _normalize_placement_records(placement_records)
    required_count = len(visuals) if visuals is not None else 0
    caller_identity = (
        {key: requirement_identity.get(key) for key in _REQUIREMENT_FIELDS}
        if isinstance(requirement_identity, Mapping) else None
    )

    if visuals is None or records is None:
        return _unavailable(REASON_EVIDENCE_MALFORMED, requirement_identity=caller_identity,
                            idempotency_key=idempotency_key if type(idempotency_key) is str else None,
                            required_count=required_count)

    # Provenance validation: the receipt is untrusted evidence. Only an
    # exact contract version, exact idempotency key, and exact complete
    # requirement identity matching the caller's canonical values admit
    # a preview at all. Artifacts must be a mapping so placement artifact
    # binding can be checked internally; anything else is unavailable.
    if not isinstance(receipt_snapshot, Mapping):
        return _unavailable(REASON_PROVENANCE_UNAVAILABLE, requirement_identity=caller_identity,
                            idempotency_key=idempotency_key if type(idempotency_key) is str else None,
                            required_count=required_count)
    if receipt_snapshot.get("contract_version") != BUILD_RECEIPT_CONTRACT:
        return _unavailable(REASON_PROVENANCE_UNAVAILABLE, requirement_identity=caller_identity,
                            idempotency_key=idempotency_key if type(idempotency_key) is str else None,
                            required_count=required_count)
    if (
        type(idempotency_key) is not str
        or not idempotency_key
        or receipt_snapshot.get("idempotency_key") != idempotency_key
    ):
        return _unavailable(REASON_PROVENANCE_UNAVAILABLE, requirement_identity=caller_identity,
                            idempotency_key=idempotency_key if type(idempotency_key) is str else None,
                            required_count=required_count)
    receipt_identity = receipt_snapshot.get("requirement_identity")
    if not isinstance(receipt_identity, Mapping):
        return _unavailable(REASON_PROVENANCE_UNAVAILABLE, requirement_identity=caller_identity,
                            idempotency_key=idempotency_key, required_count=required_count)
    values = [receipt_identity.get(name) for name in _REQUIREMENT_FIELDS]
    if any(type(value) is not str or not value for value in values):
        return _unavailable(REASON_PROVENANCE_UNAVAILABLE, requirement_identity=caller_identity,
                            idempotency_key=idempotency_key, required_count=required_count)
    if caller_identity is None or tuple(values) != tuple(
        caller_identity.get(name) for name in _REQUIREMENT_FIELDS
    ):
        return _unavailable(REASON_PROVENANCE_UNAVAILABLE, requirement_identity=caller_identity,
                            idempotency_key=idempotency_key, required_count=required_count)
    artifacts = receipt_snapshot.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return _unavailable(REASON_PROVENANCE_UNAVAILABLE, requirement_identity=caller_identity,
                            idempotency_key=idempotency_key, required_count=required_count)

    receipt_artifact_file_ids = {
        entry.get("file_id")
        for entry in artifacts.values()
        if isinstance(entry, Mapping) and type(entry.get("file_id")) is str and entry.get("file_id")
    }
    references = receipt_snapshot.get("placement_receipt_references")
    reference_list = references if isinstance(references, list) else []

    classified = [
        _classify_visual(visual, records, reference_list, receipt_artifact_file_ids, idempotency_key)
        for visual in visuals
    ]
    incomplete = [
        {"role_id": entry["role_id"], "slot_id": entry["slot_id"]}
        for entry in classified if entry["status"] == "incomplete"
    ]
    payload: dict[str, Any] = {
        "schema": TEACHER_REVIEW_PREVIEW_SCHEMA,
        "label": TEACHER_REVIEW_PREVIEW_LABEL,
        "provenance_status": "available",
        "reason_codes": [],
        "contract_version": BUILD_RECEIPT_CONTRACT,
        "idempotency_key": idempotency_key,
        "requirement_identity": {key: caller_identity[key] for key in _REQUIREMENT_FIELDS},
        "build_succeeded": receipt_snapshot.get("succeeded"),
        "terminal_qa_state": receipt_snapshot.get("terminal_qa_state"),
        "visuals": classified,
        "incomplete_visuals": incomplete,
        "required_visual_count": len(visuals),
        "classroom_ready": False,
        "authority": {"execution_authorized": False, "production_authorized": False,
                      "classroom_ready": False},
        "visual_completeness": "incomplete" if incomplete else "all-verified-within-preview",
    }
    payload["preview_id"] = (
        "teacher-review-preview:"
        + sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    )
    return payload


__all__ = [
    "TEACHER_REVIEW_PREVIEW_LABEL",
    "TEACHER_REVIEW_PREVIEW_SCHEMA",
    "PreviewRequiredVisual",
    "build_teacher_review_preview",
]
