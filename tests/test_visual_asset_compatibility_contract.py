from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

import instructional_workflow_contracts.visual_asset_compatibility as module
from instructional_workflow_contracts import (
    AuthorityEvidence,
    ValidationStatus,
    canonical_size,
)


FIXTURES = (
    Path(__file__).parent
    / "fixtures"
    / "instructional_workflow_contracts"
)
MODULE = (
    Path(__file__).parents[1]
    / "src"
    / "instructional_workflow_contracts"
    / "visual_asset_compatibility.py"
)


def fixture() -> dict[str, object]:
    return json.loads(
        (
            FIXTURES
            / "valid_visual_asset_compatibility.json"
        ).read_text(encoding="utf-8")
    )


def fixture_v2() -> dict[str, object]:
    return json.loads(
        (
            FIXTURES
            / "valid_visual_asset_compatibility_v2.json"
        ).read_text(encoding="utf-8")
    )


def classify(value: dict[str, object]):
    result = module.validate_visual_asset_compatibility_evidence(value)
    payload = (
        result.record.to_dict()
        if result.record is not None
        else None
    )
    return result, payload


def test_valid_evidence_is_deterministic_immutable_and_authority_false() -> None:
    value = fixture()
    before = copy.deepcopy(value)

    first, first_payload = classify(value)
    second, second_payload = classify(copy.deepcopy(value))

    assert first.status is ValidationStatus.VALID
    assert first.record is not None
    assert second.record is not None
    assert first_payload is not None
    assert second_payload is not None
    assert first_payload["classification"] == "eligible"
    assert first_payload["reason_codes"] == []
    assert first.record.fingerprint == second.record.fingerprint
    assert first.record.record_id == second.record.record_id
    assert first_payload == second_payload
    assert value == before
    assert first.authority == first.record.authority == AuthorityEvidence()
    assert first_payload["authority"] == {
        "execution_authorized": False,
        "external_write_authorized": False,
        "production_authorized": False,
        "publication_authorized": False,
        "side_effects_performed": False,
    }
    assert canonical_size(first_payload) <= 16 * 1024


def test_zero_asset_match_routes_to_manual_review() -> None:
    value = fixture()
    value["compatibility_evidence"]["asset_reference"][  # type: ignore[index]
        "asset_id"
    ] = "asset-missing"

    result, payload = classify(value)

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.reason_codes == (
        "manual-review-asset-association-missing",
    )
    assert payload is not None
    assert payload["classification"] == "manual-review-required"
    assert payload["matched_asset"] is None


def test_multiple_exact_asset_matches_are_invalid() -> None:
    value = fixture()
    manifest = value["artifact_manifest"]  # type: ignore[index]
    duplicate = copy.deepcopy(manifest["assets"][0])  # type: ignore[index]
    manifest["assets"].append(duplicate)  # type: ignore[index]

    result, payload = classify(value)

    assert result.status is ValidationStatus.INVALID
    assert payload is None
    assert result.reason_codes == ("asset-compatibility-invalid-manifest",)


