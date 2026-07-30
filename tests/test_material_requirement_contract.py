from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

import instructional_workflow_contracts.material_requirement as material_module
from instructional_workflow_contracts import AuthorityEvidence, ValidationStatus, canonical_size
from instructional_workflow_contracts.material_requirement import (
    COMPLETENESS_STATES,
    MAX_ASSETS,
    MAX_REQUIRED_SECTIONS,
    MAX_RESULT_BYTES,
    MAX_TEMPLATES,
    SUPPORTED_ARTIFACT_TYPES,
    material_requirement_source_fingerprint,
    validate_material_requirement,
)


def _owned_ref(stable_id: str, owner: str) -> dict[str, object]:
    return {
        "stable_id": stable_id,
        "owner": owner,
        "contract_version": "curriculum-workflow-handoff-v1",
        "record_revision": 1,
        "fingerprint": "a" * 64,
    }


def valid_requirement() -> dict[str, object]:
    value: dict[str, object] = {
        "identity": {
            "contract_version": "curriculum-material-requirement-v1",
            "requirement_id": "requirement-1",
            "record_revision": 1,
            "course_ref": "course-1",
            "unit_ref": "unit-1",
            "lesson_ref": "lesson-1",
            "created_at": "2026-07-30T00:00:00Z",
            "created_by": "instructional-materials-coach",
            "source_fingerprint": "0" * 64,
        },
        "artifact": {
            "artifact_type": "worksheet",
            "subject_metadata": "content-domain-neutral",
        },
        "instructional": {
            "purpose": "Provide bounded guided practice.",
            "audience": "students",
            "required_sections": ["directions", "practice"],
        },
        "handoff_reference": {
            "handoff_id": "handoff-1",
            "contract_version": "curriculum-workflow-handoff-v1",
            "record_revision": 1,
            "fingerprint": "b" * 64,
        },
        "learning_evidence": {
            "learning_objective_ref": _owned_ref("objective-1", "unit-alignment-agent"),
            "success_criteria_ref": _owned_ref("criteria-1", "unit-alignment-agent"),
            "evidence_target_ref": _owned_ref("evidence-1", "unit-alignment-agent"),
            "alignment_owner": "unit-alignment-agent",
        },
        "modeling": {
            "modeling_readiness_ref": _owned_ref("modeling-1", "teacher-modeling-coach"),
            "materials_extract_ref": _owned_ref("extract-1", "teacher-modeling-coach"),
            "modeling_owner": "teacher-modeling-coach",
        },
        "requirements": {
            "vocabulary_references": [
                _owned_ref("vocabulary-1", "unit-alignment-agent")
            ],
            "accessibility_requirements": ["keyboard-readable", "plain-language"],
            "content_requirements": ["cite-supplied-sources"],
            "classroom_use_requirements": ["teacher-review-before-use"],
        },
        "assets": [
            {
                "asset_id": "asset-1",
                "stable_ref": "asset-ref-1",
                "access_state": "verified",
                "permission_state": "permission-documented",
                "provenance_state": "confirmed",
            }
        ],
        "templates": [
            {
                "template_id": "template-1",
                "stable_ref": "template-ref-1",
                "access_state": "verified",
                "permission_state": "cleared-internal",
            }
        ],
        "destination": {
            "destination_id": "destination-1",
            "destination_class": "approved-google-drive-folder",
            "verification_state": "verified",
            "exact_reference": "drive-folder-reference-evidence",
        },
        "ai_review": {
            "ai_assisted_generation_permitted": True,
            "human_review_owner": "instructional-materials-coach",
            "accessibility_review_required": True,
            "nondiscrimination_review_required": True,
        },
        "provenance": {
            "citation_expectations": "Cite supplied sources and retained asset evidence.",
            "provenance_state": "confirmed",
            "copyright_state": "permission-documented",
            "license_state": "licensed",
            "asset_permission_state": "permission-documented",
        },
        "prohibited_data": {
            "student_identifying_data": False,
            "protected_attributes": False,
            "raw_student_work": False,
            "permanent_learner_profile": False,
        },
        "completeness": {
            "state": "ready-for-planning",
            "blockers": [],
            "reason_codes": [],
        },
        "authority": {
            "execution_authorized": False,
            "external_write_authorized": False,
            "production_authorized": False,
            "publication_authorized": False,
            "side_effects_performed": False,
        },
    }
    value["identity"]["source_fingerprint"] = (  # type: ignore[index]
        material_requirement_source_fingerprint(value)
    )
    return value


