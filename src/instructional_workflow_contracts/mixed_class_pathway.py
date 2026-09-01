"""Pure-local deterministic LP6 mixed-class pathway design validator (#651).

Validates one supplied-evidence-only mixed-class pathway *design* — supported,
core, or compacted-advanced — without ever assigning, classifying, or
labelling a learner. Reuses CW5A generic parsing, bounded normalization,
canonical serialization, fingerprinting, stable ID/version/revision
validation, immutable authority-false evidence, result models, reason
syntax, and import-firewall mechanics from
:mod:`instructional_workflow_contracts.common`. Reuses the canonical LP
``mixed-class-pathways`` reason codes already registered in
``04_Registry/lp-reason-code-catalog.yaml`` (LP5 / #650); this module defines
no competing reason framework.

Performs no network, Workspace, Notion, Drive, Sheets, LMS/SIS, email,
model/OCR, raw-student-work, production, or publication behavior. A supplied
Notion-export-shaped ``external_source`` is accepted only as offline input
data and is never fetched, written, or otherwise reached over the network.
"""

from __future__ import annotations

import re
from typing import Any

from .common import (
    FINGERPRINT_ALGORITHM,
    MAX_INPUT_BYTES,
    MAX_RESULT_BYTES,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_size,
    freeze_json,
    sha256_hex,
    validate_and_normalize_json,
    validate_revision,
    validate_stable_id,
    validate_text,
    validate_version,
)

CONTRACT_ID = "instructional-workflow-mixed-class-pathway-v1"

MAX_LIST_ITEMS = 32
MAX_EVIDENCE_ITEMS = 16
MAX_NOTION_PROPERTIES = 32
MAX_FIELD_LENGTH = 500

#: CW5A's shared generic normalization forbids the empty string everywhere in
#: supplied input, so a domain-optional text field (a re-entry plan, a
#: regrouping interval, an advanced-work concept link) cannot use "" to mean
#: "not supplied." This sentinel is the one non-empty placeholder value that
#: means exactly that, and is never treated as a genuine plan or reference.
NOT_SPECIFIED = "none"

TOP_LEVEL_FIELDS = frozenset(
    {
        "identity",
        "pathway",
        "grouping",
        "accessibility",
        "compacting",
        "advanced_work",
        "external_source",
        "authority",
    }
)
IDENTITY_FIELDS = frozenset({"contract_version", "record_id", "record_revision"})
PATHWAY_FIELDS = frozenset(
    {
        "pathway_type",
        "unit_ref",
        "objective_ref",
        "shared_concept_ref",
        "common_synthesis_ref",
        "pacing_coordination_ref",
    }
)
GROUPING_FIELDS = frozenset({"durable", "regroup_interval_ref"})
ACCESSIBILITY_FIELDS = frozenset({"supports", "reentry_plan"})
COMPACTING_FIELDS = frozenset(
    {
        "eligibility_basis",
        "mastered_work_removed",
        "objective_mastery_evidence",
        "added_volume_items",
    }
)
EVIDENCE_ITEM_FIELDS = frozenset({"evidence_id", "objective_ref", "status"})
ADVANCED_WORK_FIELDS = frozenset(
    {
        "advanced_dimensions",
        "advanced_success_criteria",
        "shared_concept_ref",
        "common_synthesis_ref",
    }
)
EXTERNAL_SOURCE_FIELDS = frozenset({"kind", "notion_properties"})
#: Fixed-false contract, mirroring the existing CW5A authority pattern. None of
#: these fields are ever settable to true by supplied evidence; every emitted
#: record carries the same fixed-false authority block regardless of input.
AUTHORITY_FIELDS = frozenset(
    {
        "execution_authorized",
        "grading_authorized",
        "readiness_authorized",
        "learner_classification_authorized",
        "placement_authorized",
        "route_assignment_authorized",
        "artifact_generation_authorized",
        "production_authorized",
        "publication_authorized",
        "external_write_authorized",
        "network_access_authorized",
    }
)

PATHWAY_TYPES = frozenset({"supported", "core", "compacted-advanced"})
ELIGIBILITY_BASIS_VALUES = frozenset({"objective-mastery-evidence", "speed"})
EVIDENCE_STATUSES = frozenset({"current", "stale", "privacy-blocked"})
EXTERNAL_SOURCE_KINDS = frozenset({"manual", "notion-export"})