def test_library_and_manifest_drive_identity_must_match() -> None:
    value = fixture()
    value["library_record"]["drive_file_id"] = (  # type: ignore[index]
        "different-file"
    )

    result, payload = classify(value)

    assert result.status is ValidationStatus.INVALID
    assert payload is None
    assert result.reason_codes == ("identity-invalid",)


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (
            lambda value: value["compatibility_evidence"]["purpose"].update(  # type: ignore[index]
                {"role_types": [], "decorative_only": False}
            ),
            "manual-review-asset-purpose-missing",
        ),
        (
            lambda value: value["compatibility_evidence"]["accessibility"].update(  # type: ignore[index]
                {"review_state": "not-assessed"}
            ),
            "manual-review-asset-accessibility",
        ),
        (
            lambda value: value["compatibility_evidence"]["accessibility"].update(  # type: ignore[index]
                {"description_state": "manual-review-required"}
            ),
            "manual-review-asset-accessibility-description",
        ),
        (
            lambda value: value["compatibility_evidence"]["orientation"].update(  # type: ignore[index]
                {"aspect_state": "unspecified"}
            ),
            "manual-review-asset-orientation",
        ),
        (
            lambda value: value["compatibility_evidence"]["approved_use"].update(  # type: ignore[index]
                {"state": "pending"}
            ),
            "manual-review-asset-approved-use",
        ),
        (
            lambda value: value["compatibility_evidence"]["freshness"].update(  # type: ignore[index]
                {"stale": True}
            ),
            "manual-review-asset-compatibility-stale",
        ),
    ],
)
def test_manual_review_categories_remain_distinct(
    mutation,
    expected_reason: str,
) -> None:
    value = fixture()
    mutation(value)

    result, payload = classify(value)

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert payload is not None
    assert payload["classification"] == "manual-review-required"
    assert expected_reason in result.reason_codes
    assert expected_reason in payload["reason_codes"]


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (
            lambda value: value["compatibility_evidence"]["purpose"].update(  # type: ignore[index]
                {"decorative_only": True}
            ),
            "asset-purpose-decorative-only",
        ),
        (
            lambda value: value["compatibility_evidence"]["accessibility"].update(  # type: ignore[index]
                {"review_state": "fail"}
            ),
            "asset-accessibility-failed",
        ),
        (
            lambda value: value["compatibility_evidence"]["accessibility"].update(  # type: ignore[index]
                {
                    "description_state": "missing",
                    "description_reference": None,
                }
            ),
            "asset-accessibility-description-missing",
        ),
        (
            lambda value: value["compatibility_evidence"]["orientation"].update(  # type: ignore[index]
                {"aspect_state": "mismatch"}
            ),
            "asset-orientation-mismatch",
        ),
        (
            lambda value: value["compatibility_evidence"]["approved_use"].update(  # type: ignore[index]
                {"state": "denied"}
            ),
            "asset-approved-use-rejected",
        ),
        (
            lambda value: value["compatibility_evidence"]["approved_use"].update(  # type: ignore[index]
                {"state": "expired"}
            ),
            "asset-approved-use-rejected",
        ),
    ],
)
def test_hard_rejection_categories_remain_distinct(
    mutation,
    expected_reason: str,
) -> None:
    value = fixture()
    mutation(value)

    result, payload = classify(value)

    assert result.status is ValidationStatus.VALID
    assert result.reason_codes == ()
    assert payload is not None
    assert payload["classification"] == "hard-rejection"
    assert expected_reason in payload["reason_codes"]


def test_role_types_are_unique_bounded_and_canonically_ordered() -> None:
    value = fixture()
    value["compatibility_evidence"]["purpose"]["role_types"] = [  # type: ignore[index]
        "worked-example",
        "comparison",
    ]
    value["compatibility_evidence"]["approved_use"]["role_types"] = [  # type: ignore[index]
        "worked-example",
        "comparison",
    ]

    result, payload = classify(value)

    assert result.status is ValidationStatus.VALID
    assert payload is not None
    assert payload["purpose"]["role_types"] == [
        "comparison",
        "worked-example",
    ]
    assert payload["approved_use"]["role_types"] == [
        "comparison",
        "worked-example",
    ]

    duplicate = fixture()
    duplicate["compatibility_evidence"]["purpose"]["role_types"] = [  # type: ignore[index]
        "comparison",
        "comparison",
    ]
    assert classify(duplicate)[0].status is ValidationStatus.INVALID


def test_unknown_roles_and_unknown_fields_fail_closed() -> None:
    unknown_role = fixture()
    unknown_role["compatibility_evidence"]["purpose"]["role_types"] = [  # type: ignore[index]
        "decorative-photo"
    ]
    assert classify(unknown_role)[0].status is ValidationStatus.INVALID

    unknown_field = fixture()
    unknown_field["compatibility_evidence"]["caption"] = (  # type: ignore[index]
        "free-form compatibility"
    )
    assert classify(unknown_field)[0].status is ValidationStatus.INVALID


