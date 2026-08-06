from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

from instructional_workflow_contracts import ValidationStatus
from instructional_workflow_contracts.common import (
    FINGERPRINT_ALGORITHM,
    ValidatedRecord,
    freeze_json,
    sha256_hex,
)
from instructional_workflow_contracts.cohesive_visual_plan import (
    CONTRACT_ID,
    plan_cohesive_visual_set,
)
from instructional_workflow_contracts.visual_asset_candidates import (
    V2_CONTRACT_ID,
    filter_approved_visual_candidates,
)
from instructional_workflow_contracts.visual_needs import plan_visual_needs

FIXTURES = Path(__file__).parent / "fixtures" / "instructional_workflow_contracts"
PLAN_MODULE = (
    Path(__file__).parents[1]
    / "src"
    / "instructional_workflow_contracts"
    / "cohesive_visual_plan.py"
)


def _load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _plan() -> ValidatedRecord:
    result = plan_visual_needs(_load("valid_material_requirement_v2.json"))
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    return result.record


def _candidate_result() -> ValidatedRecord:
    result = filter_approved_visual_candidates(
        _plan(),
        [_load("valid_visual_asset_compatibility_v2.json")],
        source_revision="visual-library-snapshot-v2",
        contract_version=V2_CONTRACT_ID,
    )
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    return result.record


def _record(
    payload: dict[str, object],
    *,
    contract_version: str,
    record_id: str,
) -> ValidatedRecord:
    return ValidatedRecord(
        contract_version=contract_version,
        record_id=record_id,
        record_revision=1,
        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
        fingerprint=sha256_hex(payload),
        payload=freeze_json(payload),
    )


def _plan_record(payload: dict[str, object]) -> ValidatedRecord:
    return _record(
        payload,
        contract_version="curriculum-visual-needs-plan-v1",
        record_id=payload["plan_id"],  # type: ignore[arg-type]
    )


def _candidate_record(payload: dict[str, object]) -> ValidatedRecord:
    return _record(
        payload,
        contract_version=V2_CONTRACT_ID,
        record_id=payload["candidate_set_id"],  # type: ignore[arg-type]
    )


def _second_candidate_for(
    candidate: dict[str, object],
    role_type: str,
    orientation: str,
) -> dict[str, object]:
    item = copy.deepcopy(candidate)
    item["compatibility_id"] = f"visual-compatibility-{role_type}"
    item["fingerprint"] = sha256_hex(
        {"role_type": role_type, "orientation": orientation}
    )
    item["asset_reference"] = {
        "asset_id": f"asset-{role_type}",
        "stable_ref": f"asset-ref-{role_type}",
        "content_fingerprint": sha256_hex({"asset": role_type}),
    }
    item["library_reference"] = {
        "page_id": f"page-{role_type}",
        "drive_file_id": f"file-{role_type}",
    }
    item["manifest_reference"] = {
        "manifest_id": f"manifest-{role_type}",
        "record_revision": 1,
        "fingerprint": sha256_hex({"manifest": role_type}),
        "verified_at": "2026-07-30T00:00:00Z",
        "external_file_id": f"file-{role_type}",
    }
    item["matched_asset"] = {
        "asset_id": f"asset-{role_type}",
        "stable_ref": f"asset-ref-{role_type}",
        "content_fingerprint": sha256_hex({"asset": role_type}),
        "duplicate_relationship": "unique",
        "disposition": "canonical",
        "canonical_asset_ref": None,
        "duplicate_group_id": None,
        "required_context_flags": [],
        "preserved_context_flags": [],
        "context_preservation_complete": True,
        "direct_use_status": "student-ready",
        "repair_source_status": "not-needed",
        "replacement_required": False,
    }
    item["purpose"]["role_types"] = [role_type]  # type: ignore[index]
    item["approved_use"]["role_types"] = [role_type]  # type: ignore[index]
    item["orientation"]["orientation"] = orientation  # type: ignore[index]
    return item


def test_complete_set_selects_required_role_and_leaves_optional_unfilled() -> None:
    result = plan_cohesive_visual_set(_plan(), _candidate_result())

    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["contract_version"] == CONTRACT_ID
    assert payload["outcome"] == "complete-set"
    assert len(payload["required_role_assignments"]) == 1
    assert payload["optional_role_assignments"] == []
    assert payload["unfilled_required_roles"] == []
    assert len(payload["unfilled_optional_roles"]) == 1
    assert payload["image_gap_briefs"] == []
    assert payload["authority"] == {
        "execution_authorized": False,
        "external_write_authorized": False,
        "production_authorized": False,
        "publication_authorized": False,
        "side_effects_performed": False,
    }


