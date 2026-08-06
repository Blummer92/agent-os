from __future__ import annotations

import ast
import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from instructional_workflow_contracts import ValidationStatus
from instructional_workflow_contracts.material_requirement import (
    material_requirement_source_fingerprint,
)
from instructional_workflow_contracts.visual_asset_candidates import (
    MAX_CANDIDATES,
    V1_CONTRACT_ID,
    V2_CONTRACT_ID,
    filter_approved_visual_candidates,
)
from instructional_workflow_contracts.visual_asset_compatibility import (
    V1_CONTRACT_ID as V1_COMPATIBILITY_CONTRACT_ID,
    V2_CONTRACT_ID as V2_COMPATIBILITY_CONTRACT_ID,
    validate_visual_asset_compatibility_evidence,
)
from instructional_workflow_contracts.visual_needs import plan_visual_needs

FIXTURES = Path(__file__).parent / "fixtures" / "instructional_workflow_contracts"
CANDIDATE_MODULE = (
    Path(__file__).parents[1]
    / "src"
    / "instructional_workflow_contracts"
    / "visual_asset_candidates.py"
)


def _load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _plan():
    result = plan_visual_needs(_load("valid_material_requirement_v2.json"))
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    return result.record


def _compatibility() -> dict[str, object]:
    return _load("valid_visual_asset_compatibility.json")


def _compatibility_v2() -> dict[str, object]:
    return _load("valid_visual_asset_compatibility_v2.json")


def _mutate(value: dict[str, object], path: list[str], replacement: object) -> None:
    cursor: object = value
    for key in path[:-1]:
        assert isinstance(cursor, dict)
        cursor = cursor[key]
    assert isinstance(cursor, dict)
    cursor[path[-1]] = replacement


def test_valid_candidate_is_eligible_and_deterministic() -> None:
    candidate = _compatibility()
    before = copy.deepcopy(candidate)

    first = filter_approved_visual_candidates(
        _plan(),
        [candidate],
        source_revision="visual-library-snapshot-v1",
    )
    second = filter_approved_visual_candidates(
        _plan(),
        [copy.deepcopy(candidate)],
        source_revision="visual-library-snapshot-v1",
    )

    assert first.status is ValidationStatus.VALID
    assert first.record is not None
    assert second.record is not None
    payload = first.record.to_dict()
    assert payload["candidate_count"] == 1
    assert len(payload["eligible"]) == 1
    assert payload["rejected"] == []
    assert payload["manual_review"] == []
    assert first.record.fingerprint == second.record.fingerprint
    assert first.record.record_id == second.record.record_id
    assert candidate == before
    assert payload["authority"] == {
        "execution_authorized": False,
        "external_write_authorized": False,
        "production_authorized": False,
        "publication_authorized": False,
        "side_effects_performed": False,
    }


def test_fixture_cases_route_to_expected_groups() -> None:
    matrix = _load("visual_asset_candidate_cases.json")
    source_revision = matrix["source_revision"]
    assert isinstance(source_revision, str)

    for case in matrix["cases"]:
        candidate = _compatibility()
        mutation = case["mutation"]
        if mutation is not None:
            _mutate(candidate, mutation["path"], mutation["value"])

        result = filter_approved_visual_candidates(
            _plan(),
            [candidate],
            source_revision=source_revision,
        )
        assert result.record is not None, case["name"]
        payload = result.record.to_dict()
        group = case["expected_group"]
        assert len(payload[group]) == 1, case["name"]
        if group == "manual_review":
            assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
        else:
            assert result.status is ValidationStatus.VALID
        if "expected_reason" in case:
            assert case["expected_reason"] in payload[group][0]["reason_codes"]


def test_manual_review_candidate_controls_result_status() -> None:
    candidate = _compatibility()
    candidate["compatibility_evidence"]["freshness"]["stale"] = True  # type: ignore[index]

    result = filter_approved_visual_candidates(
        _plan(),
        [candidate],
        source_revision="visual-library-snapshot-v1",
    )

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.reason_codes == ("manual-review-visual-candidates",)


def test_invalid_candidate_is_rejected_without_aborting_batch() -> None:
    invalid = _compatibility()
    invalid["compatibility_evidence"]["unexpected"] = True  # type: ignore[index]

    result = filter_approved_visual_candidates(
        _plan(),
        [_compatibility(), invalid],
        source_revision="visual-library-snapshot-v1",
    )

    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    payload = result.record.to_dict()
    assert len(payload["eligible"]) == 1
    assert len(payload["rejected"]) == 1
    assert payload["rejected"][0]["classification"] == "invalid"