def test_free_form_library_fields_cannot_manufacture_eligibility() -> None:
    value = fixture()
    value["compatibility_evidence"]["purpose"].update(  # type: ignore[index]
        {
            "role_types": [],
            "decorative_only": False,
        }
    )
    value["library_record"]["asset_title"] = (  # type: ignore[index]
        "Perfect worked example"
    )
    value["library_record"]["approved_use"] = (  # type: ignore[index]
        "approved for everything"
    )
    value["library_record"]["extra_fields"] = {  # type: ignore[index]
        "role_type": "worked-example",
        "orientation": "landscape",
        "accessibility": "pass",
    }

    result, payload = classify(value)

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert payload is not None
    assert payload["classification"] == "manual-review-required"
    assert "manual-review-asset-purpose-missing" in result.reason_codes


def test_manifest_reference_revision_and_fingerprint_must_match() -> None:
    revision = fixture()
    revision["compatibility_evidence"]["manifest_reference"][  # type: ignore[index]
        "record_revision"
    ] = 2
    revision_result, revision_payload = classify(revision)
    assert revision_result.status is ValidationStatus.INVALID
    assert revision_payload is None
    assert revision_result.reason_codes == ("identity-invalid",)

    fingerprint = fixture()
    fingerprint["compatibility_evidence"]["manifest_reference"][  # type: ignore[index]
        "fingerprint"
    ] = "f" * 64
    fingerprint_result, fingerprint_payload = classify(fingerprint)
    assert fingerprint_result.status is ValidationStatus.INVALID
    assert fingerprint_payload is None
    assert fingerprint_result.reason_codes == ("identity-invalid",)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("manifest_record_revision", 2),
        ("manifest_fingerprint", "f" * 64),
        ("manifest_verified_at", "2026-08-03T00:00:00Z"),
    ],
)
def test_freshness_manifest_identity_must_match(
    field: str,
    replacement: object,
) -> None:
    value = fixture()
    value["compatibility_evidence"]["freshness"][field] = replacement  # type: ignore[index]

    result, payload = classify(value)

    assert result.status is ValidationStatus.INVALID
    assert payload is None
    assert result.reason_codes == ("identity-invalid",)


def test_authority_values_cannot_be_true() -> None:
    for key in fixture()["compatibility_evidence"]["authority"]:  # type: ignore[index]
        value = fixture()
        value["compatibility_evidence"]["authority"][key] = True  # type: ignore[index]
        result, payload = classify(value)
        assert result.status is ValidationStatus.INVALID
        assert payload is None
        assert result.reason_codes == ("authority-invalid",)


def test_exact_types_and_bounds_fail_closed() -> None:
    wrong_type = fixture()
    wrong_type["compatibility_evidence"]["purpose"]["decorative_only"] = 0  # type: ignore[index]
    assert classify(wrong_type)[0].status is ValidationStatus.INVALID

    too_many = fixture()
    too_many["compatibility_evidence"]["approved_use"]["material_types"] = [  # type: ignore[index]
        f"material-{index}"
        for index in range(module.MAX_MATERIAL_TYPES + 1)
    ]
    assert classify(too_many)[0].status is ValidationStatus.INVALID


def test_module_has_no_prohibited_imports_or_compute_operations() -> None:
    source = MODULE.read_text(encoding="utf-8")
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


