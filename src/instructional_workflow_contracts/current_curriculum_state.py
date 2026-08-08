"""Pure deterministic current-curriculum-state projection from supplied evidence."""

from __future__ import annotations

from typing import Any

from .common import (
    FINGERPRINT_ALGORITHM,
    MAX_INPUT_BYTES,
    MAX_RESULT_BYTES as SHARED_MAX_RESULT_BYTES,
    ContractReference,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_size,
    freeze_json,
    sanitize_detail,
    sha256_hex,
    validate_and_normalize_json,
    validate_revision,
    validate_stable_id,
    validate_text,
    validate_timestamp,
    validate_version,
)

INPUT_CONTRACT_ID = "curriculum-current-state-evidence-v1"
CONTRACT_ID = "curriculum-current-state-v1"
MAX_RESULT_BYTES = 16 * 1024
MAX_OWNER_EVIDENCE = 24
MAX_ASSET_EVIDENCE = 24
MAX_DAY_IDS = 32
CLASSIFICATIONS = {"owner-governed", "display-derived", "agent-suggested", "teacher-entered"}
UNIT_STATUSES = {"active", "ambiguous", "archived", "split", "merged", "human-review-required"}
_AUTHORITY_KEYS = {
    "authority", "execution_authorized", "external_write_authorized",
    "notion_write_authorized", "drive_write_authorized", "production_authorized",
    "publication_authorized", "readiness_authorized", "approval_authorized",
}


