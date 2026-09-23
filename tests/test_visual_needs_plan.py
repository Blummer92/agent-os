from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

import instructional_workflow_contracts.visual_needs as visual_module
from instructional_workflow_contracts import (
    AuthorityEvidence,
    ValidationStatus,
    canonical_size,
)
from instructional_workflow_contracts.material_requirement import (
    material_requirement_source_fingerprint,
    validate_material_requirement,
)

FIXTURES = Path(__file__).parent / "fixtures" / "instructional_workflow_contracts"
MODULE = (
    Path(__file__).parents[1]
    / "src"
    / "instructional_workflow_contracts"
    / "visual_needs.py"
)


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def refresh(value: dict[str, object]) -> None:
    value["identity"]["source_fingerprint"] = (  # type: ignore[index]
        material_requirement_source_fingerprint(value)
    )


def v2_direction(
    *,
    decision: str,
    maximum_visual_count: int,
    roles: list[dict[str, object]],
) -> dict[str, object]:
    value = fixture("valid_material_requirement_v2.json")
    value["visual_direction"] = {
        "decision": decision,
        "maximum_visual_count": maximum_visual_count,
        "roles": roles,
    }
    refresh(value)
    return value


def test_valid_v1_routes_to_manual_review_without_inventing_roles() -> None:
    result = visual_module.plan_visual_needs(
        fixture("valid_material_requirement.json")
    )

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.reason_codes == ("manual-review-material-requirement-v1",)
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["outcome"] == "manual-review-required"
    assert payload["source_visual_decision"] is None
    assert payload["required_roles"] == []
    assert payload["optional_roles"] == []
    assert payload["maximum_visual_count"] == 0


@pytest.mark.parametrize(
    ("case_name", "expected_status", "expected_reason"),
    [
        (
            "unspecified",
            ValidationStatus.MANUAL_REVIEW_REQUIRED,
            "manual-review-visual-direction-unspecified",
        ),
        ("no-visuals", ValidationStatus.VALID, None),
    ],
)
def test_fixture_backed_non_retrieval_outcomes(
    case_name: str,
    expected_status: ValidationStatus,
    expected_reason: str | None,
) -> None:
    cases = fixture("visual_needs_cases.json")
    case = cases[case_name]  # type: ignore[index]
    value = v2_direction(
        decision=case["decision"],  # type: ignore[index]
        maximum_visual_count=case["maximum_visual_count"],  # type: ignore[index]
        roles=case["roles"],  # type: ignore[index]
    )

    result = visual_module.plan_visual_needs(value)

    assert result.status is expected_status
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["outcome"] == case["expected_outcome"]  # type: ignore[index]
    assert payload["required_roles"] == []
    assert payload["optional_roles"] == []
    assert payload["maximum_visual_count"] == 0
    if expected_reason is None:
        assert result.reason_codes == ()
    else:
        assert result.reason_codes == (expected_reason,)


def test_visuals_required_produces_governed_required_and_optional_roles() -> None:
    result = visual_module.plan_visual_needs(
        fixture("valid_material_requirement_v2.json")
    )

    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["outcome"] == "visuals-required"
    assert payload["source_visual_decision"] == "visuals-required"
    assert payload["maximum_visual_count"] == 2
    assert payload["cognitive_load_ceiling"] == 2
    assert payload["accessibility_requirements"] == [
        "keyboard-readable",
        "plain-language",
    ]
    assert [role["role_type"] for role in payload["required_roles"]] == [
        "worked-example"
    ]
    assert [role["role_type"] for role in payload["optional_roles"]] == [
        "comparison"
    ]
    all_roles = payload["required_roles"] + payload["optional_roles"]
    assert len({role["role_id"] for role in all_roles}) == 2
    assert all(
        role["accessibility_reference"]
        == "requirements.accessibility_requirements"
        for role in all_roles
    )
    assert all(
        role["requirement_state"] == "required"
        for role in payload["required_roles"]
    )
    assert all(
        role["requirement_state"] == "optional"
        for role in payload["optional_roles"]
    )


def test_raw_result_and_record_inputs_reconstruct_exactly() -> None:
    value = fixture("valid_material_requirement_v2.json")
    validated = validate_material_requirement(copy.deepcopy(value))
    assert validated.record is not None

    raw = visual_module.plan_visual_needs(copy.deepcopy(value))
    from_result = visual_module.plan_visual_needs(validated)
    from_record = visual_module.plan_visual_needs(validated.record)

    assert raw.record is not None
    assert from_result.record is not None
    assert from_record.record is not None
    assert raw.record.fingerprint == from_result.record.fingerprint
    assert raw.record.fingerprint == from_record.record.fingerprint
    assert raw.record.to_dict() == from_result.record.to_dict()
    assert raw.record.to_dict() == from_record.record.to_dict()