def test_valid_v2_evidence_is_deterministic_and_preserves_cohesion() -> None:
    value = fixture_v2()
    before = copy.deepcopy(value)

    first, first_payload = classify(value)
    second, second_payload = classify(copy.deepcopy(value))

    assert first.status is ValidationStatus.VALID
    assert first.record is not None
    assert second.record is not None
    assert first_payload is not None
    assert second_payload is not None
    assert first.record.contract_version == module.V2_CONTRACT_ID
    assert first_payload["contract_version"] == module.V2_CONTRACT_ID
    assert first_payload["classification"] == "eligible"
    assert first_payload["reason_codes"] == []
    assert first_payload["cohesion_profile"] == value[
        "compatibility_evidence"
    ]["cohesion_profile"]
    assert first.record.record_id == second.record.record_id
    assert first.record.fingerprint == second.record.fingerprint
    assert first_payload == second_payload
    assert value == before
    assert first_payload["authority"] == {
        "execution_authorized": False,
        "external_write_authorized": False,
        "production_authorized": False,
        "publication_authorized": False,
        "side_effects_performed": False,
    }


def test_contract_versions_enforce_exact_evidence_fields() -> None:
    v1_with_profile = fixture()
    v1_with_profile["compatibility_evidence"]["cohesion_profile"] = (
        fixture_v2()["compatibility_evidence"]["cohesion_profile"]
    )
    assert classify(v1_with_profile)[0].status is ValidationStatus.INVALID

    v2_without_profile = fixture_v2()
    del v2_without_profile["compatibility_evidence"]["cohesion_profile"]
    assert classify(v2_without_profile)[0].status is ValidationStatus.INVALID

    unsupported = fixture()
    unsupported["compatibility_evidence"]["contract_version"] = (
        "curriculum-visual-asset-compatibility-v3"
    )
    result, payload = classify(unsupported)
    assert result.status is ValidationStatus.INVALID
    assert payload is None
    assert result.reason_codes == ("handoff-version-unsupported",)


def test_v1_identity_remains_exact_after_v2_extension() -> None:
    result, payload = classify(fixture())

    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    assert payload is not None
    assert result.record.record_id == (
        "visual-compatibility-f79ac899b7406a8b1d43a5e8"
    )
    assert result.record.fingerprint == (
        "8ca8aa4ce84090c608952f5f97c6062b7f9abd4800d7fbd5587c8a2d12bf0d80"
    )
    assert "cohesion_profile" not in payload


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("visual_style_family", "cinematic"),
        ("medium", "oil-paint"),
        ("representation_class", "collage"),
        ("palette_family", "neon"),
        ("line_treatment", "scribbled"),
        ("rendering_style", "hyperreal"),
        ("perspective", "fish-eye"),
        ("background_treatment", "gradient"),
    ],
)
def test_v2_cohesion_vocabularies_fail_closed(
    field: str,
    replacement: object,
) -> None:
    value = fixture_v2()
    value["compatibility_evidence"]["cohesion_profile"][field] = replacement

    result, payload = classify(value)

    assert result.status is ValidationStatus.INVALID
    assert payload is None


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("complexity_rating", 0),
        ("complexity_rating", 6),
        ("complexity_rating", True),
        ("complexity_rating", 2.5),
        ("cognitive_load_rating", 0),
        ("cognitive_load_rating", 6),
        ("cognitive_load_rating", False),
        ("cognitive_load_rating", "2"),
    ],
)
def test_v2_cohesion_ratings_require_built_in_integers_one_to_five(
    field: str,
    replacement: object,
) -> None:
    value = fixture_v2()
    value["compatibility_evidence"]["cohesion_profile"][field] = replacement

    result, payload = classify(value)

    assert result.status is ValidationStatus.INVALID
    assert payload is None
    assert result.reason_codes == ("asset-cohesion-rating-invalid",)


def test_v2_unspecified_cohesion_routes_to_manual_review() -> None:
    value = fixture_v2()
    value["compatibility_evidence"]["cohesion_profile"][
        "visual_style_family"
    ] = "unspecified"

    result, payload = classify(value)

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert payload is not None
    assert payload["classification"] == "manual-review-required"
    assert (
        "manual-review-asset-cohesion-unspecified"
        in result.reason_codes
    )