def resolve_current_curriculum_state(evidence: object) -> ValidationResult:
    """Project bounded provider-neutral evidence without reads, writes, or inference."""
    try:
        root = _mapping(validate_and_normalize_json(evidence, max_bytes=MAX_INPUT_BYTES), "evidence")
        _reject_authority_attack(root)
        if validate_version(root.get("contract_version")) != INPUT_CONTRACT_ID:
            raise ContractValidationError("handoff-version-unsupported", "unsupported current-state evidence version")

        unit = _unit(root.get("canonical_unit"))
        request = _request(root.get("request"))
        current_context, resolved_day_id, routing_blockers = _context(
            root.get("current_context"), request["relative_time"]
        )
        required = set(_ids(root.get("required_decision_keys", []), "required decision keys", MAX_OWNER_EVIDENCE))
        evidence_items = _owner_evidence(root.get("owner_evidence", []))
        assets = _assets(root.get("asset_evidence", []))

        reasons: set[str] = set()
        blockers: set[str] = set(routing_blockers)
        contradictions: list[dict[str, Any]] = []
        owner_states: list[dict[str, Any]] = []
        context_evidence = [_context_evidence(item) for item in evidence_items if item["classification"] != "owner-governed"]
        stale_evidence = [_evidence_ref(item) for item in evidence_items if item["currentness"] == "stale"]
        next_owner: str | None = None
        teacher_decision: str | None = None

        unit_reason = {
            "active": None,
            "ambiguous": "identity-canonical-unit-ambiguous",
            "archived": "identity-canonical-unit-archived",
            "split": "identity-canonical-unit-split",
            "merged": "identity-canonical-unit-merged",
            "human-review-required": "manual-review-canonical-unit-human-review",
        }[unit["status"]]
        if unit_reason:
            reasons.add(unit_reason)
            teacher_decision = "Resolve canonical unit identity before downstream planning."

        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in evidence_items:
            grouped.setdefault(item["decision_key"], []).append(item)

        for key in sorted(set(grouped) | required):
            records = grouped.get(key, [])
            owners = [r for r in records if r["classification"] == "owner-governed"]
            current = [r for r in owners if r["currentness"] == "current"]
            stale = [r for r in owners if r["currentness"] == "stale"]

            unresolved = [r for r in records if r["material"] and not r["relation_resolved"]]
            if unresolved:
                blockers.add("dependency-owner-relation-unresolved")
                next_owner = next_owner or unresolved[0]["owner"]

            if key in required and not current:
                if not stale:
                    blockers.add("dependency-owner-evidence-missing")
                    continue
                reasons.add("source-stale-material")
                stale_owner = max(stale, key=_freshness_key)
                next_owner = next_owner or stale_owner["owner"]
                for item in records:
                    if (
                        item["classification"] == "teacher-entered"
                        and item["value"] is not None
                        and item["value"] != stale_owner["value"]
                        and item["observed_at"] > stale_owner["observed_at"]
                    ):
                        reasons.add("source-newer-narrative-conflict")
                        contradictions.append(_conflict("newer-narrative-vs-stale-owner", key, stale_owner, item))
                continue
            if not current:
                continue

            if len({r["owner"] for r in current}) > 1:
                reasons.add("ownership-owner-conflict")
                contradictions.append(_multi_conflict("owner-conflict", key, current))
                continue
            if len({r["value"] for r in current}) > 1:
                reasons.add("source-owner-value-conflict")
                contradictions.append(_multi_conflict("owner-value-conflict", key, current))
                next_owner = next_owner or current[0]["owner"]
                continue

            operative = max(current, key=_freshness_key)
            owner_states.append(_owner_state(operative))
            for item in records:
                if item["evidence_id"] == operative["evidence_id"] or item["value"] in {None, operative["value"]}:
                    continue
                classification = item["classification"]
                if classification == "teacher-entered" and item["observed_at"] > operative["observed_at"]:
                    reasons.add("source-newer-narrative-conflict")
                    contradictions.append(_conflict("newer-narrative-conflict", key, operative, item))
                    next_owner = next_owner or operative["owner"]
                elif classification == "display-derived":
                    contradictions.append(_conflict("display-drift", key, operative, item))
                    if item["material"]:
                        reasons.add("source-display-drift")
                        next_owner = next_owner or operative["owner"]
                elif classification == "agent-suggested":
                    contradictions.append(_conflict("advisory-conflict", key, operative, item))

        asset_summary, asset_reasons, asset_blockers = _asset_summary(assets, request["requires_reusable_assets"])
        reasons |= asset_reasons
        blockers |= asset_blockers
        if (asset_reasons or asset_blockers) and next_owner is None:
            next_owner = "curriculum-source-control"

        disposition = _disposition(unit["status"], reasons, blockers)
        if teacher_decision is None:
            if "routing-current-day-missing" in blockers or "routing-current-day-unresolvable" in blockers:
                teacher_decision = "Provide trustworthy current-day evidence."
            elif "dependency-owner-evidence-missing" in blockers:
                teacher_decision = "Resolve the missing canonical owner evidence."
            elif "asset-reusable-unavailable" in blockers:
                teacher_decision = "Resolve reusable asset eligibility before artifact planning."
            elif disposition == "needs-reconciliation":
                teacher_decision = "Reconcile current owner state with contradictory or stale evidence."
            elif disposition == "needs-decision":
                teacher_decision = "Resolve the conflicting canonical planning evidence."

        payload = {
            "contract_version": CONTRACT_ID,
            "state_id": "pending",
            "canonical_unit": unit,
            "request": request,
            "current_context": current_context,
            "resolved_day_id": resolved_day_id,
            "owner_states": sorted(owner_states, key=lambda x: (x["decision_key"], x["owner"], x["evidence_id"])),
            "context_evidence": sorted(context_evidence, key=lambda x: (x["decision_key"], x["classification"], x["evidence_id"])),
            "stale_evidence": sorted(stale_evidence, key=lambda x: x["evidence_id"]),
            "contradictions": sorted(contradictions, key=lambda x: (x["decision_key"], x["kind"], x["evidence_ids"])),
            "unresolved_teacher_decision": teacher_decision,
            "next_legitimate_owner": next_owner,
            "disposition": disposition,
            "assets": asset_summary,
            "reason_codes": sorted(reasons),
            "blockers": sorted(blockers),
            "authority": {
                "execution_authorized": False,
                "external_write_authorized": False,
                "notion_write_authorized": False,
                "drive_write_authorized": False,
                "production_authorized": False,
                "publication_authorized": False,
            },
        }
        payload["state_id"] = "current-state-" + sha256_hex({k: v for k, v in payload.items() if k != "state_id"})[:24]
        validate_stable_id(payload["state_id"], "current curriculum state_id")
        normalized = validate_and_normalize_json(payload, max_bytes=MAX_RESULT_BYTES)
        if canonical_size(normalized) > min(MAX_RESULT_BYTES, SHARED_MAX_RESULT_BYTES):
            raise ContractValidationError("handoff-oversized", "current curriculum state exceeds result bound")
        record = ValidatedRecord(
            contract_version=CONTRACT_ID,
            record_id=normalized["state_id"],
            record_revision=1,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(normalized),
            payload=freeze_json(normalized),
        )
        codes = tuple(sorted(reasons | blockers))
        if disposition == "blocked":
            return ValidationResult(
                status=ValidationStatus.BLOCKED,
                record=record,
                reason_codes=codes,
                blockers=tuple(sorted(blockers)),
                details=("current curriculum state is fail-closed for the requested action",),
            )
        if disposition in {"needs-reconciliation", "needs-decision"}:
            return ValidationResult(
                status=ValidationStatus.MANUAL_REVIEW_REQUIRED,
                record=record,
                reason_codes=codes,
                details=("current curriculum evidence requires bounded human reconciliation",),
            )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return _invalid(exc.reason_code, exc.detail)
    except (TypeError, ValueError) as exc:
        return _invalid("handoff-invalid", sanitize_detail(str(exc)))