def test_repeated_input_is_deterministic_and_immutable() -> None:
    value = fixture("valid_material_requirement_v2.json")
    before = copy.deepcopy(value)

    first = visual_module.plan_visual_needs(value)
    second = visual_module.plan_visual_needs(copy.deepcopy(value))

    assert first.record is not None and second.record is not None
    assert first.record.fingerprint == second.record.fingerprint
    assert first.record.record_id == second.record.record_id
    assert first.record.to_dict() == second.record.to_dict()
    assert value == before


def test_free_form_visual_language_cannot_create_roles() -> None:
    value = v2_direction(
        decision="unspecified",
        maximum_visual_count=0,
        roles=[],
    )
    value["artifact"]["subject_metadata"] = (  # type: ignore[index]
        "engaging visual process model"
    )
    value["instructional"]["purpose"] = (  # type: ignore[index]
        "Use a visual example and decorative images."
    )
    refresh(value)

    upstream = validate_material_requirement(copy.deepcopy(value))
    assert upstream.status is ValidationStatus.VALID

    result = visual_module.plan_visual_needs(value)

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["required_roles"] == []
    assert payload["optional_roles"] == []


def test_manual_review_sentinel_material_type_never_authorizes_roles() -> None:
    value = fixture("valid_material_requirement_v2.json")
    value["artifact"]["artifact_type"] = (  # type: ignore[index]
        "unsupported-manual-review"
    )
    refresh(value)

    result = visual_module.plan_visual_needs(value)

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.reason_codes == ("manual-review-unsupported-material-type",)
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["outcome"] == "manual-review-required"
    assert payload["source_visual_decision"] == "visuals-required"
    assert payload["required_roles"] == []
    assert payload["optional_roles"] == []
    assert payload["maximum_visual_count"] == 0


def test_eight_role_boundary_is_supported_and_ninth_role_fails_closed() -> None:
    role_types = [
        "teacher-model",
        "worked-example",
        "non-example",
        "process-sequence",
        "comparison",
        "annotated-evidence",
        "navigation-orientation",
        "accessibility-support",
        "repeated-reference",
    ]
    roles = [
        {
            "role_type": role_type,
            "requirement_state": "required" if index == 0 else "optional",
            "instructional_purpose": f"Instructional purpose {index}.",
            "intended_placement": "section",
            "orientation": "unspecified",
        }
        for index, role_type in enumerate(role_types)
    ]

    supported = v2_direction(
        decision="visuals-required",
        maximum_visual_count=8,
        roles=roles[:8],
    )
    supported_result = visual_module.plan_visual_needs(supported)
    assert supported_result.status is ValidationStatus.VALID
    assert supported_result.record is not None
    supported_payload = supported_result.record.to_dict()
    assert len(supported_payload["required_roles"]) == 1
    assert len(supported_payload["optional_roles"]) == 7

    oversized = v2_direction(
        decision="visuals-required",
        maximum_visual_count=8,
        roles=roles,
    )
    assert visual_module.plan_visual_needs(oversized).status is ValidationStatus.INVALID


def test_malformed_and_invalid_upstream_inputs_fail_closed() -> None:
    assert visual_module.plan_visual_needs(None).status is ValidationStatus.INVALID

    malformed = fixture("valid_material_requirement_v2.json")
    malformed["visual_direction"]["maximum_visual_count"] = True  # type: ignore[index]
    refresh(malformed)
    result = visual_module.plan_visual_needs(malformed)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("material-visual-needs-invalid-upstream",)

    upstream = validate_material_requirement(None)
    result = visual_module.plan_visual_needs(upstream)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("material-visual-needs-invalid-upstream",)


def test_authority_is_always_false_and_result_is_bounded() -> None:
    for value in (
        fixture("valid_material_requirement.json"),
        fixture("valid_material_requirement_v2.json"),
        v2_direction(decision="no-visuals", maximum_visual_count=0, roles=[]),
    ):
        result = visual_module.plan_visual_needs(value)
        assert result.authority == AuthorityEvidence()
        assert result.record is not None
        payload = result.record.to_dict()
        assert not any(payload["authority"].values())
        assert canonical_size(payload) <= visual_module.MAX_RESULT_BYTES


def test_planner_module_has_no_external_or_image_operation_imports() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    forbidden = (
        "requests",
        "httpx",
        "urllib",
        "subprocess",
        "socket",
        "notion",
        "google",
        "PIL",
        "cv2",
        "torch",
        "transformers",
        "sentence_transformers",
    )
    assert not [name for name in imports if name.startswith(forbidden)]