def test_v2_interface_capture_medium_conflict_hard_rejects() -> None:
    value = fixture_v2()
    profile = value["compatibility_evidence"]["cohesion_profile"]
    profile["representation_class"] = "interface-capture"
    profile["medium"] = "digital"

    result, payload = classify(value)

    assert result.status is ValidationStatus.VALID
    assert payload is not None
    assert payload["classification"] == "hard-rejection"
    assert (
        "asset-cohesion-representation-medium-conflict"
        in payload["reason_codes"]
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("state", "unknown"),
        ("stale", 0),
        ("contradictory", 1),
        ("reviewer_ref", ""),
        ("reviewed_at", "not-a-timestamp"),
        ("evidence_reference", ""),
    ],
)
def test_v2_audience_evidence_types_fail_closed(
    field: str,
    replacement: object,
) -> None:
    value = fixture_v2()
    audience = value["compatibility_evidence"]["cohesion_profile"][
        "audience_compatibility"
    ]
    audience[field] = replacement

    result, payload = classify(value)

    assert result.status is ValidationStatus.INVALID
    assert payload is None


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (
            lambda audience: audience.update({"state": "not-assessed"}),
            "manual-review-asset-audience",
        ),
        (
            lambda audience: audience.update({"stale": True}),
            "manual-review-asset-audience-stale",
        ),
        (
            lambda audience: audience.update({"contradictory": True}),
            "manual-review-asset-audience-contradictory",
        ),
        (
            lambda audience: audience.update({"reviewer_ref": None}),
            "manual-review-asset-audience-unattributed",
        ),
    ],
)
def test_v2_audience_uncertainty_routes_to_manual_review(
    mutation,
    expected_reason: str,
) -> None:
    value = fixture_v2()
    audience = value["compatibility_evidence"]["cohesion_profile"][
        "audience_compatibility"
    ]
    mutation(audience)

    result, payload = classify(value)

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert payload is not None
    assert payload["classification"] == "manual-review-required"
    assert expected_reason in result.reason_codes


def test_v2_attributed_audience_rejection_hard_rejects() -> None:
    value = fixture_v2()
    audience = value["compatibility_evidence"]["cohesion_profile"][
        "audience_compatibility"
    ]
    audience["state"] = "rejected"

    result, payload = classify(value)

    assert result.status is ValidationStatus.VALID
    assert payload is not None
    assert payload["classification"] == "hard-rejection"
    assert "asset-audience-incompatible" in payload["reason_codes"]


def test_v2_unattributed_audience_rejection_requires_manual_review() -> None:
    value = fixture_v2()
    audience = value["compatibility_evidence"]["cohesion_profile"][
        "audience_compatibility"
    ]
    audience["state"] = "rejected"
    audience["reviewer_ref"] = None

    result, payload = classify(value)

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert payload is not None
    assert payload["classification"] == "manual-review-required"
    assert (
        "manual-review-asset-audience-unattributed"
        in result.reason_codes
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("visual_style_family", "cinematic"),
        ("medium", "oil-paint"),
        ("representation_class", "collage"),
        ("palette_family", "neon"),
        ("line_treatment", "scribbled"),
        ("rendering_style", "hyperreal"),
        ("perspective", "fish-eye"),
        ("background_treatment", "gradient"),
    ],
)
def test_v2_cohesion_vocabularies_fail_closed(
    field: str,
    replacement: object,
) -> None:
    value = fixture_v2()
    value["compatibility_evidence"]["cohesion_profile"][field] = replacement

    result, payload = classify(value)

    assert result.status is ValidationStatus.INVALID
    assert payload is None


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("complexity_rating", 0),
        ("complexity_rating", 6),
        ("complexity_rating", True),
        ("complexity_rating", 2.5),
        ("cognitive_load_rating", 0),
        ("cognitive_load_rating", 6),
        ("cognitive_load_rating", False),
        ("cognitive_load_rating", "2"),
    ],
)
def test_v2_cohesion_ratings_require_built_in_integers_one_to_five(
    field: str,
    replacement: object,
) -> None:
    value = fixture_v2()
    value["compatibility_evidence"]["cohesion_profile"][field] = replacement

    result, payload = classify(value)

    assert result.status is ValidationStatus.INVALID
    assert payload is None
    assert result.reason_codes == ("asset-cohesion-rating-invalid",)