def test_multiple_required_roles_receive_compatible_candidates() -> None:
    plan_payload = _plan().to_dict()
    optional = copy.deepcopy(plan_payload["optional_roles"][0])
    optional["requirement_state"] = "required"
    plan_payload["required_roles"] = [plan_payload["required_roles"][0], optional]
    plan_payload["optional_roles"] = []
    plan_payload["maximum_visual_count"] = 2
    plan_payload["cognitive_load_ceiling"] = 4
    plan_payload["plan_id"] = "visual-needs-plan-multi-required"

    candidate_payload = _candidate_result().to_dict()
    candidate_payload["visual_needs_plan"] = {
        "contract_version": plan_payload["contract_version"],
        "plan_id": plan_payload["plan_id"],
        "record_revision": 1,
        "fingerprint": sha256_hex(plan_payload),
    }
    first = candidate_payload["eligible"][0]
    candidate_payload["eligible"] = [
        first,
        _second_candidate_for(first, "comparison", "square"),
    ]

    result = plan_cohesive_visual_set(
        _plan_record(plan_payload),
        _candidate_record(candidate_payload),
    )

    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["outcome"] == "complete-set"
    assert len(payload["required_role_assignments"]) == 2
    assert payload["unfilled_required_roles"] == []


def test_unfilled_required_role_produces_one_vendor_neutral_gap_brief() -> None:
    candidate_payload = _candidate_result().to_dict()
    candidate_payload["eligible"][0]["purpose"]["role_types"] = ["comparison"]
    candidate_payload["eligible"][0]["approved_use"]["role_types"] = ["comparison"]

    result = plan_cohesive_visual_set(
        _plan(),
        _candidate_record(candidate_payload),
    )

    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["outcome"] == "partial-set"
    assert len(payload["unfilled_required_roles"]) == 1
    assert len(payload["image_gap_briefs"]) == 1
    brief = payload["image_gap_briefs"][0]
    assert brief["human_review_required"] is True
    assert brief["required_visual_style_family"] == "unspecified"
    assert brief["authority"]["side_effects_performed"] is False


def test_equal_candidate_tie_routes_to_manual_review() -> None:
    candidate_payload = _candidate_result().to_dict()
    first = candidate_payload["eligible"][0]
    tied = _second_candidate_for(first, "worked-example", "landscape")
    tied["cohesion_profile"] = copy.deepcopy(first["cohesion_profile"])
    candidate_payload["eligible"] = [first, tied]

    result = plan_cohesive_visual_set(
        _plan(),
        _candidate_record(candidate_payload),
    )

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.record is not None
    assert result.reason_codes == ("manual-review-visual-assignment-tie",)
    assert result.record.to_dict()["outcome"] == "manual-review-required"


def test_canonical_asset_wins_over_alternate_tie() -> None:
    candidate_payload = _candidate_result().to_dict()
    first = candidate_payload["eligible"][0]
    alternate = _second_candidate_for(first, "worked-example", "landscape")
    alternate["cohesion_profile"] = copy.deepcopy(first["cohesion_profile"])
    alternate["matched_asset"]["disposition"] = "alternate"
    alternate["matched_asset"]["canonical_asset_ref"] = "asset-ref-1"
    candidate_payload["eligible"] = [alternate, first]

    result = plan_cohesive_visual_set(
        _plan(),
        _candidate_record(candidate_payload),
    )

    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    selected = result.record.to_dict()["required_role_assignments"][0][
        "selected_candidate"
    ]
    assert selected["asset_reference"]["stable_ref"] == "asset-ref-1"


def test_manual_review_candidate_filter_evidence_controls_result_status() -> None:
    candidate_payload = _candidate_result().to_dict()
    candidate_payload["manual_review"] = [
        {
            "compatibility_contract_version": "curriculum-visual-asset-compatibility-v2",
            "compatibility_id": "visual-compatibility-review",
            "compatibility_record_revision": 1,
            "fingerprint": "f" * 64,
            "classification": "manual-review-required",
            "reason_codes": ["manual-review-asset-audience"],
        }
    ]

    result = plan_cohesive_visual_set(
        _plan(),
        _candidate_record(candidate_payload),
    )

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.reason_codes == ("manual-review-visual-candidates",)


def test_mismatched_candidate_plan_binding_is_invalid() -> None:
    candidate_payload = _candidate_result().to_dict()
    candidate_payload["visual_needs_plan"]["plan_id"] = "other-plan"

    result = plan_cohesive_visual_set(
        _plan(),
        _candidate_record(candidate_payload),
    )

    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("identity-invalid",)


def test_non_v2_candidate_contract_is_rejected() -> None:
    record = _candidate_result()
    incompatible = ValidatedRecord(
        contract_version="curriculum-visual-asset-candidates-v1",
        record_id=record.record_id,
        record_revision=1,
        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
        fingerprint=record.fingerprint,
        payload=record.payload,
    )

    result = plan_cohesive_visual_set(_plan(), incompatible)

    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("asset-cohesive-plan-incompatible-candidates",)


def test_cohesive_plan_module_has_no_prohibited_operations() -> None:
    source = PLAN_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    prohibited_imports = {
        "requests",
        "urllib",
        "socket",
        "httpx",
        "openai",
        "anthropic",
        "google.genai",
        "PIL",
        "cv2",
        "torch",
        "tensorflow",
        "subprocess",
    }
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported |= {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not {
        name
        for name in imported
        if any(
            name == prohibited or name.startswith(prohibited + ".")
            for prohibited in prohibited_imports
        )
    }

    prohibited_calls = {
        "open",
        "rank",
        "embed",
        "ocr",
        "decode_image",
        "generate_image",
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    called |= {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not called & prohibited_calls