def _refresh_fingerprint(value: dict[str, object]) -> None:
    value["identity"]["source_fingerprint"] = (  # type: ignore[index]
        material_requirement_source_fingerprint(value)
    )


def test_valid_requirement_is_deterministic_immutable_and_authority_false() -> None:
    supplied = valid_requirement()
    before = copy.deepcopy(supplied)
    first = validate_material_requirement(supplied)
    second = validate_material_requirement(copy.deepcopy(supplied))
    assert first.status is ValidationStatus.VALID
    assert first.record is not None and second.record is not None
    assert first.record.fingerprint == second.record.fingerprint
    assert first.authority == AuthorityEvidence()
    assert first.record.authority == AuthorityEvidence()
    assert first.record.to_dict()["authority"]["side_effects_performed"] is False
    assert canonical_size(first.record.to_dict()) <= MAX_RESULT_BYTES
    assert supplied == before


@pytest.mark.parametrize("artifact_type", sorted(SUPPORTED_ARTIFACT_TYPES))
def test_every_supported_artifact_type_is_valid(artifact_type: str) -> None:
    value = valid_requirement()
    value["artifact"]["artifact_type"] = artifact_type  # type: ignore[index]
    _refresh_fingerprint(value)
    assert validate_material_requirement(value).status is ValidationStatus.VALID


def test_unsupported_artifact_type_fails_with_finite_reason() -> None:
    value = valid_requirement()
    value["artifact"]["artifact_type"] = "interactive-hologram"  # type: ignore[index]
    _refresh_fingerprint(value)
    result = validate_material_requirement(value)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("material-unsupported-artifact-type",)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("learning_evidence", "alignment_owner"), "qa-test-agent"),
        (("learning_evidence", "learning_objective_ref", "owner"), "qa-test-agent"),
        (("modeling", "modeling_owner"), "unit-alignment-agent"),
        (("modeling", "materials_extract_ref", "owner"), "unit-alignment-agent"),
    ],
)
def test_missing_or_conflicting_owner_evidence_fails(
    path: tuple[str, ...], replacement: str
) -> None:
    value = valid_requirement()
    target: object = value
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = replacement  # type: ignore[index]
    _refresh_fingerprint(value)
    result = validate_material_requirement(value)
    assert "material-missing-owner-evidence" in result.reason_codes


def test_incompatible_handoff_version_and_malformed_fingerprint_fail() -> None:
    wrong_version = valid_requirement()
    wrong_version["handoff_reference"]["contract_version"] = (  # type: ignore[index]
        "future-handoff-v2"
    )
    _refresh_fingerprint(wrong_version)
    assert "material-incompatible-handoff" in validate_material_requirement(
        wrong_version
    ).reason_codes

    bad_fingerprint = valid_requirement()
    bad_fingerprint["handoff_reference"]["fingerprint"] = "not-a-sha"  # type: ignore[index]
    _refresh_fingerprint(bad_fingerprint)
    assert validate_material_requirement(bad_fingerprint).status is ValidationStatus.INVALID


def test_incompatible_source_fingerprint_fails() -> None:
    value = valid_requirement()
    value["identity"]["source_fingerprint"] = "f" * 64  # type: ignore[index]
    result = validate_material_requirement(value)
    assert result.reason_codes == ("material-incompatible-fingerprint",)


def test_duplicate_asset_and_template_ids_fail() -> None:
    duplicate_asset = valid_requirement()
    duplicate_asset["assets"].append(  # type: ignore[union-attr]
        copy.deepcopy(duplicate_asset["assets"][0])  # type: ignore[index]
    )
    _refresh_fingerprint(duplicate_asset)
    assert "material-duplicate-asset" in validate_material_requirement(
        duplicate_asset
    ).reason_codes

    duplicate_template = valid_requirement()
    duplicate_template["templates"].append(  # type: ignore[union-attr]
        copy.deepcopy(duplicate_template["templates"][0])  # type: ignore[index]
    )
    _refresh_fingerprint(duplicate_template)
    assert "material-duplicate-template" in validate_material_requirement(
        duplicate_template
    ).reason_codes