def test_v2_unspecified_cohesion_routes_to_manual_review() -> None:
    value = fixture_v2()
    value["compatibility_evidence"]["cohesion_profile"][
        "visual_style_family"
    ] = "unspecified"

    result, payload = classify(value)

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert payload is not None
    assert payload["classification"] == "manual-review-required"
    assert (
        "manual-review-asset-cohesion-unspecified"
        in result.reason_codes
    )


def test_v2_interface_capture_medium_conflict_hard_rejects() -> None:
    value = fixture_v2()
    profile = value["compatibility_evidence"]["cohesion_profile"]
    profile["representation_class"] = "interface-capture"
    profile["medium"] = "digital"

    result, payload = classify(value)

    assert result.status is ValidationStatus.VALID
    assert payload is not None
    assert payload["classification"] == "hard-rejection"
    assert (
        "asset-cohesion-representation-medium-conflict"
        in payload["reason_codes"]
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("state", "unknown"),
        ("stale", 0),
        ("contradictory", 1),
        ("reviewer_ref", ""),
        ("reviewed_at", "not-a-timestamp"),
        ("evidence_reference", ""),
    ],
)
def test_v2_audience_evidence_types_fail_closed(
    field: str,
    replacement: object,
) -> None:
    value = fixture_v2()
    audience = value["compatibility_evidence"]["cohesion_profile"][
        "audience_compatibility"
    ]
    audience[field] = replacement

    result, payload = classify(value)

    assert result.status is ValidationStatus.INVALID
    assert payload is None


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (
            lambda audience: audience.update({"state": "not-assessed"}),
            "manual-review-asset-audience",
        ),
        (
            lambda audience: audience.update({"stale": True}),
            "manual-review-asset-audience-stale",
        ),
        (
            lambda audience: audience.update({"contradictory": True}),
            "manual-review-asset-audience-contradictory",
        ),
        (
            lambda audience: audience.update({"reviewer_ref": None}),
            "manual-review-asset-audience-unattributed",
        ),
    ],
)
def test_v2_audience_uncertainty_routes_to_manual_review(
    mutation,
    expected_reason: str,
) -> None:
    value = fixture_v2()
    audience = value["compatibility_evidence"]["cohesion_profile"][
        "audience_compatibility"
    ]
    mutation(audience)

    result, payload = classify(value)

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert payload is not None
    assert payload["classification"] == "manual-review-required"
    assert expected_reason in result.reason_codes


def test_v2_attributed_audience_rejection_hard_rejects() -> None:
    value = fixture_v2()
    audience = value["compatibility_evidence"]["cohesion_profile"][
        "audience_compatibility"
    ]
    audience["state"] = "rejected"

    result, payload = classify(value)

    assert result.status is ValidationStatus.VALID
    assert payload is not None
    assert payload["classification"] == "hard-rejection"
    assert "asset-audience-incompatible" in payload["reason_codes"]


def test_v2_unattributed_audience_rejection_requires_manual_review() -> None:
    value = fixture_v2()
    audience = value["compatibility_evidence"]["cohesion_profile"][
        "audience_compatibility"
    ]
    audience["state"] = "rejected"
    audience["reviewer_ref"] = None

    result, payload = classify(value)

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert payload is not None
    assert payload["classification"] == "manual-review-required"
    assert (
        "manual-review-asset-audience-unattributed"
        in result.reason_codes
    )