#: Canonical LP ``mixed-class-pathways`` reason codes (LP5 / #650). Sourced
#: from ``04_Registry/lp-reason-code-catalog.yaml``; this module never
#: invents a competing code.
LP_PATHWAY_OBJECTIVE_MASTERY_EVIDENCE_MISSING = "lp-pathway-objective-mastery-evidence-missing"
LP_PATHWAY_SPEED_ONLY_ELIGIBILITY = "lp-pathway-speed-only-eligibility"
LP_PATHWAY_MASTERED_WORK_UNIDENTIFIED = "lp-pathway-mastered-work-unidentified"
LP_PATHWAY_ADDED_VOLUME_NOT_COMPACTING = "lp-pathway-added-volume-not-compacting"
LP_PATHWAY_ADVANCED_DIMENSION_ABSENT = "lp-pathway-advanced-dimension-absent"
LP_PATHWAY_EXTENSION_UNRELATED = "lp-pathway-extension-unrelated"
LP_PATHWAY_FIXED_GROUPING_ATTEMPTED = "lp-pathway-fixed-grouping-attempted"
LP_PATHWAY_ACCESSIBILITY_OR_REENTRY_UNRESOLVED = "lp-pathway-accessibility-or-reentry-unresolved"
LP_PATHWAY_AUTOMATIC_PLACEMENT_ATTEMPTED = "lp-pathway-automatic-placement-attempted"

#: Per-code ``manual_review_required`` / ``privacy_sensitive`` metadata, copied
#: by reference from the canonical catalog record for each code (never
#: redefined here).
_MANUAL_REVIEW_CODES = frozenset(
    {
        LP_PATHWAY_OBJECTIVE_MASTERY_EVIDENCE_MISSING,
        LP_PATHWAY_SPEED_ONLY_ELIGIBILITY,
        LP_PATHWAY_FIXED_GROUPING_ATTEMPTED,
        LP_PATHWAY_ACCESSIBILITY_OR_REENTRY_UNRESOLVED,
        LP_PATHWAY_AUTOMATIC_PLACEMENT_ATTEMPTED,
    }
)
_PRIVACY_SENSITIVE_CODES = frozenset({LP_PATHWAY_AUTOMATIC_PLACEMENT_ATTEMPTED})

#: A supplied Notion-export-shaped ``external_source`` is offline input data
#: only. These patterns catch a learner identity or a protected/inferred
#: attribute surfacing in its free-form property names, which this validator
#: must reject as an automatic-placement attempt rather than silently accept
#: as structured LP5 evidence.
_IDENTITY_KEY_RE = re.compile(
    r"(?:student|learner)[\s_-]*(?:name|id|email|number)|assigned[\s_-]*(?:student|to|learner)",
    re.IGNORECASE,
)
_PROTECTED_ATTRIBUTE_KEY_RE = re.compile(
    r"\b(?:race|ethnicity|gender|sex|disab\w*|iep|504|ell|ses|"
    r"free[\s_-]*(?:or[\s_-]*)?reduced|income|home[\s_-]*language|"
    r"immigration|religion|national[\s_-]*origin)\b",
    re.IGNORECASE,
)


def _invalid(reason: str, detail: str) -> ValidationResult:
    return ValidationResult(
        status=ValidationStatus.INVALID,
        record=None,
        reason_codes=(reason,),
        details=(detail,),
    )


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in mapping")
    return value


def _exact_fields(value: dict[str, Any], expected: frozenset[str], name: str) -> None:
    if set(value) != expected:
        if set(value) - expected:
            raise ContractValidationError("handoff-unknown-field", f"{name} contains unknown fields")
        raise ContractValidationError("handoff-invalid", f"{name} is missing required fields")


def _choice(value: Any, allowed: frozenset[str], name: str) -> str:
    if type(value) is not str or value not in allowed:
        raise ContractValidationError("handoff-invalid", f"{name} is unsupported")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in Boolean")
    return value


def _text_list(value: Any, name: str, *, maximum: int = MAX_LIST_ITEMS) -> list[str]:
    if type(value) is not list:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in list")
    if len(value) > maximum:
        raise ContractValidationError("handoff-oversized", f"{name} exceeds its collection bound")
    checked = [validate_text(item, name) for item in value]
    if len(set(checked)) != len(checked):
        raise ContractValidationError("handoff-duplicate", f"{name} contains duplicate values")
    return sorted(checked)


def _stable_id_list(value: Any, name: str, *, maximum: int = MAX_LIST_ITEMS) -> list[str]:
    if type(value) is not list:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in list")
    if len(value) > maximum:
        raise ContractValidationError("handoff-oversized", f"{name} exceeds its collection bound")
    checked = [validate_stable_id(item, name) for item in value]
    if len(set(checked)) != len(checked):
        raise ContractValidationError("handoff-duplicate", f"{name} contains duplicate values")
    return sorted(checked)


