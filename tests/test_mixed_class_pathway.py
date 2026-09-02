from __future__ import annotations

import ast
import copy
from pathlib import Path
from typing import Any

import pytest

from instructional_workflow_contracts import ValidationStatus
from instructional_workflow_contracts.mixed_class_pathway import (
    AUTHORITY_FIELDS,
    CONTRACT_ID,
    LP_PATHWAY_ACCESSIBILITY_OR_REENTRY_UNRESOLVED,
    LP_PATHWAY_ADDED_VOLUME_NOT_COMPACTING,
    LP_PATHWAY_ADVANCED_DIMENSION_ABSENT,
    LP_PATHWAY_AUTOMATIC_PLACEMENT_ATTEMPTED,
    LP_PATHWAY_EXTENSION_UNRELATED,
    LP_PATHWAY_FIXED_GROUPING_ATTEMPTED,
    LP_PATHWAY_MASTERED_WORK_UNIDENTIFIED,
    LP_PATHWAY_OBJECTIVE_MASTERY_EVIDENCE_MISSING,
    LP_PATHWAY_SPEED_ONLY_ELIGIBILITY,
    validate_mixed_class_pathway,
)


def _authority() -> dict[str, bool]:
    return {name: False for name in sorted(AUTHORITY_FIELDS)}


def _grouping(*, durable: bool = False, regroup_interval_ref: str = "quarterly-regroup-check") -> dict[str, Any]:
    return {"durable": durable, "regroup_interval_ref": regroup_interval_ref}


def _accessibility(
    *,
    supports: list[str] | None = None,
    reentry_plan: str = "Learner rejoins the core small-group at the next unit boundary on teacher confirmation.",
) -> dict[str, Any]:
    return {
        "supports": ["read-aloud", "extended-time"] if supports is None else supports,
        "reentry_plan": reentry_plan,
    }


def _external_source(
    *, kind: str = "manual", notion_properties: dict[str, str] | None = None
) -> dict[str, Any]:
    return {"kind": kind, "notion_properties": notion_properties}


def _base_record(
    *,
    pathway_type: str = "supported",
    record_id: str = "pathway-1",
    compacting: dict[str, Any] | None = None,
    advanced_work: dict[str, Any] | None = None,
    grouping: dict[str, Any] | None = None,
    accessibility: dict[str, Any] | None = None,
    external_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "identity": {
            "contract_version": CONTRACT_ID,
            "record_id": record_id,
            "record_revision": 1,
        },
        "pathway": {
            "pathway_type": pathway_type,
            "unit_ref": "unit-fractions",
            "objective_ref": "objective-add-sub-fractions",
            "shared_concept_ref": "concept-equivalence",
            "common_synthesis_ref": "synthesis-equivalence-across-representations",
            "pacing_coordination_ref": "pacing-brief-unit-fractions",
        },
        "grouping": grouping if grouping is not None else _grouping(),
        "accessibility": accessibility if accessibility is not None else _accessibility(),
        "compacting": compacting,
        "advanced_work": advanced_work,
        "external_source": external_source if external_source is not None else _external_source(),
        "authority": _authority(),
    }


def _evidence(status: str = "current", *, evidence_id: str = "ev-1", objective_ref: str = "objective-add-sub-fractions") -> dict[str, str]:
    return {"evidence_id": evidence_id, "objective_ref": objective_ref, "status": status}


def _compacting(
    *,
    eligibility_basis: list[str] | None = None,
    mastered_work_removed: list[str] | None = None,
    objective_mastery_evidence: list[dict[str, str]] | None = None,
    added_volume_items: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "eligibility_basis": ["objective-mastery-evidence"] if eligibility_basis is None else eligibility_basis,
        "mastered_work_removed": (
            ["unit3-fraction-operations-practice-set"] if mastered_work_removed is None else mastered_work_removed
        ),
        "objective_mastery_evidence": (
            [_evidence()] if objective_mastery_evidence is None else objective_mastery_evidence
        ),
        "added_volume_items": [] if added_volume_items is None else added_volume_items,
    }