def test_candidate_order_does_not_change_result_identity() -> None:
    eligible = _compatibility()
    rejected = _compatibility()
    rejected["compatibility_evidence"]["accessibility"]["review_state"] = "fail"  # type: ignore[index]

    forward = filter_approved_visual_candidates(
        _plan(),
        [eligible, rejected],
        source_revision="visual-library-snapshot-v1",
    )
    reverse = filter_approved_visual_candidates(
        _plan(),
        [rejected, eligible],
        source_revision="visual-library-snapshot-v1",
    )

    assert forward.record is not None
    assert reverse.record is not None
    assert forward.record.fingerprint == reverse.record.fingerprint
    assert forward.record.record_id == reverse.record.record_id


def test_source_revision_is_required_and_identity_bound() -> None:
    first = filter_approved_visual_candidates(
        _plan(),
        [_compatibility()],
        source_revision="revision-1",
    )
    second = filter_approved_visual_candidates(
        _plan(),
        [_compatibility()],
        source_revision="revision-2",
    )

    assert first.record is not None
    assert second.record is not None
    assert first.record.record_id != second.record.record_id

    invalid = filter_approved_visual_candidates(
        _plan(),
        [_compatibility()],
        source_revision="",
    )
    assert invalid.status is ValidationStatus.INVALID


def test_candidate_count_is_bounded() -> None:
    result = filter_approved_visual_candidates(
        _plan(),
        [_compatibility() for _ in range(MAX_CANDIDATES + 1)],
        source_revision="visual-library-snapshot-v1",
    )

    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-oversized",)


@pytest.mark.parametrize("value", [None, (), {}, "candidate"])
def test_candidates_require_a_builtin_list(value: object) -> None:
    result = filter_approved_visual_candidates(
        _plan(),
        value,
        source_revision="visual-library-snapshot-v1",
    )
    assert result.status is ValidationStatus.INVALID


def test_non_actionable_plan_is_rejected() -> None:
    requirement = _load("valid_material_requirement_v2.json")
    requirement["visual_direction"] = {  # type: ignore[index]
        "decision": "no-visuals",
        "maximum_visual_count": 0,
        "roles": [],
    }
    requirement["identity"]["source_fingerprint"] = (  # type: ignore[index]
        material_requirement_source_fingerprint(requirement)
    )
    plan = plan_visual_needs(requirement)
    assert plan.record is not None

    result = filter_approved_visual_candidates(
        plan.record,
        [],
        source_revision="visual-library-snapshot-v1",
    )

    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("asset-candidates-plan-not-actionable",)


def test_plain_plan_mapping_is_not_trusted() -> None:
    result = filter_approved_visual_candidates(
        _plan().to_dict(),
        [_compatibility()],
        source_revision="visual-library-snapshot-v1",
    )
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("asset-candidates-invalid-plan",)



def test_explicit_v1_selection_preserves_default_output_exactly() -> None:
    candidate = _compatibility()

    default = filter_approved_visual_candidates(
        _plan(),
        [candidate],
        source_revision="visual-library-snapshot-v1",
    )
    explicit = filter_approved_visual_candidates(
        _plan(),
        [copy.deepcopy(candidate)],
        source_revision="visual-library-snapshot-v1",
        contract_version=V1_CONTRACT_ID,
    )

    assert default.status is explicit.status is ValidationStatus.VALID
    assert default.record is not None
    assert explicit.record is not None
    assert default.record.contract_version == V1_CONTRACT_ID
    assert explicit.record.contract_version == V1_CONTRACT_ID
    assert default.record.record_id == explicit.record.record_id
    assert default.record.fingerprint == explicit.record.fingerprint
    assert default.record.to_dict() == explicit.record.to_dict()
    entry = default.record.to_dict()["eligible"][0]
    assert set(entry) == {
        "compatibility_id",
        "fingerprint",
        "classification",
        "reason_codes",
        "asset_reference",
        "library_reference",
    }