def test_unverified_asset_template_and_destination_fail_closed() -> None:
    asset = valid_requirement()
    asset["assets"][0]["access_state"] = "unverified"  # type: ignore[index]
    _refresh_fingerprint(asset)
    assert "material-unverified-asset" in validate_material_requirement(asset).reason_codes

    template = valid_requirement()
    template["templates"][0]["access_state"] = "denied"  # type: ignore[index]
    _refresh_fingerprint(template)
    assert "material-unverified-template" in validate_material_requirement(
        template
    ).reason_codes

    destination = valid_requirement()
    destination["destination"]["verification_state"] = "ambiguous"  # type: ignore[index]
    _refresh_fingerprint(destination)
    assert "material-ambiguous-destination" in validate_material_requirement(
        destination
    ).reason_codes


def test_ai_review_provenance_permission_and_prohibited_data_failures() -> None:
    owner = valid_requirement()
    owner["ai_review"]["human_review_owner"] = "unregistered-owner"  # type: ignore[index]
    _refresh_fingerprint(owner)
    assert "material-ai-review-owner-missing" in validate_material_requirement(
        owner
    ).reason_codes

    provenance = valid_requirement()
    provenance["provenance"]["license_state"] = "unclear"  # type: ignore[index]
    _refresh_fingerprint(provenance)
    assert "material-provenance-incomplete" in validate_material_requirement(
        provenance
    ).reason_codes

    permission = valid_requirement()
    permission["assets"][0]["permission_state"] = "restricted"  # type: ignore[index]
    _refresh_fingerprint(permission)
    assert "material-permission-incomplete" in validate_material_requirement(
        permission
    ).reason_codes

    prohibited = valid_requirement()
    prohibited["prohibited_data"]["student_identifying_data"] = True  # type: ignore[index]
    _refresh_fingerprint(prohibited)
    assert "material-prohibited-data" in validate_material_requirement(
        prohibited
    ).reason_codes


@pytest.mark.parametrize("state", sorted(COMPLETENESS_STATES))
def test_completeness_is_validated_but_never_grants_authority(state: str) -> None:
    value = valid_requirement()
    value["completeness"]["state"] = state  # type: ignore[index]
    value["completeness"]["blockers"] = (  # type: ignore[index]
        ["material-incomplete"] if state == "blocked" else []
    )
    value["completeness"]["reason_codes"] = (  # type: ignore[index]
        ["material-incomplete"]
        if state in {"incomplete", "manual-review-required"}
        else []
    )
    _refresh_fingerprint(value)
    result = validate_material_requirement(value)
    assert result.status is ValidationStatus.VALID
    assert result.authority == AuthorityEvidence()
    assert result.record is not None
    assert result.record.to_dict()["authority"] == {
        "execution_authorized": False,
        "external_write_authorized": False,
        "production_authorized": False,
        "publication_authorized": False,
        "side_effects_performed": False,
    }


def test_caller_cannot_set_any_authority_true() -> None:
    for key in (
        "execution_authorized",
        "external_write_authorized",
        "production_authorized",
        "publication_authorized",
        "side_effects_performed",
    ):
        value = valid_requirement()
        value["authority"][key] = True  # type: ignore[index]
        _refresh_fingerprint(value)
        assert "authority-invalid" in validate_material_requirement(value).reason_codes