def _advanced_work(
    *,
    advanced_dimensions: list[str] | None = None,
    advanced_success_criteria: list[str] | None = None,
    shared_concept_ref: str = "concept-equivalence",
    common_synthesis_ref: str = "synthesis-equivalence-across-representations",
) -> dict[str, Any]:
    return {
        "advanced_dimensions": ["depth", "transfer"] if advanced_dimensions is None else advanced_dimensions,
        "advanced_success_criteria": (
            ["Explains why a chosen algorithmic shortcut works using place-value reasoning."]
            if advanced_success_criteria is None
            else advanced_success_criteria
        ),
        "shared_concept_ref": shared_concept_ref,
        "common_synthesis_ref": common_synthesis_ref,
    }


def _compacted_advanced_record(**overrides: Any) -> dict[str, Any]:
    return _base_record(
        pathway_type="compacted-advanced",
        compacting=overrides.pop("compacting", _compacting()),
        advanced_work=overrides.pop("advanced_work", _advanced_work()),
        **overrides,
    )


# ---------------------------------------------------------------------------
# Valid pathway designs (no learner assignment, no violations)
# ---------------------------------------------------------------------------


def test_valid_supported_pathway() -> None:
    result = validate_mixed_class_pathway(_base_record(pathway_type="supported"))
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    body = result.record.to_dict()
    assert body["pathway"]["pathway_type"] == "supported"
    assert body["compacting"] is None
    assert body["advanced_work"] is None
    assert body["learner_assignment"] is None
    assert body["teacher_review_required"] is True
    assert body["pacing_coordination_preserved"] is True
    assert body["blocked_reason_codes"] == []
    assert all(value is False for value in body["authority"].values())


def test_valid_core_pathway() -> None:
    result = validate_mixed_class_pathway(_base_record(pathway_type="core", record_id="pathway-2"))
    assert result.status is ValidationStatus.VALID
    assert result.record.to_dict()["pathway"]["pathway_type"] == "core"


def test_valid_compacted_advanced_pathway() -> None:
    result = validate_mixed_class_pathway(_compacted_advanced_record(record_id="pathway-3"))
    assert result.status is ValidationStatus.VALID
    body = result.record.to_dict()
    assert body["pathway"]["pathway_type"] == "compacted-advanced"
    assert body["compacting"]["mastered_work_removed"] == ["unit3-fraction-operations-practice-set"]
    assert body["advanced_work"]["advanced_dimensions"] == ["depth", "transfer"]
    assert body["blocked_reason_codes"] == []


def test_partial_compacting_with_identified_evidenced_subset_is_valid() -> None:
    """Removing only some mastered work is legitimate when what IS removed is
    identified and evidenced; compacting need not be all-or-nothing."""
    record = _compacted_advanced_record(
        record_id="pathway-4",
        compacting=_compacting(mastered_work_removed=["unit3-lesson2-practice-set"]),
    )
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.VALID


# ---------------------------------------------------------------------------
# Compacting eligibility and evidence rejections
# ---------------------------------------------------------------------------


def test_speed_only_eligibility_is_rejected() -> None:
    record = _compacted_advanced_record(compacting=_compacting(eligibility_basis=["speed"]))
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_SPEED_ONLY_ELIGIBILITY in result.blockers


def test_missing_objective_specific_evidence_is_rejected() -> None:
    record = _compacted_advanced_record(compacting=_compacting(objective_mastery_evidence=[]))
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_OBJECTIVE_MASTERY_EVIDENCE_MISSING in result.blockers


@pytest.mark.parametrize("status", ["stale", "privacy-blocked"])
def test_stale_or_privacy_blocked_evidence_does_not_count_as_current(status: str) -> None:
    record = _compacted_advanced_record(compacting=_compacting(objective_mastery_evidence=[_evidence(status)]))
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_OBJECTIVE_MASTERY_EVIDENCE_MISSING in result.blockers


def test_mastered_work_not_identified_is_rejected() -> None:
    record = _compacted_advanced_record(compacting=_compacting(mastered_work_removed=[]))
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_MASTERED_WORK_UNIDENTIFIED in result.blockers


def test_added_volume_masquerading_as_compacting_is_rejected() -> None:
    record = _compacted_advanced_record(
        compacting=_compacting(mastered_work_removed=[], added_volume_items=["extra-worksheet-set-4"])
    )
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_MASTERED_WORK_UNIDENTIFIED in result.blockers
    assert LP_PATHWAY_ADDED_VOLUME_NOT_COMPACTING in result.blockers