def _mapping(value: object, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in mapping")
    return value


def _unit(value: object) -> dict[str, str]:
    raw = _mapping(value, "canonical_unit")
    status = validate_text(raw.get("status"), "canonical unit status", max_length=64)
    if status not in UNIT_STATUSES:
        raise ContractValidationError("identity-invalid", "canonical unit status is unsupported")
    return {"stable_id": validate_stable_id(raw.get("stable_id"), "canonical unit stable_id"), "status": status}


def _request(value: object) -> dict[str, Any]:
    raw = _mapping(value, "request")
    relative = validate_text(raw.get("relative_time", "none"), "relative_time", max_length=32)
    if relative not in {"none", "tomorrow"}:
        raise ContractValidationError("routing-invalid", "relative_time is unsupported")
    requires_assets = raw.get("requires_reusable_assets", False)
    if type(requires_assets) is not bool:
        raise ContractValidationError("handoff-wrong-type", "requires_reusable_assets must be a boolean")
    artifact = raw.get("artifact_type")
    return {
        "action": validate_text(raw.get("action"), "request action"),
        "artifact_type": None if artifact is None else validate_text(artifact, "artifact_type", max_length=128),
        "relative_time": relative,
        "requires_reusable_assets": requires_assets,
    }


def _context(value: object, relative: str) -> tuple[dict[str, Any] | None, str | None, set[str]]:
    if value is None:
        return (None, None, {"routing-current-day-missing"}) if relative == "tomorrow" else (None, None, set())
    raw = _mapping(value, "current_context")
    current = validate_stable_id(raw.get("current_day_id"), "current day stable_id")
    ordered = _ordered_ids(raw.get("ordered_day_ids", []), "ordered day ids", MAX_DAY_IDS)
    if relative != "tomorrow":
        return {"current_day_id": current, "ordered_day_ids": list(ordered)}, current, set()
    if current not in ordered or ordered.index(current) + 1 >= len(ordered):
        return {"current_day_id": current, "ordered_day_ids": list(ordered)}, None, {"routing-current-day-unresolvable"}
    return {"current_day_id": current, "ordered_day_ids": list(ordered)}, ordered[ordered.index(current) + 1], set()


def _ids(value: object, name: str, maximum: int) -> tuple[str, ...]:
    return tuple(sorted(_ordered_ids(value, name, maximum)))


def _ordered_ids(value: object, name: str, maximum: int) -> tuple[str, ...]:
    if type(value) is not list:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in list")
    if len(value) > maximum:
        raise ContractValidationError("handoff-oversized", f"{name} exceeds its bound")
    checked = [validate_stable_id(item, name) for item in value]
    if len(set(checked)) != len(checked):
        raise ContractValidationError("handoff-duplicate", f"{name} contains duplicates")
    return tuple(checked)


def _owner_evidence(value: object) -> list[dict[str, Any]]:
    if type(value) is not list:
        raise ContractValidationError("handoff-wrong-type", "owner_evidence must be a built-in list")
    if len(value) > MAX_OWNER_EVIDENCE:
        raise ContractValidationError("handoff-oversized", "owner_evidence exceeds its bound")
    items = [_owner_item(item) for item in value]
    if len({item["evidence_id"] for item in items}) != len(items):
        raise ContractValidationError("handoff-duplicate", "owner_evidence IDs must be unique")
    return sorted(items, key=lambda x: x["evidence_id"])


def _owner_item(value: object) -> dict[str, Any]:
    raw = _mapping(value, "owner evidence")
    classification = validate_text(raw.get("classification"), "evidence classification", max_length=32)
    currentness = validate_text(raw.get("currentness"), "evidence currentness", max_length=16)
    if classification not in CLASSIFICATIONS:
        raise ContractValidationError("ownership-owner-conflict", "evidence classification is unsupported")
    if currentness not in {"current", "stale"}:
        raise ContractValidationError("source-invalid", "evidence currentness is unsupported")
    material, relation = raw.get("material"), raw.get("relation_resolved", True)
    if type(material) is not bool or type(relation) is not bool:
        raise ContractValidationError("handoff-wrong-type", "material and relation_resolved must be booleans")
    raw_value = raw.get("value")
    item_value = None if raw_value is None else validate_text(raw_value, "evidence value")
    if classification == "owner-governed" and item_value is None:
        raise ContractValidationError("source-invalid", "owner-governed evidence requires a value")
    return {
        "evidence_id": validate_stable_id(raw.get("evidence_id"), "evidence_id"),
        "owner": validate_stable_id(raw.get("owner"), "evidence owner"),
        "decision_key": validate_stable_id(raw.get("decision_key"), "decision_key"),
        "value": item_value,
        "classification": classification,
        "source_revision": validate_revision(raw.get("source_revision")),
        "observed_at": validate_timestamp(raw.get("observed_at"), "evidence observed_at"),
        "currentness": currentness,
        "material": material,
        "relation_resolved": relation,
        "reference": _reference(raw.get("reference")),
    }


def _reference(value: object) -> dict[str, str]:
    raw = _mapping(value, "evidence reference")
    ref = ContractReference(
        system=raw.get("system"), stable_id=raw.get("stable_id"),
        exact_location=raw.get("exact_location"), verification_evidence=raw.get("verification_evidence")
    )
    return {"system": ref.system, "stable_id": ref.stable_id, "exact_location": ref.exact_location, "verification_evidence": ref.verification_evidence}


def _assets(value: object) -> list[dict[str, Any]]:
    if type(value) is not list:
        raise ContractValidationError("handoff-wrong-type", "asset_evidence must be a built-in list")
    if len(value) > MAX_ASSET_EVIDENCE:
        raise ContractValidationError("handoff-oversized", "asset_evidence exceeds its bound")
    items: list[dict[str, Any]] = []
    for value_item in value:
        raw = _mapping(value_item, "asset evidence")
        exists, approved, reuse = raw.get("exists"), raw.get("approved_for_requested_use"), raw.get("approved_student_reuse")
        if type(exists) is not bool or (approved is not None and type(approved) is not bool) or (reuse is not None and type(reuse) is not bool):
            raise ContractValidationError("handoff-wrong-type", "asset eligibility fields have invalid types")
        items.append({
            "asset_id": validate_stable_id(raw.get("asset_id"), "asset_id"),
            "exists": exists, "approved_for_requested_use": approved, "approved_student_reuse": reuse,
            "source_revision": validate_revision(raw.get("source_revision")),
        })
    if len({item["asset_id"] for item in items}) != len(items):
        raise ContractValidationError("handoff-duplicate", "asset IDs must be unique")
    return sorted(items, key=lambda x: x["asset_id"])


def _asset_summary(items: list[dict[str, Any]], required: bool) -> tuple[dict[str, Any], set[str], set[str]]:
    existing = [item for item in items if item["exists"]]
    ambiguous = [item for item in existing if item["approved_for_requested_use"] is None or item["approved_student_reuse"] is None]
    eligible = [item for item in existing if item["approved_for_requested_use"] is True and item["approved_student_reuse"] is True]
    reasons = {"asset-approval-ambiguous"} if ambiguous else set()
    blockers = {"asset-reusable-unavailable"} if required and not eligible and not ambiguous else set()
    return {
        "matching_asset_exists": bool(existing),
        "approved_for_requested_use_exists": any(item["approved_for_requested_use"] is True for item in existing),
        "approved_reusable_student_facing_exists": bool(eligible),
        "production_authorized": False,
        "asset_ids": [item["asset_id"] for item in existing],
        "eligible_asset_ids": [item["asset_id"] for item in eligible],
    }, reasons, blockers


def _disposition(status: str, reasons: set[str], blockers: set[str]) -> str:
    if blockers:
        return "blocked"
    if status != "active" or reasons & {"ownership-owner-conflict", "source-owner-value-conflict"}:
        return "needs-decision"
    if reasons & {"source-stale-material", "source-newer-narrative-conflict", "source-display-drift", "asset-approval-ambiguous"}:
        return "needs-reconciliation"
    return "supported"


def _freshness_key(item: dict[str, Any]) -> tuple[str, int, str]:
    return item["observed_at"], item["source_revision"], item["evidence_id"]


def _owner_state(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in ("evidence_id", "owner", "decision_key", "value", "source_revision", "observed_at", "reference")}


def _context_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in ("evidence_id", "owner", "decision_key", "value", "classification", "source_revision", "observed_at", "currentness", "material", "reference")}


def _evidence_ref(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in ("evidence_id", "owner", "decision_key", "source_revision", "observed_at", "reference")}


def _conflict(kind: str, key: str, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return _multi_conflict(kind, key, [left, right])


def _multi_conflict(kind: str, key: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"kind": kind, "decision_key": key, "evidence_ids": sorted(item["evidence_id"] for item in items), "owners": sorted({item["owner"] for item in items})}


def _reject_authority_attack(value: object) -> None:
    if type(value) is dict:
        for key, item in value.items():
            if key in _AUTHORITY_KEYS and item is not False and item is not None:
                raise ContractValidationError("authority-escalation-attempt", "supplied evidence attempts to grant authority")
            _reject_authority_attack(item)
    elif type(value) is list:
        for item in value:
            _reject_authority_attack(item)


def _invalid(reason: str, detail: str) -> ValidationResult:
    return ValidationResult(
        status=ValidationStatus.INVALID, record=None, reason_codes=(reason,), details=(sanitize_detail(detail),)
    )