def _validate_authority(authority: dict[str, Any]) -> None:
    _exact_fields(authority, AUTHORITY_FIELDS, "authority")
    for name, value in authority.items():
        if type(value) is not bool or value is not False:
            raise ContractValidationError("authority-invalid", f"{name} must be built-in false")


def _evidence_items(value: Any) -> list[dict[str, str]]:
    if type(value) is not list:
        raise ContractValidationError(
            "handoff-wrong-type", "compacting.objective_mastery_evidence must be a built-in list"
        )
    if len(value) > MAX_EVIDENCE_ITEMS:
        raise ContractValidationError(
            "handoff-oversized", "compacting.objective_mastery_evidence exceeds its collection bound"
        )
    checked: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in value:
        mapped = _mapping(item, "compacting.objective_mastery_evidence item")
        _exact_fields(mapped, EVIDENCE_ITEM_FIELDS, "compacting.objective_mastery_evidence item")
        evidence_id = validate_stable_id(mapped["evidence_id"], "objective_mastery_evidence.evidence_id")
        if evidence_id in seen_ids:
            raise ContractValidationError(
                "handoff-duplicate", "objective_mastery_evidence contains a duplicate evidence_id"
            )
        seen_ids.add(evidence_id)
        objective_ref = validate_stable_id(mapped["objective_ref"], "objective_mastery_evidence.objective_ref")
        status = _choice(mapped["status"], EVIDENCE_STATUSES, "objective_mastery_evidence.status")
        checked.append({"evidence_id": evidence_id, "objective_ref": objective_ref, "status": status})
    return sorted(checked, key=lambda item: item["evidence_id"])


def _notion_properties(value: Any) -> dict[str, str]:
    if type(value) is not dict:
        raise ContractValidationError(
            "handoff-wrong-type", "external_source.notion_properties must be a built-in mapping"
        )
    if len(value) > MAX_NOTION_PROPERTIES:
        raise ContractValidationError(
            "handoff-oversized", "external_source.notion_properties exceeds its collection bound"
        )
    checked: dict[str, str] = {}
    for key, item in value.items():
        if type(key) is not str:
            raise ContractValidationError(
                "handoff-wrong-type", "external_source.notion_properties keys must be built-in strings"
            )
        validate_text(key, "external_source.notion_properties key", max_length=MAX_FIELD_LENGTH)
        checked[key] = validate_text(item, f"external_source.notion_properties.{key}", max_length=MAX_FIELD_LENGTH)
    return checked


def _external_source_implies_learner(notion_properties: dict[str, str]) -> bool:
    """Return whether a supplied Notion-export property set implies a learner.

    Any non-empty property whose *name* reads as a learner identity or a
    protected/inferred attribute is treated as an automatic-placement
    attempt, regardless of the property's value. The export is read as
    already-supplied offline data only; nothing here fetches, resolves, or
    mutates a live Notion page.
    """
    for key, item in notion_properties.items():
        if not item:
            continue
        if _IDENTITY_KEY_RE.search(key) or _PROTECTED_ATTRIBUTE_KEY_RE.search(key):
            return True
    return False