def test_extra_work_masquerading_as_advanced_work_is_rejected() -> None:
    """Mastered work is genuinely identified and evidenced, but the
    replacement work names no advanced dimension — it is just more of the
    same-level content relabelled as 'advanced'."""
    record = _compacted_advanced_record(advanced_work=_advanced_work(advanced_dimensions=[]))
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_ADVANCED_DIMENSION_ABSENT in result.blockers


def test_advanced_dimension_absent_is_rejected() -> None:
    record = _compacted_advanced_record(
        advanced_work=_advanced_work(advanced_dimensions=[], advanced_success_criteria=[])
    )
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_ADVANCED_DIMENSION_ABSENT in result.blockers


def test_unrelated_enrichment_is_rejected() -> None:
    record = _compacted_advanced_record(
        advanced_work=_advanced_work(shared_concept_ref="concept-unrelated-topic")
    )
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_EXTENSION_UNRELATED in result.blockers


def test_no_common_synthesis_is_rejected() -> None:
    record = _compacted_advanced_record(advanced_work=_advanced_work(common_synthesis_ref="none"))
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_EXTENSION_UNRELATED in result.blockers


# ---------------------------------------------------------------------------
# Grouping, accessibility, and re-entry
# ---------------------------------------------------------------------------


def test_fixed_or_permanent_grouping_is_rejected() -> None:
    result = validate_mixed_class_pathway(_base_record(grouping=_grouping(durable=True)))
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_FIXED_GROUPING_ATTEMPTED in result.blockers


def test_permanent_label_attempt_is_rejected_as_automatic_placement() -> None:
    record = _base_record(
        external_source=_external_source(
            kind="notion-export",
            notion_properties={"Permanent Label - Assigned Student": "Advanced Track — Alex R."},
        )
    )
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_AUTOMATIC_PLACEMENT_ATTEMPTED in result.blockers


def test_accessibility_omitted_is_rejected() -> None:
    result = validate_mixed_class_pathway(_base_record(accessibility=_accessibility(supports=[])))
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_ACCESSIBILITY_OR_REENTRY_UNRESOLVED in result.blockers


def test_reentry_omitted_is_rejected() -> None:
    result = validate_mixed_class_pathway(_base_record(accessibility=_accessibility(reentry_plan="none")))
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_ACCESSIBILITY_OR_REENTRY_UNRESOLVED in result.blockers


# ---------------------------------------------------------------------------
# Automatic placement, learner classification, and Notion-export offline input
# ---------------------------------------------------------------------------


def test_notion_export_shaped_record_implying_automatic_placement_is_rejected() -> None:
    record = _base_record(
        external_source=_external_source(
            kind="notion-export",
            notion_properties={"Assigned Student": "Jordan P.", "Unit": "Fractions"},
        )
    )
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_AUTOMATIC_PLACEMENT_ATTEMPTED in result.blockers


def test_student_identity_field_in_notion_export_is_rejected() -> None:
    record = _base_record(
        external_source=_external_source(
            kind="notion-export",
            notion_properties={"Student Name": "Jordan P."},
        )
    )
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_AUTOMATIC_PLACEMENT_ATTEMPTED in result.blockers


def test_protected_attribute_field_in_notion_export_is_rejected() -> None:
    record = _base_record(
        external_source=_external_source(
            kind="notion-export",
            notion_properties={"IEP Status": "Active"},
        )
    )
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.BLOCKED
    assert LP_PATHWAY_AUTOMATIC_PLACEMENT_ATTEMPTED in result.blockers


def test_notion_export_without_identifying_properties_is_accepted_as_offline_data() -> None:
    record = _base_record(
        external_source=_external_source(
            kind="notion-export",
            notion_properties={"Unit": "Fractions", "Term": "Fall"},
        )
    )
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.VALID
    assert result.record.to_dict()["external_source"]["kind"] == "notion-export"


def test_manual_source_with_notion_properties_is_structurally_rejected() -> None:
    record = _base_record(external_source={"kind": "manual", "notion_properties": {"Unit": "Fractions"}})
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.INVALID
    assert result.record is None


# ---------------------------------------------------------------------------
# Authority escalation, legacy records, and schema/version integrity
# ---------------------------------------------------------------------------


def test_authority_escalation_attempt_is_rejected() -> None:
    escalated = _authority()
    escalated["placement_authorized"] = True
    record = _base_record()
    record["authority"] = escalated
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("authority-invalid",)
    assert result.record is None