def test_valid_v2_candidate_preserves_exact_validated_projection() -> None:
    candidate = _compatibility_v2()
    before = copy.deepcopy(candidate)
    compatibility = validate_visual_asset_compatibility_evidence(candidate)
    assert compatibility.status is ValidationStatus.VALID
    assert compatibility.record is not None
    compatibility_payload = compatibility.record.to_dict()

    first = filter_approved_visual_candidates(
        _plan(),
        [candidate],
        source_revision="visual-library-snapshot-v2",
        contract_version=V2_CONTRACT_ID,
    )
    second = filter_approved_visual_candidates(
        _plan(),
        [copy.deepcopy(candidate)],
        source_revision="visual-library-snapshot-v2",
        contract_version=V2_CONTRACT_ID,
    )

    assert first.status is ValidationStatus.VALID
    assert first.record is not None
    assert second.record is not None
    assert first.record.contract_version == V2_CONTRACT_ID
    assert first.record.record_id == second.record.record_id
    assert first.record.fingerprint == second.record.fingerprint
    assert first.record.to_dict() == second.record.to_dict()
    assert candidate == before

    payload = first.record.to_dict()
    plan = _plan()
    assert payload["contract_version"] == V2_CONTRACT_ID
    assert payload["visual_needs_plan"] == {
        "contract_version": plan.contract_version,
        "plan_id": plan.record_id,
        "record_revision": plan.record_revision,
        "fingerprint": plan.fingerprint,
    }
    assert payload["rejected"] == []
    assert payload["manual_review"] == []
    assert len(payload["eligible"]) == 1

    entry = payload["eligible"][0]
    assert set(entry) == {
        "compatibility_contract_version",
        "compatibility_id",
        "compatibility_record_revision",
        "fingerprint",
        "classification",
        "reason_codes",
        "manifest_reference",
        "asset_reference",
        "library_reference",
        "purpose",
        "approved_use",
        "orientation",
        "accessibility",
        "freshness",
        "matched_asset",
        "cohesion_profile",
        "authority",
    }
    assert entry["compatibility_contract_version"] == (
        V2_COMPATIBILITY_CONTRACT_ID
    )
    assert entry["compatibility_id"] == compatibility.record.record_id
    assert entry["compatibility_record_revision"] == (
        compatibility.record.record_revision
    )
    assert entry["fingerprint"] == compatibility.record.fingerprint
    for field in (
        "manifest_reference",
        "asset_reference",
        "library_reference",
        "purpose",
        "approved_use",
        "orientation",
        "accessibility",
        "freshness",
        "matched_asset",
        "cohesion_profile",
        "authority",
    ):
        assert entry[field] == compatibility_payload[field]

    assert entry["matched_asset"] == {
        "asset_id": "asset-1",
        "stable_ref": "asset-ref-1",
        "content_fingerprint": "c" * 64,
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
    assert entry["authority"] == payload["authority"] == {
        "execution_authorized": False,
        "external_write_authorized": False,
        "production_authorized": False,
        "publication_authorized": False,
        "side_effects_performed": False,
    }


def test_candidate_versions_do_not_convert_compatibility_records() -> None:
    v2_in_v1 = filter_approved_visual_candidates(
        _plan(),
        [_compatibility_v2()],
        source_revision="visual-library-snapshot-v2",
    )
    assert v2_in_v1.status is ValidationStatus.VALID
    assert v2_in_v1.record is not None
    v2_in_v1_payload = v2_in_v1.record.to_dict()
    assert v2_in_v1_payload["contract_version"] == V1_CONTRACT_ID
    assert v2_in_v1_payload["eligible"] == []
    assert v2_in_v1_payload["rejected"][0]["reason_codes"] == [
        "visual-candidate-contract-incompatible"
    ]

    v1_in_v2 = filter_approved_visual_candidates(
        _plan(),
        [_compatibility()],
        source_revision="visual-library-snapshot-v1",
        contract_version=V2_CONTRACT_ID,
    )
    assert v1_in_v2.status is ValidationStatus.VALID
    assert v1_in_v2.record is not None
    v1_in_v2_payload = v1_in_v2.record.to_dict()
    assert v1_in_v2_payload["contract_version"] == V2_CONTRACT_ID
    assert v1_in_v2_payload["eligible"] == []
    assert v1_in_v2_payload["rejected"][0]["reason_codes"] == [
        "visual-candidate-contract-incompatible"
    ]
    assert v1_in_v2_payload["rejected"][0][
        "compatibility_contract_version"
    ] == V1_COMPATIBILITY_CONTRACT_ID


@pytest.mark.parametrize(
    ("contract_version", "expected_reason"),
    [
        (None, "handoff-wrong-type"),
        (2, "handoff-wrong-type"),
        (
            "curriculum-visual-asset-candidates-v3",
            "handoff-version-unsupported",
        ),
    ],
)
def test_candidate_contract_version_fails_closed(
    contract_version: object,
    expected_reason: str,
) -> None:
    result = filter_approved_visual_candidates(
        _plan(),
        [_compatibility_v2()],
        source_revision="visual-library-snapshot-v2",
        contract_version=contract_version,
    )

    assert result.status is ValidationStatus.INVALID
    assert result.record is None
    assert result.reason_codes == (expected_reason,)


def test_v2_fixture_cases_route_to_expected_groups() -> None:
    matrix = _load("visual_asset_candidate_v2_cases.json")
    assert matrix["contract_version"] == V2_CONTRACT_ID
    source_revision = matrix["source_revision"]
    assert isinstance(source_revision, str)

    for case in matrix["cases"]:
        candidate = _compatibility_v2()
        mutation = case["mutation"]
        if mutation is not None:
            _mutate(candidate, mutation["path"], mutation["value"])

        result = filter_approved_visual_candidates(
            _plan(),
            [candidate],
            source_revision=source_revision,
            contract_version=V2_CONTRACT_ID,
        )
        assert result.record is not None, case["name"]
        payload = result.record.to_dict()
        group = case["expected_group"]
        assert len(payload[group]) == 1, case["name"]
        if group == "manual_review":
            assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED, (
                case["name"]
            )
        else:
            assert result.status is ValidationStatus.VALID, case["name"]
        if "expected_reason" in case:
            assert case["expected_reason"] in payload[group][0][
                "reason_codes"
            ]


def test_v2_candidate_order_does_not_change_identity() -> None:
    eligible = _compatibility_v2()
    rejected = _compatibility_v2()
    rejected["compatibility_evidence"]["cohesion_profile"][  # type: ignore[index]
        "audience_compatibility"
    ]["state"] = "rejected"

    forward = filter_approved_visual_candidates(
        _plan(),
        [eligible, rejected],
        source_revision="visual-library-snapshot-v2",
        contract_version=V2_CONTRACT_ID,
    )
    reverse = filter_approved_visual_candidates(
        _plan(),
        [rejected, eligible],
        source_revision="visual-library-snapshot-v2",
        contract_version=V2_CONTRACT_ID,
    )

    assert forward.record is not None
    assert reverse.record is not None
    assert forward.record.record_id == reverse.record.record_id
    assert forward.record.fingerprint == reverse.record.fingerprint
    assert forward.record.to_dict() == reverse.record.to_dict()


def test_v2_same_reason_invalid_envelopes_are_order_independent() -> None:
    first_invalid = "not-a-visual-candidate-envelope"
    second_invalid = 12345

    forward = filter_approved_visual_candidates(
        _plan(),
        [first_invalid, second_invalid],
        source_revision="visual-library-snapshot-v2",
        contract_version=V2_CONTRACT_ID,
    )
    reverse = filter_approved_visual_candidates(
        _plan(),
        [second_invalid, first_invalid],
        source_revision="visual-library-snapshot-v2",
        contract_version=V2_CONTRACT_ID,
    )

    assert forward.record is not None
    assert reverse.record is not None
    forward_payload = forward.record.to_dict()
    reverse_payload = reverse.record.to_dict()
    assert len(forward_payload["rejected"]) == 2
    assert forward.record.record_id == reverse.record.record_id
    assert forward.record.fingerprint == reverse.record.fingerprint
    assert forward_payload == reverse_payload


def test_v2_invalid_candidate_does_not_corrupt_valid_sibling() -> None:
    invalid = _compatibility_v2()
    invalid["compatibility_evidence"]["cohesion_profile"][  # type: ignore[index]
        "medium"
    ] = "unsupported-medium"

    result = filter_approved_visual_candidates(
        _plan(),
        [_compatibility_v2(), invalid],
        source_revision="visual-library-snapshot-v2",
        contract_version=V2_CONTRACT_ID,
    )

    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    payload = result.record.to_dict()
    assert len(payload["eligible"]) == 1
    assert len(payload["rejected"]) == 1
    assert payload["rejected"][0]["classification"] == "invalid"
    assert payload["rejected"][0]["reason_codes"] == [
        "asset-compatibility-invalid"
    ]


def test_v2_plan_fingerprint_is_revalidated() -> None:
    plan = _plan()
    tampered = replace(plan, fingerprint="f" * 64)

    result = filter_approved_visual_candidates(
        tampered,
        [_compatibility_v2()],
        source_revision="visual-library-snapshot-v2",
        contract_version=V2_CONTRACT_ID,
    )

    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("asset-candidates-invalid-plan",)


def test_v2_oversized_projection_fails_closed() -> None:
    result = filter_approved_visual_candidates(
        _plan(),
        [_compatibility_v2() for _ in range(MAX_CANDIDATES)],
        source_revision="visual-library-snapshot-v2",
        contract_version=V2_CONTRACT_ID,
    )

    assert result.status is ValidationStatus.INVALID
    assert result.record is None
    assert result.reason_codes == ("handoff-oversized",)


def test_candidate_module_has_no_prohibited_operations() -> None:
    source = CANDIDATE_MODULE.read_text(encoding="utf-8")
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
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
    }
    assert not {
        name
        for name in imported
        if any(
            name == prohibited
            or name.startswith(prohibited + ".")
            for prohibited in prohibited_imports
        )
    }

    prohibited_calls = {
        "open",
        "rank",
        "score",
        "embed",
        "ocr",
        "decode_image",
        "generate_image",
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
    }
    assert not called & prohibited_calls