def validate_mixed_class_pathway(value: object) -> ValidationResult:
    """Validate one supplied-evidence-only LP6 mixed-class pathway design.

    Validates a supported, core, or compacted-advanced pathway *design*
    without assigning, classifying, or labelling any learner. Pure local
    computation on already-supplied evidence only: no network, Workspace,
    Notion, Drive, Sheets, LMS/SIS, email, model/OCR, raw-student-work,
    production, or publication behavior of any kind.
    """
    try:
        normalized = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
        payload = _mapping(normalized, "pathway record")
        _exact_fields(payload, TOP_LEVEL_FIELDS, "pathway record")

        identity = _mapping(payload["identity"], "identity")
        pathway = _mapping(payload["pathway"], "pathway")
        grouping = _mapping(payload["grouping"], "grouping")
        accessibility = _mapping(payload["accessibility"], "accessibility")
        external_source = _mapping(payload["external_source"], "external_source")
        authority = _mapping(payload["authority"], "authority")

        _exact_fields(identity, IDENTITY_FIELDS, "identity")
        _exact_fields(pathway, PATHWAY_FIELDS, "pathway")
        _exact_fields(grouping, GROUPING_FIELDS, "grouping")
        _exact_fields(accessibility, ACCESSIBILITY_FIELDS, "accessibility")
        _exact_fields(external_source, EXTERNAL_SOURCE_FIELDS, "external_source")
        _validate_authority(authority)

        if validate_version(identity["contract_version"]) != CONTRACT_ID:
            raise ContractValidationError("handoff-version-unsupported", "contract_version is unsupported")
        record_id = validate_stable_id(identity["record_id"], "record_id")
        revision = validate_revision(identity["record_revision"])

        pathway_type = _choice(pathway["pathway_type"], PATHWAY_TYPES, "pathway.pathway_type")
        unit_ref = validate_stable_id(pathway["unit_ref"], "pathway.unit_ref")
        objective_ref = validate_stable_id(pathway["objective_ref"], "pathway.objective_ref")
        shared_concept_ref = validate_stable_id(pathway["shared_concept_ref"], "pathway.shared_concept_ref")
        common_synthesis_ref = validate_stable_id(pathway["common_synthesis_ref"], "pathway.common_synthesis_ref")
        pacing_coordination_ref = validate_stable_id(
            pathway["pacing_coordination_ref"], "pathway.pacing_coordination_ref"
        )

        durable = _bool(grouping["durable"], "grouping.durable")
        regroup_interval_ref = validate_text(
            grouping["regroup_interval_ref"], "grouping.regroup_interval_ref", max_length=MAX_FIELD_LENGTH
        )

        supports = _text_list(accessibility["supports"], "accessibility.supports")
        reentry_plan = validate_text(
            accessibility["reentry_plan"], "accessibility.reentry_plan", max_length=MAX_FIELD_LENGTH
        )

        source_kind = _choice(external_source["kind"], EXTERNAL_SOURCE_KINDS, "external_source.kind")
        raw_notion_properties = external_source["notion_properties"]
        if source_kind == "manual":
            if raw_notion_properties is not None:
                raise ContractValidationError(
                    "handoff-invalid", "external_source.notion_properties must be null for a manual source"
                )
            notion_properties: dict[str, str] = {}
        else:
            notion_properties = _notion_properties(raw_notion_properties)

        compacting_raw = payload["compacting"]
        advanced_work_raw = payload["advanced_work"]
        if pathway_type == "compacted-advanced":
            if compacting_raw is None or advanced_work_raw is None:
                raise ContractValidationError(
                    "handoff-invalid",
                    "a compacted-advanced pathway requires both compacting and advanced_work",
                )
        elif compacting_raw is not None or advanced_work_raw is not None:
            raise ContractValidationError(
                "handoff-invalid",
                "only a compacted-advanced pathway may supply compacting or advanced_work",
            )

        compacting: dict[str, Any] | None = None
        advanced_work: dict[str, Any] | None = None

        if compacting_raw is not None:
            compacting_mapping = _mapping(compacting_raw, "compacting")
            _exact_fields(compacting_mapping, COMPACTING_FIELDS, "compacting")
            eligibility_basis_raw = compacting_mapping["eligibility_basis"]
            if type(eligibility_basis_raw) is not list or not eligibility_basis_raw:
                raise ContractValidationError(
                    "handoff-invalid", "compacting.eligibility_basis must name at least one basis"
                )
            if len(eligibility_basis_raw) > MAX_LIST_ITEMS:
                raise ContractValidationError(
                    "handoff-oversized", "compacting.eligibility_basis exceeds its collection bound"
                )
            eligibility_basis = [
                _choice(item, ELIGIBILITY_BASIS_VALUES, "compacting.eligibility_basis")
                for item in eligibility_basis_raw
            ]
            if len(set(eligibility_basis)) != len(eligibility_basis):
                raise ContractValidationError("handoff-duplicate", "compacting.eligibility_basis contains duplicates")
            compacting = {
                "eligibility_basis": sorted(set(eligibility_basis)),
                "mastered_work_removed": _stable_id_list(
                    compacting_mapping["mastered_work_removed"], "compacting.mastered_work_removed"
                ),
                "objective_mastery_evidence": _evidence_items(compacting_mapping["objective_mastery_evidence"]),
                "added_volume_items": _stable_id_list(
                    compacting_mapping["added_volume_items"], "compacting.added_volume_items"
                ),
            }

        if advanced_work_raw is not None:
            advanced_work_mapping = _mapping(advanced_work_raw, "advanced_work")
            _exact_fields(advanced_work_mapping, ADVANCED_WORK_FIELDS, "advanced_work")
            advanced_work = {
                "advanced_dimensions": _text_list(
                    advanced_work_mapping["advanced_dimensions"], "advanced_work.advanced_dimensions"
                ),
                "advanced_success_criteria": _text_list(
                    advanced_work_mapping["advanced_success_criteria"], "advanced_work.advanced_success_criteria"
                ),
                "shared_concept_ref": validate_text(
                    advanced_work_mapping["shared_concept_ref"],
                    "advanced_work.shared_concept_ref",
                    max_length=MAX_FIELD_LENGTH,
                ),
                "common_synthesis_ref": validate_text(
                    advanced_work_mapping["common_synthesis_ref"],
                    "advanced_work.common_synthesis_ref",
                    max_length=MAX_FIELD_LENGTH,
                ),
            }

        blockers: list[str] = []

        if durable or regroup_interval_ref == NOT_SPECIFIED:
            blockers.append(LP_PATHWAY_FIXED_GROUPING_ATTEMPTED)
        if not supports or reentry_plan == NOT_SPECIFIED:
            blockers.append(LP_PATHWAY_ACCESSIBILITY_OR_REENTRY_UNRESOLVED)
        if _external_source_implies_learner(notion_properties):
            blockers.append(LP_PATHWAY_AUTOMATIC_PLACEMENT_ATTEMPTED)

        if compacting is not None:
            if set(compacting["eligibility_basis"]) == {"speed"}:
                blockers.append(LP_PATHWAY_SPEED_ONLY_ELIGIBILITY)
            current_evidence = [
                item for item in compacting["objective_mastery_evidence"] if item["status"] == "current"
            ]
            if not current_evidence:
                blockers.append(LP_PATHWAY_OBJECTIVE_MASTERY_EVIDENCE_MISSING)
            if not compacting["mastered_work_removed"]:
                blockers.append(LP_PATHWAY_MASTERED_WORK_UNIDENTIFIED)
                if compacting["added_volume_items"]:
                    blockers.append(LP_PATHWAY_ADDED_VOLUME_NOT_COMPACTING)
            if advanced_work is not None:
                if not advanced_work["advanced_dimensions"] or not advanced_work["advanced_success_criteria"]:
                    blockers.append(LP_PATHWAY_ADVANCED_DIMENSION_ABSENT)
                if (
                    advanced_work["shared_concept_ref"] != shared_concept_ref
                    or advanced_work["common_synthesis_ref"] != common_synthesis_ref
                ):
                    blockers.append(LP_PATHWAY_EXTENSION_UNRELATED)

        blockers = sorted(set(blockers))
        manual_review_required = bool(set(blockers) & _MANUAL_REVIEW_CODES)
        privacy_sensitive = bool(set(blockers) & _PRIVACY_SENSITIVE_CODES)

        output = {
            "identity": {
                "contract_version": CONTRACT_ID,
                "record_id": record_id,
                "record_revision": revision,
            },
            "pathway": {
                "pathway_type": pathway_type,
                "unit_ref": unit_ref,
                "objective_ref": objective_ref,
                "shared_concept_ref": shared_concept_ref,
                "common_synthesis_ref": common_synthesis_ref,
                "pacing_coordination_ref": pacing_coordination_ref,
            },
            "grouping": {"durable": durable, "regroup_interval_ref": regroup_interval_ref},
            "accessibility": {"supports": supports, "reentry_plan": reentry_plan},
            "compacting": compacting,
            "advanced_work": advanced_work,
            "external_source": {"kind": source_kind, "notion_properties": notion_properties},
            "learner_assignment": None,
            "pacing_coordination_preserved": True,
            "teacher_review_required": True,
            "manual_review_required": manual_review_required,
            "privacy_sensitive": privacy_sensitive,
            "blocked_reason_codes": list(blockers),
            "authority": {name: False for name in sorted(AUTHORITY_FIELDS)},
        }
        if canonical_size(output) > MAX_RESULT_BYTES:
            raise ContractValidationError("handoff-oversized", "normalized result exceeds its byte bound")

        record = ValidatedRecord(
            contract_version=CONTRACT_ID,
            record_id=record_id,
            record_revision=revision,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(output),
            payload=freeze_json(output),
        )

        if blockers:
            return ValidationResult(
                status=ValidationStatus.BLOCKED,
                record=record,
                blockers=tuple(blockers),
            )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return _invalid(exc.reason_code, exc.detail)
    except (TypeError, ValueError):
        return _invalid("handoff-invalid", "mixed-class pathway validation failed")