def test_teacher_review_cannot_be_overridden_by_supplied_evidence() -> None:
    """teacher_review_required is never a caller-supplied field; it is always
    fixed true in the emitted record regardless of what evidence is supplied."""
    record = _base_record()
    assert "teacher_review_required" not in record
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.VALID
    assert result.record.to_dict()["teacher_review_required"] is True

    escalated = _base_record()
    escalated["teacher_review_required"] = False
    escalation_result = validate_mixed_class_pathway(escalated)
    assert escalation_result.status is ValidationStatus.INVALID
    assert escalation_result.reason_codes == ("handoff-unknown-field",)


def test_schema_version_mismatch_is_rejected() -> None:
    record = _base_record()
    record["identity"]["contract_version"] = "instructional-workflow-mixed-class-pathway-v0"
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-version-unsupported",)


def test_legacy_unstructured_record_is_rejected_not_upgraded() -> None:
    legacy_record = {
        "notes": "Some kids finish early and do extra worksheets while others catch up.",
        "differentiation": "informal",
    }
    result = validate_mixed_class_pathway(legacy_record)
    assert result.status is ValidationStatus.INVALID
    assert result.record is None


def test_historical_unstructured_differentiation_field_is_not_silently_upgraded() -> None:
    """A record that is otherwise well-formed but carries a legacy free-text
    differentiation field must fail closed rather than have that prose
    silently reinterpreted as structured LP5 mastery evidence."""
    record = _base_record()
    record["differentiation_notes"] = (
        "Historically some students did extra fraction worksheets while others reviewed."
    )
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-unknown-field",)
    assert result.record is None


def test_compacted_advanced_pathway_requires_compacting_and_advanced_work() -> None:
    record = _base_record(pathway_type="compacted-advanced")
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.INVALID


def test_supported_pathway_may_not_supply_compacting() -> None:
    record = _base_record(pathway_type="supported", compacting=_compacting())
    result = validate_mixed_class_pathway(record)
    assert result.status is ValidationStatus.INVALID


# ---------------------------------------------------------------------------
# Determinism, purity, and no side effects
# ---------------------------------------------------------------------------


def test_result_is_deterministic_for_identical_input() -> None:
    record = _compacted_advanced_record()
    first = validate_mixed_class_pathway(copy.deepcopy(record))
    second = validate_mixed_class_pathway(copy.deepcopy(record))
    assert first.record.fingerprint == second.record.fingerprint


def test_malformed_input_fails_closed_without_raising() -> None:
    result = validate_mixed_class_pathway("not a mapping")
    assert result.status is ValidationStatus.INVALID
    assert result.record is None


# ---------------------------------------------------------------------------
# Import / reuse isolation: no forbidden external integrations are introduced
# ---------------------------------------------------------------------------


def test_import_reuse_isolation_introduces_no_forbidden_integration() -> None:
    """mixed_class_pathway.py must import only CW5A mechanics and the standard
    library; it must never import network, Notion, Drive, Sheets, LMS/SIS,
    model/OCR, or scheduler/publication machinery."""
    path = Path(__file__).parents[1] / "src" / "instructional_workflow_contracts" / "mixed_class_pathway.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.add(node.func.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            calls.add(node.func.attr)

    allowed = {"__future__", "re", "typing", "common", ""}
    assert imports <= allowed, imports - allowed

    forbidden_prefixes = (
        "requests",
        "httpx",
        "urllib.request",
        "subprocess",
        "importlib",
        "notion",
        "google",
        "workflow_scheduler",
        "navigation_registry",
        "sentence_transformers",
        "transformers",
        "torch",
        "paddle",
        "jsonschema",
        "pydantic",
    )
    assert not any(
        imported == forbidden or imported.startswith(forbidden + ".")
        for imported in imports
        for forbidden in forbidden_prefixes
    )
    assert calls.isdisjoint(
        {
            "open",
            "getenv",
            "environ",
            "Popen",
            "run",
            "system",
            "basicConfig",
            "register",
            "import_module",
            "eval",
            "exec",
        }
    )


def test_never_assigns_a_learner_across_every_pathway_type() -> None:
    for pathway_type in ("supported", "core"):
        result = validate_mixed_class_pathway(_base_record(pathway_type=pathway_type))
        assert result.record.to_dict()["learner_assignment"] is None
    result = validate_mixed_class_pathway(_compacted_advanced_record())
    assert result.record.to_dict()["learner_assignment"] is None