def test_exact_asset_template_and_section_bounds_and_one_over() -> None:
    assets = valid_requirement()
    assets["assets"] = [
        {
            "asset_id": f"asset-{index}",
            "stable_ref": f"asset-ref-{index}",
            "access_state": "verified",
            "permission_state": "permission-documented",
            "provenance_state": "confirmed",
        }
        for index in range(MAX_ASSETS)
    ]
    _refresh_fingerprint(assets)
    assert validate_material_requirement(assets).status is ValidationStatus.VALID
    assets["assets"].append(  # type: ignore[union-attr]
        {
            "asset_id": "asset-over",
            "stable_ref": "asset-ref-over",
            "access_state": "verified",
            "permission_state": "permission-documented",
            "provenance_state": "confirmed",
        }
    )
    _refresh_fingerprint(assets)
    assert "handoff-oversized" in validate_material_requirement(assets).reason_codes

    templates = valid_requirement()
    templates["templates"] = [
        {
            "template_id": f"template-{index}",
            "stable_ref": f"template-ref-{index}",
            "access_state": "verified",
            "permission_state": "cleared-internal",
        }
        for index in range(MAX_TEMPLATES)
    ]
    _refresh_fingerprint(templates)
    assert validate_material_requirement(templates).status is ValidationStatus.VALID
    templates["templates"].append(  # type: ignore[union-attr]
        {
            "template_id": "template-over",
            "stable_ref": "template-ref-over",
            "access_state": "verified",
            "permission_state": "cleared-internal",
        }
    )
    _refresh_fingerprint(templates)
    assert "handoff-oversized" in validate_material_requirement(templates).reason_codes

    sections = valid_requirement()
    sections["instructional"]["required_sections"] = [  # type: ignore[index]
        f"section-{index}" for index in range(MAX_REQUIRED_SECTIONS)
    ]
    _refresh_fingerprint(sections)
    assert validate_material_requirement(sections).status is ValidationStatus.VALID
    sections["instructional"]["required_sections"].append(  # type: ignore[index,union-attr]
        "section-over"
    )
    _refresh_fingerprint(sections)
    assert "handoff-oversized" in validate_material_requirement(sections).reason_codes


class HostileMapping(dict):
    def __iter__(self):
        raise AssertionError("custom mapping iteration executed")


class HostileString(str):
    pass


def test_hostile_custom_objects_fail_without_invoking_behavior() -> None:
    assert validate_material_requirement(HostileMapping()).status is ValidationStatus.INVALID
    value = valid_requirement()
    value["identity"]["requirement_id"] = HostileString("requirement-1")  # type: ignore[index]
    result = validate_material_requirement(value)
    assert result.status is ValidationStatus.INVALID
    assert "handoff-wrong-type" in result.reason_codes


def test_unknown_fields_fail_closed() -> None:
    value = valid_requirement()
    value["extra"] = {}
    _refresh_fingerprint(value)
    assert "material-unknown-field" in validate_material_requirement(value).reason_codes


def test_shared_cw5a_helpers_are_used(monkeypatch: pytest.MonkeyPatch) -> None:
    value = valid_requirement()
    calls = {"normalize": 0, "fingerprint": 0}
    original_normalize = material_module.validate_and_normalize_json
    original_fingerprint = material_module.sha256_hex

    def normalize_spy(raw: object, *, max_bytes: int):
        calls["normalize"] += 1
        return original_normalize(raw, max_bytes=max_bytes)

    def fingerprint_spy(raw: object) -> str:
        calls["fingerprint"] += 1
        return original_fingerprint(raw)

    monkeypatch.setattr(material_module, "validate_and_normalize_json", normalize_spy)
    monkeypatch.setattr(material_module, "sha256_hex", fingerprint_spy)
    assert validate_material_requirement(value).status is ValidationStatus.VALID
    assert calls["normalize"] >= 2
    assert calls["fingerprint"] >= 2


def test_module_does_not_duplicate_cw5a_mechanics_or_import_side_effects() -> None:
    path = (
        Path(__file__).parents[1]
        / "src"
        / "instructional_workflow_contracts"
        / "material_requirement.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    class_names: set[str] = set()
    calls: set[str] = set()
    function_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, ast.ClassDef):
            class_names.add(node.name)
        elif isinstance(node, ast.FunctionDef):
            function_names.add(node.name)
        elif isinstance(node, ast.Call):
            calls.add(
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
    assert imports <= {"__future__", "typing", "common"}
    assert class_names.isdisjoint(
        {"AuthorityEvidence", "ValidationResult", "ValidationStatus", "ValidatedRecord"}
    )
    assert function_names.isdisjoint(
        {"canonical_json_bytes", "canonical_size", "sha256_hex", "freeze_json"}
    )
    assert calls.isdisjoint(
        {
            "open",
            "getenv",
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
